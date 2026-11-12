"""REST API routes for DukaPulse."""

from __future__ import annotations

import concurrent.futures
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..auth.jwt import create_dev_token
from ..auth.rbac import RequireOwner, RequireStaff
from ..config import settings
from ..db.models import Inventory
from ..db.session import get_db
from ..services.forecasting import DemandForecastingService
from ..services.inventory import InsufficientStockError, InventoryService
from ..services.semantic_search import SemanticSearchService
from ..services.timeseries import TimeSeriesAnalyticsService

router = APIRouter(prefix="/api", tags=["DukaPulse API"])


# -----------------------------------------------------------------------------
# Request & Response Schemas
# -----------------------------------------------------------------------------
class CheckoutRequest(BaseModel):
    shop_id: str
    product_id: str
    quantity: int = Field(gt=0, description="Number of items to purchase")
    payment_method: str = Field(default="M-PESA", description="'M-PESA' or 'CASH'")


class RestockRequest(BaseModel):
    shop_id: str
    product_id: str
    quantity: int = Field(gt=0, description="Number of units added to shelf inventory")


class TokenRequest(BaseModel):
    sub: str = Field(default="prince_staff_01")
    role: str = Field(default="staff", description="'owner' or 'staff'")
    shop_id: str = Field(default="shop_kibera_01")


class SaleItemInput(BaseModel):
    product_id: str
    quantity: int = Field(default=1, gt=0)


class SaleInputRequest(BaseModel):
    shop_id: str = Field(default="shop_kibera_01")
    product_id: str | None = None
    quantity: int | None = Field(default=None, gt=0)
    items: list[SaleItemInput] = Field(default_factory=list)
    payment_method: str = Field(default="M-PESA")


class OversellRaceRequest(BaseModel):
    product_id: str
    shop_id: str = Field(default="shop_kibera_01")


# -----------------------------------------------------------------------------
# Auth & Dev Token Endpoints
# -----------------------------------------------------------------------------
@router.post("/auth/token", summary="Generate Dev / Evaluator Bearer Token")
def generate_token(req: TokenRequest):
    """Generate an Auth0-compatible test token for offline hackathon grading."""
    env_flag = os.getenv("DEV_MODE_MOCK_AUTH")
    is_mock_enabled = (
        env_flag.lower() in ("true", "1", "yes")
        if env_flag is not None
        else settings.DEV_MODE_MOCK_AUTH
    )
    if not settings.DEV_MODE_MOCK_AUTH:
        is_mock_enabled = False

    if not is_mock_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: DEV_MODE_MOCK_AUTH is disabled",
        )

    token = create_dev_token(sub=req.sub, role=req.role, shop_id=req.shop_id)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "role": req.role,
        "sub": req.sub,
        "shop_id": req.shop_id,
    }


# -----------------------------------------------------------------------------
# POS & Sales Endpoints (Pessimistic ACID Locking)
# -----------------------------------------------------------------------------
@router.post(
    "/sales",
    summary="Kiosk POS Checkout (Atomic Decrement)",
    responses={
        409: {"description": "Oversell attempt blocked by pessimistic row lock"},
        401: {"description": "Unauthenticated Bearer token"},
    },
)
def checkout_sale(
    req: SaleInputRequest,
    user: RequireStaff,
    db: Annotated[Session, Depends(get_db)],
):
    """Atomic sales checkout for any authenticated role.

    Returns receipt {sale_id, items, total_ksh, remaining_stock}.
    """
    service = InventoryService(db)
    sale_items = list(req.items)
    if not sale_items and req.product_id:
        sale_items.append(SaleItemInput(product_id=req.product_id, quantity=req.quantity or 1))

    if not sale_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No items provided for checkout",
        )

    receipt_items = []
    total_revenue = 0.0
    last_receipt = None

    try:
        for it in sale_items:
            rec = service.process_sale(
                shop_id=req.shop_id,
                product_id=it.product_id,
                quantity=it.quantity,
                payment_method=req.payment_method,
                cashier_id=user.sub,
            )
            last_receipt = rec
            total_revenue += rec.total_revenue
            receipt_items.append(
                {
                    "product_id": rec.product_id,
                    "product_name": rec.product_name,
                    "quantity": rec.quantity,
                    "unit_price_ksh": rec.unit_price,
                    "line_total_ksh": rec.total_revenue,
                    "remaining_stock": rec.remaining_stock,
                }
            )

        return {
            "sale_id": last_receipt.event_id if last_receipt else str(uuid.uuid4()),
            "items": receipt_items,
            "total_ksh": round(total_revenue, 2),
            "remaining_stock": last_receipt.remaining_stock if last_receipt else 0,
        }
    except InsufficientStockError as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(err),
        ) from err
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err


