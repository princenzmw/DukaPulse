"""Real-engine integration tests against PostgreSQL with TimescaleDB and pgvector."""

from __future__ import annotations

import concurrent.futures
import datetime
import os
import pathlib

import pytest
import sqlalchemy
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from dukapulse.config import settings
from dukapulse.db.models import Inventory, Product
from dukapulse.seed import seed_database
from dukapulse.services.inventory import InsufficientStockError, InventoryService
from dukapulse.services.timeseries import TimeSeriesAnalyticsService

pytestmark = pytest.mark.integration

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/dukapulse_test",
)


@pytest.fixture(scope="module")
def pg_engine():
    """Engine connected to the real PostgreSQL/TimescaleDB service."""
    if not DATABASE_URL.startswith("postgres"):
        pytest.skip("Integration tests require PostgreSQL DATABASE_URL")

    # Synchronize application settings with DATABASE_URL
    settings.DATABASE_URL = DATABASE_URL
    settings.USE_SQLITE_FALLBACK = False

    engine = sqlalchemy.create_engine(DATABASE_URL, pool_size=20, max_overflow=20)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1;"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL service not reachable at {DATABASE_URL}: {exc}")

    return engine


@pytest.fixture(scope="module")
def SessionLocal(pg_engine):
    """Session factory bound to PostgreSQL engine."""
    return sessionmaker(bind=pg_engine)


def test_probe_extensions(pg_engine):
    """PROBE: connect via DATABASE_URL; CREATE EXTENSION IF NOT EXISTS timescaledb;

    CREATE EXTENSION IF NOT EXISTS vector; assert both in pg_extension.
    """
    with pg_engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector CASCADE;"))

        rows = conn.execute(text("SELECT extname, extversion FROM pg_extension;")).all()
        ext_map = {row[0]: row[1] for row in rows}
        print(f"\n[PROBE FINDINGS VERBATIM] Installed extensions in pg_extension: {ext_map}")

        assert "timescaledb" in ext_map, f"timescaledb missing from pg_extension: {ext_map}"
        assert "vector" in ext_map, f"vector (pgvector) missing from pg_extension: {ext_map}"


def test_schema_hypertables_and_continuous_aggregates(pg_engine):
    """SCHEMA: execute dukapulse/db/schema.sql DDL; assert hypertable sales_events exists

    (timescaledb_information.hypertables) with 7-day chunk interval; assert continuous
    aggregates hourly_sales_summary and daily_duka_analytics exist.
    """
    schema_path = pathlib.Path(__file__).resolve().parents[1] / "dukapulse" / "db" / "schema.sql"
    sql_ddl = schema_path.read_text(encoding="utf-8")

    with pg_engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")
        for raw_stmt in sql_ddl.split(";"):
            stmt = raw_stmt.strip()
            if stmt:
                conn.execute(text(stmt))

        # 1. Assert sales_events is a registered hypertable
        hypertables = (
            conn.execute(text("SELECT hypertable_name FROM timescaledb_information.hypertables;"))
            .scalars()
            .all()
        )
        assert "sales_events" in hypertables, f"sales_events not found in hypertables: {hypertables}"

        # 2. Assert 7-day chunk interval on sales_events
        dimensions = (
            conn.execute(
                text(
                    "SELECT hypertable_name, column_name, time_interval "
                    "FROM timescaledb_information.dimensions "
                    "WHERE hypertable_name = 'sales_events';"
                )
            )
            .mappings()
            .all()
        )
        assert len(dimensions) > 0, "No dimensions found for sales_events hypertable"
        dim = dimensions[0]
        interval_val = dim["time_interval"]
        assert (
            interval_val == datetime.timedelta(days=7)
            or "7 days" in str(interval_val)
            or str(interval_val) == "7 days, 0:00:00"
        ), f"Expected 7-day chunk interval, got {interval_val}"

        # 3. Assert continuous aggregates hourly_sales_summary and daily_duka_analytics exist
        caggs = (
            conn.execute(
                text("SELECT view_name FROM timescaledb_information.continuous_aggregates;")
            )
            .scalars()
            .all()
        )
        assert (
            "hourly_sales_summary" in caggs
        ), f"hourly_sales_summary not found in continuous aggregates: {caggs}"
        assert (
            "daily_duka_analytics" in caggs
        ), f"daily_duka_analytics not found in continuous aggregates: {caggs}"


