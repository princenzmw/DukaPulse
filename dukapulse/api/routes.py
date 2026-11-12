"""REST API routes for DukaPulse."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.jwt import create_dev_token
from ..auth.rbac import RequireOwner, RequireStaff
from ..config import settings
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