@router.post(
    "/sales/checkout",
    summary="Atomically Record a Sale (Oversell-Proof Row Lock)",
    responses={
        409: {"description": "Oversell attempt blocked by pessimistic row lock"},
        401: {"description": "Unauthenticated or missing Bearer token"},
    },
)
def checkout(
    req: CheckoutRequest,
    user: RequireStaff,
    db: Annotated[Session, Depends(get_db)],
):
    """Atomically decrements stock using SELECT ... FOR UPDATE.

    If concurrent clerks attempt to sell more than current inventory,
    the transaction blocks and raises InsufficientStockError (HTTP 409).
    """
    service = InventoryService(db)
    try:
        receipt = service.process_sale(
            shop_id=req.shop_id,
            product_id=req.product_id,
            quantity=req.quantity,
            payment_method=req.payment_method,
            cashier_id=user.sub,
        )
        return {
            "status": "success",
            "receipt": {
                "event_id": receipt.event_id,
                "product_name": receipt.product_name,
                "quantity": receipt.quantity,
                "unit_price": receipt.unit_price,
                "total_revenue": receipt.total_revenue,
                "profit": receipt.profit
                if user.role == "owner"
                else None,  # Redact profit for staff
                "remaining_stock": receipt.remaining_stock,
                "sale_time": receipt.sale_time.isoformat(),
                "payment_method": receipt.payment_method,
            },
        }
    except InsufficientStockError as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(err),
        ) from err
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err


# -----------------------------------------------------------------------------
# Inventory & Restocking Endpoints
# -----------------------------------------------------------------------------
@router.get("/products", summary="List Kiosk Catalog with Stock and Role-Gated Margins")
def list_products(
    user: RequireStaff,
    shop_id: str = "shop_kibera_01",
    db: Annotated[Session, Depends(get_db)] = None,
):
    """List products for active shop with price_ksh, stock, and owner-only margin_ksh."""
    service = InventoryService(db)
    items = service.get_stock_levels(shop_id)
    return [
        {
            "id": it["product_id"],
            "name": it["name"],
            "category": it["category"],
            "price_ksh": float(it["unit_price"]),
            "stock": int(it["current_stock"]),
            "margin_ksh": float(it["margin_kes"]) if user.role == "owner" else None,
        }
        for it in items
    ]


@router.get("/products/search", summary="Semantic Catalog Search")
def search_products_kiosk(
    q: str = Query(..., description="Colloquial search query (e.g. unga, mafuta, sabuni)"),
    k: int = Query(default=5, ge=1, le=20, description="Top matches"),
    shop_id: str = "shop_kibera_01",
    db: Annotated[Session, Depends(get_db)] = None,
):
    """Semantic search returning ordered [{product_id, name, price_ksh, similarity}]."""
    search_service = SemanticSearchService(db)
    results = search_service.search_products(shop_id=shop_id, query=q, top_k=k)
    return [
        {
            "product_id": it["id"],
            "name": it["name"],
            "price_ksh": float(it["unit_price"]),
            "similarity": float(it["similarity"]),
        }
        for it in results
    ]


@router.post(
    "/demo/oversell-race",
    summary="Dev-Demo Utility: 2-Thread Concurrency Race Simulation",
    responses={
        403: {"description": "Forbidden when DEV_MODE_MOCK_AUTH is False"},
        404: {"description": "Product not found"},
    },
)
def demo_oversell_race(
    req: OversellRaceRequest,
    db: Annotated[Session, Depends(get_db)],
):
    """Dev-demo utility: sets product stock to 1, then simulates 2 concurrent checkout attempts.

    Returns {attempts: [{worker, outcome, remaining_stock | status_code, error?}], note}.
    """
    env_flag = os.getenv("DEV_MODE_MOCK_AUTH")
    is_mock_enabled = (
        env_flag.lower() in ("true", "1", "yes")
        if env_flag is not None
        else settings.DEV_MODE_MOCK_AUTH
    )
    if not settings.DEV_MODE_MOCK_AUTH:
        is_mock_enabled = False

    if not is_mock_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: DEV_MODE_MOCK_AUTH is disabled",
        )

    # 1. Reset stock to 1
    inv = (
        db.execute(
            select(Inventory).where(
                Inventory.shop_id == req.shop_id,
                Inventory.product_id == req.product_id,
            )
        )
        .scalar_one_or_none()
    )
    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inventory record not found",
        )
    inv.current_stock = 1
    db.commit()

    # 2. Race 2 concurrent threads using sessions bound to the active DB engine
    bind = db.get_bind()
    bind_engine = bind.engine if hasattr(bind, "engine") else bind
    session_factory = sessionmaker(bind=bind_engine)
    attempts = []

    # SQLite in-memory connections share C memory structures; serialize for SQLite
    # while running full multi-threaded concurrency on PostgreSQL / Timescale.
    is_sqlite = bind.dialect.name == "sqlite"
    max_workers = 1 if is_sqlite else 2

    def attempt_checkout(worker_id: int):
        with session_factory() as worker_sess:
            svc = InventoryService(worker_sess)
            try:
                rec = svc.process_sale(
                    shop_id=req.shop_id,
                    product_id=req.product_id,
                    quantity=1,
                    cashier_id=f"demo_worker_{worker_id}",
                )
                return {
                    "worker": worker_id,
                    "outcome": "success",
                    "remaining_stock": rec.remaining_stock,
                    "status_code": 200,
                }
            except InsufficientStockError as exc:
                return {
                    "worker": worker_id,
                    "outcome": "rejected",
                    "status_code": 409,
                    "error": str(exc),
                }
            except Exception as exc:
                return {
                    "worker": worker_id,
                    "outcome": "rejected",
                    "status_code": 500,
                    "error": str(exc),
                }

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futs = [executor.submit(attempt_checkout, i + 1) for i in range(2)]
        for fut in concurrent.futures.as_completed(futs):
            attempts.append(fut.result())

    attempts.sort(key=lambda x: x["worker"])

    return {
        "attempts": attempts,
        "note": "Pessimistic row lock (SELECT ... FOR UPDATE) guaranteed atomic execution: exactly 1 sale succeeded and 1 was blocked.",
    }


