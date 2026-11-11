"""Tiger Data time-series analytics and continuous aggregate query service."""

from __future__ import annotations

import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..db.models import SalesEvent


class TimeSeriesAnalyticsService:
    """Time-series analytics powered by Tiger Data Timescale hypertables."""

    def __init__(self, db: Session):
        self.db = db

    def get_daily_revenue_velocity(self, shop_id: str, days: int = 30) -> list[dict]:
        """Aggregate daily sales, gross revenue, and net profit over a time window."""
        start_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)

        is_postgres = self.db.bind.dialect.name != "sqlite"
        if is_postgres:
            # Tiger Data time_bucket native syntax
            query = text("""
                SELECT 
                    time_bucket('1 day', sale_time) AS bucket,
                    COALESCE(SUM(total_revenue), 0.0) AS revenue,
                    COALESCE(SUM(profit), 0.0) AS profit,
                    COALESCE(SUM(quantity), 0) AS units_sold,
                    COUNT(*) AS transactions
                FROM sales_events
                WHERE shop_id = :shop_id AND sale_time >= :start_date
                GROUP BY bucket
                ORDER BY bucket ASC;
            """)
            rows = (
                self.db.execute(query, {"shop_id": shop_id, "start_date": start_date})
                .mappings()
                .all()
            )
            return [
                {
                    "date": r["bucket"].strftime("%Y-%m-%d")
                    if hasattr(r["bucket"], "strftime")
                    else str(r["bucket"]),
                    "revenue": float(r["revenue"]),
                    "profit": float(r["profit"]),
                    "units_sold": int(r["units_sold"]),
                    "transactions": int(r["transactions"]),
                }
                for r in rows
            ]

        # SQLite fallback using date()
        query = text("""
            SELECT 
                date(sale_time) AS bucket,
                COALESCE(SUM(total_revenue), 0.0) AS revenue,
                COALESCE(SUM(profit), 0.0) AS profit,
                COALESCE(SUM(quantity), 0) AS units_sold,
                COUNT(*) AS transactions
            FROM sales_events
            WHERE shop_id = :shop_id AND sale_time >= :start_date
            GROUP BY bucket
            ORDER BY bucket ASC;
        """)
        rows = (
            self.db.execute(query, {"shop_id": shop_id, "start_date": start_date.isoformat()})
            .mappings()
            .all()
        )
        return [
            {
                "date": str(r["bucket"]),
                "revenue": float(r["revenue"]),
                "profit": float(r["profit"]),
                "units_sold": int(r["units_sold"]),
                "transactions": int(r["transactions"]),
            }
            for r in rows
        ]

    def get_hourly_sales_profile(self, shop_id: str, days: int = 14) -> list[dict]:
        """Detect peak shopping hours in African dukas (morning & evening rush)."""
        start_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)
        is_postgres = self.db.bind.dialect.name != "sqlite"

        if is_postgres:
            query = text("""
                SELECT 
                    EXTRACT(HOUR FROM sale_time) AS hour_of_day,
                    COUNT(*) AS transaction_count,
                    SUM(total_revenue) AS total_revenue
                FROM sales_events
                WHERE shop_id = :shop_id AND sale_time >= :start_date
                GROUP BY hour_of_day
                ORDER BY hour_of_day ASC;
            """)
            rows = (
                self.db.execute(query, {"shop_id": shop_id, "start_date": start_date})
                .mappings()
                .all()
            )
        else:
            query = text("""
                SELECT 
                    CAST(strftime('%H', sale_time) AS INTEGER) AS hour_of_day,
                    COUNT(*) AS transaction_count,
                    SUM(total_revenue) AS total_revenue
                FROM sales_events
                WHERE shop_id = :shop_id AND sale_time >= :start_date
                GROUP BY hour_of_day
                ORDER BY hour_of_day ASC;
            """)
            rows = (
                self.db.execute(query, {"shop_id": shop_id, "start_date": start_date.isoformat()})
                .mappings()
                .all()
            )

        return [
            {
                "hour": int(r["hour_of_day"]),
                "transactions": int(r["transaction_count"]),
                "revenue": float(r["total_revenue"] or 0.0),
            }
            for r in rows
        ]

    def get_payment_method_split(self, shop_id: str) -> dict[str, float]:
        """M-PESA vs Cash breakdown."""
        stmt = (
            select(
                SalesEvent.payment_method,
                func.sum(SalesEvent.total_revenue).label("total"),
            )
            .where(SalesEvent.shop_id == shop_id)
            .group_by(SalesEvent.payment_method)
        )
        results = self.db.execute(stmt).all()
        return {str(method): float(total or 0.0) for method, total in results}
