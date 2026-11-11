"""SQLAlchemy declarative models for DukaPulse."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

try:
    from pgvector.sqlalchemy import Vector

    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False


class Base(DeclarativeBase):
    pass


class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    location: Mapped[str] = mapped_column(String(120), default="Nairobi, Kenya")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.UTC)
    )

    products: Mapped[list[Product]] = relationship(
        "Product", back_populates="shop", cascade="all, delete-orphan"
    )
    inventory_items: Mapped[list[Inventory]] = relationship(
        "Inventory", back_populates="shop", cascade="all, delete-orphan"
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    shop_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # pgvector embedding: 384 dimensions for all-MiniLM-L6-v2 or local hash vectors
    if HAS_PGVECTOR:
        embedding = mapped_column(Vector(384), nullable=True)
    else:
        embedding = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.UTC)
    )

    shop: Mapped[Shop] = relationship("Shop", back_populates="products")
    inventory: Mapped[Inventory | None] = relationship(
        "Inventory", back_populates="product", uselist=False
    )


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("shop_id", "product_id", name="uq_shop_product_inventory"),
        CheckConstraint("current_stock >= 0", name="chk_stock_non_negative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    shop_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    current_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reorder_point: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    reorder_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    last_restocked_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.UTC)
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.UTC),
        onupdate=lambda: datetime.datetime.now(datetime.UTC),
    )

    shop: Mapped[Shop] = relationship("Shop", back_populates="inventory_items")
    product: Mapped[Product] = relationship("Product", back_populates="inventory")


class SalesEvent(Base):
    """Event table converted into a Tiger Data Hypertable partitioned on sale_time."""

    __tablename__ = "sales_events"

    # In Timescale/Tiger Data hypertables, primary keys must include the partitioning column
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sale_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        default=lambda: datetime.datetime.now(datetime.UTC),
        index=True,
    )
    shop_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(150), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    total_revenue: Mapped[float] = mapped_column(Float, nullable=False)
    profit: Mapped[float] = mapped_column(Float, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(30), default="M-PESA")  # M-PESA or CASH
    cashier_id: Mapped[str] = mapped_column(String(120), default="staff_kiosk")