def test_analytics_time_bucket_rollup(SessionLocal):
    """ANALYTICS: run seed logic against PG via the app's settings/config mechanism

    (small volume acceptable), execute the time_bucket rollup query from timeseries.py,
    assert ordered, non-empty buckets.
    """
    shop_id = "shop_kibera_01"
    with SessionLocal() as session:
        seed_database(session, num_days=14)
        service = TimeSeriesAnalyticsService(session)
        buckets = service.get_daily_revenue_velocity(shop_id, days=14)

        assert len(buckets) > 0, "Daily revenue velocity buckets must not be empty"

        dates = [b["date"] for b in buckets]
        assert dates == sorted(dates), f"Buckets are not ordered chronologically: {dates}"

        # Assert data fields
        first_bucket = buckets[0]
        assert "date" in first_bucket
        assert "revenue" in first_bucket
        assert "profit" in first_bucket
        assert "units_sold" in first_bucket
        assert "transactions" in first_bucket


def test_oversell_concurrency_on_real_pg(SessionLocal):
    """OVERSELL ON REAL PG: 16 threads racing 10,000 attempts for 1 unit through the

    inventory service; assert exactly 1 success, 9,999 InsufficientStockError, stock never negative.
    """
    shop_id = "shop_kibera_01"
    with SessionLocal() as init_sess:
        prod = init_sess.query(Product).filter(Product.shop_id == shop_id).first()
        assert prod is not None, "Product must exist after seeding"
        prod_id = prod.id

        inv = init_sess.query(Inventory).filter(Inventory.product_id == prod_id).first()
        inv.current_stock = 1
        init_sess.commit()

    total_attempts = 10000
    max_workers = 16
    success_count = 0
    insufficient_stock_count = 0
    other_errors = []

    def attempt_purchase(clerk_id: int):
        with SessionLocal() as worker_sess:
            svc = InventoryService(worker_sess)
            try:
                svc.process_sale(
                    shop_id=shop_id,
                    product_id=prod_id,
                    quantity=1,
                    cashier_id=f"clerk_pg_{clerk_id}",
                )
                return "success"
            except InsufficientStockError:
                return "insufficient"
            except Exception as exc:
                return f"error: {exc}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(attempt_purchase, i) for i in range(total_attempts)]
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            if res == "success":
                success_count += 1
            elif res == "insufficient":
                insufficient_stock_count += 1
            else:
                other_errors.append(res)

    print(
        f"\n[OVERSELL RECEIPT] Total Attempts: {total_attempts}, "
        f"Success: {success_count}, InsufficientStock: {insufficient_stock_count}, "
        f"Other: {len(other_errors)}"
    )

    # Assert exactly 1 success and 9,999 InsufficientStockError
    assert success_count == 1, f"Expected exactly 1 success, got {success_count}"
    assert insufficient_stock_count == total_attempts - 1, (
        f"Expected exactly {total_attempts - 1} InsufficientStockError, "
        f"got {insufficient_stock_count}. Other errors: {other_errors}"
    )
    assert len(other_errors) == 0, f"Unexpected errors during concurrency race: {other_errors}"

    # Verify stock remained at exactly 0 and never dropped below 0
    with SessionLocal() as verify_sess:
        inv = verify_sess.query(Inventory).filter(Inventory.product_id == prod_id).first()
        assert inv.current_stock == 0, f"Expected final stock 0, got {inv.current_stock}"
        assert inv.current_stock >= 0, "Stock constraint violated: negative stock detected"