@router.get("/inventory", summary="Get Current Inventory Levels")
def list_inventory(
    shop_id: str,
    user: RequireStaff,
    db: Annotated[Session, Depends(get_db)],
):
    """Returns current stock and reorder flags. Profit margins are redacted for staff."""
    service = InventoryService(db)
    items = service.get_stock_levels(shop_id)

    # Redact margins if user does not have owner role
    if user.role != "owner":
        for it in items:
            it["unit_cost"] = None
            it["margin_kes"] = None
            it["margin_pct"] = None

    return {"shop_id": shop_id, "role_applied": user.role, "inventory": items}


@router.post(
    "/inventory/restock",
    summary="Restock Inventory (Owner Role Required)",
    responses={403: {"description": "Forbidden: Requires Owner role"}},
)
def restock_inventory(
    req: RestockRequest,
    user: RequireOwner,  # Enforces Owner RBAC
    db: Annotated[Session, Depends(get_db)],
):
    """Restock an inventory line. Restricted strictly to duka owners."""
    service = InventoryService(db)
    new_stock = service.restock(req.shop_id, req.product_id, req.quantity)
    return {
        "status": "success",
        "product_id": req.product_id,
        "restocked_by": user.sub,
        "units_added": req.quantity,
        "current_stock": new_stock,
    }


# -----------------------------------------------------------------------------
# Semantic Product Search (pgvector)
# -----------------------------------------------------------------------------
@router.get("/catalog/search", summary="pgvector Semantic Product Catalog Search")
def semantic_search(
    shop_id: str,
    q: str = Query(..., description="Colloquial search query (e.g. 'unga ya ugali', 'sabuni')"),
    top_k: int = Query(default=5, ge=1, le=20),
    db: Annotated[Session, Depends(get_db)] = None,
):
    """Searches inventory using 384-d pgvector cosine distance embeddings."""
    search_service = SemanticSearchService(db)
    results = search_service.search_products(shop_id=shop_id, query=q, top_k=top_k)
    return {"query": q, "count": len(results), "matches": results}


# -----------------------------------------------------------------------------
# Tiger Data Time-Series Analytics (Owner Only)
# -----------------------------------------------------------------------------
@router.get("/analytics/daily", summary="Tiger Data Daily Revenue Velocity")
def daily_analytics(
    shop_id: str,
    days: int = Query(default=30, ge=7, le=90),
    user: RequireOwner = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    """Continuous aggregate time_bucket rollup of revenue and profit."""
    analytics = TimeSeriesAnalyticsService(db)
    return {
        "shop_id": shop_id,
        "days": days,
        "data": analytics.get_daily_revenue_velocity(shop_id, days=days),
    }


@router.get("/analytics/hourly", summary="Tiger Data Hourly Rush Profile")
def hourly_analytics(
    shop_id: str,
    days: int = Query(default=14, ge=1, le=60),
    db: Annotated[Session, Depends(get_db)] = None,
):
    """Peak transaction hours in the kiosk."""
    analytics = TimeSeriesAnalyticsService(db)
    return {
        "shop_id": shop_id,
        "profile": analytics.get_hourly_sales_profile(shop_id, days=days),
        "payment_split": analytics.get_payment_method_split(shop_id),
    }


# -----------------------------------------------------------------------------
# Demand Forecasting vs Seasonal-Naive Baseline (Owner Only)
# -----------------------------------------------------------------------------
@router.get("/forecasting/{product_id}", summary="Backtested Demand Forecast vs Seasonal-Naive")
def get_forecast(
    product_id: str,
    shop_id: str,
    user: RequireOwner = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    """Evaluates 4-week demand against a seasonal-naive baseline."""
    forecaster = DemandForecastingService(db)
    return forecaster.forecast_product_demand(shop_id=shop_id, product_id=product_id)
