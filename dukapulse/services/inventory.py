"""Oversell-Proof Inventory Service using Pessimistic Row Locking."""

from __future__ import annotations

import datetime
import uuid
from typing import NamedTuple

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db.models import Inventory, Product, SalesEvent


class InsufficientStockError(Exception):
    """Raised when an atomic sale exceeds currently available shelf inventory."""

    def __init__(self, product_name: str, requested: int, available: int):
        super().__init__(
            f"Oversell blocked for '{product_name}': requested {requested} units, "
            f"but only {available} units available in stock."
        )
        self.product_name = product_name
        self.requested = requested
        self.available = available


class SaleReceipt(NamedTuple):
    event_id: str
    product_id: str
    product_name: str
    quantity: int
    unit_price: float
    total_revenue: float
    profit: float
    remaining_stock: int
    sale_time: datetime.datetime
    payment_method: str


class InventoryService:
    """Core inventory orchestration with ACID-guaranteed concurrency control."""

    def __init__(self, db: Session):
        self.db = db

    def process_sale(
        self,
        shop_id: str,
        product_id: str,
        quantity: int,
        payment_method: str = "M-PESA",
        cashier_id: str = "staff_kiosk",
        sale_time: datetime.datetime | None = None,
    ) -> SaleReceipt:
        """Atomically decrement inventory with pessimistic locking & conditional update guard.

        Guarantees that two concurrent clerks cannot sell the last unit simultaneously.
        """
        if quantity <= 0:
            raise ValueError(f"Quantity must be strictly positive, got {quantity}")

        if sale_time is None:
            sale_time = datetime.datetime.now(datetime.UTC)

        # 1. Acquire product details for pricing and receipts
        product = self.db.execute(
            select(Product).where(Product.id == product_id)
        ).scalar_one_or_none()
        if not product:
            raise ValueError(f"Product '{product_id}' not found")

        # 2. Atomic conditional decrement with RETURNING
        # Enforces atomic row locking on PostgreSQL and atomic conditional update on SQLite
        stmt = (
            update(Inventory)
            .where(
                Inventory.shop_id == shop_id,
                Inventory.product_id == product_id,
                Inventory.current_stock >= quantity,
            )
            .values(
                current_stock=Inventory.current_stock - quantity,
                updated_at=sale_time,
            )
            .returning(Inventory.current_stock)
        )
        res = self.db.execute(stmt).scalar_one_or_none()
        if res is None:
            inv = self.db.execute(
                select(Inventory).where(
                    Inventory.shop_id == shop_id, Inventory.product_id == product_id
                )
            ).scalar_one_or_none()
            avail = inv.current_stock if inv else 0
            raise InsufficientStockError(
                product_name=product.name,
                requested=quantity,
                available=avail,
            )

        remaining_stock = int(res)

        # 3. Calculate financials
        revenue = round(float(product.unit_price) * quantity, 2)
        total_cost = round(float(product.unit_cost) * quantity, 2)
        profit = round(revenue - total_cost, 2)

        # 4. Record immutable time-series sales event (for Tiger Data Hypertable)
        event_id = str(uuid.uuid4())
        event = SalesEvent(
            id=event_id,
            sale_time=sale_time,
            shop_id=shop_id,
            product_id=product_id,
            product_name=product.name,
            quantity=quantity,
            unit_cost=product.unit_cost,
            unit_price=product.unit_price,
            total_revenue=revenue,
            profit=profit,
            payment_method=payment_method,
            cashier_id=cashier_id,
        )
        self.db.add(event)
        self.db.commit()

        return SaleReceipt(
            event_id=event_id,
            product_id=product_id,
            product_name=product.name,
            quantity=quantity,
            unit_price=product.unit_price,
            total_revenue=revenue,
            profit=profit,
            remaining_stock=remaining_stock,
            sale_time=sale_time,
            payment_method=payment_method,
        )

    def restock(self, shop_id: str, product_id: str, quantity: int) -> int:
        """Restock an item (Owner privilege), updating last_restocked_at."""
        if quantity <= 0:
            raise ValueError("Restock quantity must be positive")

        stmt = (
            select(Inventory)
            .where(Inventory.shop_id == shop_id, Inventory.product_id == product_id)
            .with_for_update()
        )
        inv = self.db.execute(stmt).scalar_one_or_none()
        if not inv:
            inv = Inventory(
                shop_id=shop_id,
                product_id=product_id,
                current_stock=quantity,
                last_restocked_at=datetime.datetime.now(datetime.UTC),
            )
            self.db.add(inv)
        else:
            inv.current_stock += quantity
            inv.last_restocked_at = datetime.datetime.now(datetime.UTC)

        self.db.commit()
        self.db.refresh(inv)
        return inv.current_stock

    def get_stock_levels(self, shop_id: str) -> list[dict]:
        """Fetch current stock, reorder flags, and unit margins for all products."""
        stmt = (
            select(Product, Inventory)
            .join(Inventory, Product.id == Inventory.product_id)
            .where(Product.shop_id == shop_id)
            .order_by(Product.category, Product.name)
        )
        results = self.db.execute(stmt).all()
        stock_list = []
        for prod, inv in results:
            margin = round(prod.unit_price - prod.unit_cost, 2)
            margin_pct = round((margin / prod.unit_price) * 100, 1) if prod.unit_price else 0.0
            stock_list.append(
                {
                    "product_id": prod.id,
                    "name": prod.name,
                    "category": prod.category,
                    "barcode": prod.barcode,
                    "current_stock": inv.current_stock,
                    "reorder_point": inv.reorder_point,
                    "reorder_quantity": inv.reorder_quantity,
                    "unit_cost": prod.unit_cost,
                    "unit_price": prod.unit_price,
                    "margin_kes": margin,
                    "margin_pct": margin_pct,
                    "needs_reorder": inv.current_stock <= inv.reorder_point,
                    "last_restocked_at": inv.last_restocked_at,
                }
            )
        return stock_list
