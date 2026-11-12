"""Automated forecasting benchmark CLI comparing Holt exponential smoothing vs Seasonal-Naive.

Loads 60 days of retail transaction history and writes MAPE comparison receipts.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from .db.models import Product, Shop
from .db.session import SessionLocal, init_db
from .seed import seed_database
from .services.forecasting import DemandForecastingService


def run_benchmark() -> list[dict]:
    """Run forecasting tournament across all products for the active shop."""
    init_db()
    with SessionLocal() as db:
        seed_database(db, num_days=60)
        shop = db.query(Shop).first()
        shop_id = shop.id if shop else "shop_kibera_01"

        products = db.query(Product).filter(Product.shop_id == shop_id).all()
        forecaster = DemandForecastingService(db)

        receipts: list[dict] = []
        now_iso = datetime.datetime.now(datetime.UTC).isoformat()

        for prod in products:
            res = forecaster.forecast_product_demand(shop_id=shop_id, product_id=prod.id)
            receipts.append(
                {
                    "product": prod.name,
                    "mape_seasonal_naive": res["seasonal_naive_mape"],
                    "mape_holt": res["candidate_mape"],
                    "winner": res["champion_model"],
                    "generated_at": now_iso,
                }
            )

        output_dir = Path(__file__).resolve().parents[1] / "docs" / "receipts"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "forecast_mape.json"

        output_file.write_text(json.dumps(receipts, indent=2), encoding="utf-8")
        return receipts


if __name__ == "__main__":
    results = run_benchmark()
    print(json.dumps(results, indent=2))
