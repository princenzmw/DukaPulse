"""Demand forecasting and seasonal-naive benchmark tests."""

from __future__ import annotations

from dukapulse.db.models import Product
from dukapulse.services.forecasting import (
    DemandForecastingService,
    compute_mae,
    compute_mape,
    holt_linear_forecast,
    seasonal_naive_forecast,
)


def test_seasonal_naive_repeats_cycle():
    """Verify seasonal-naive baseline repeats the last season cycle."""
    history = [10.0, 15.0, 20.0, 25.0]
    preds = seasonal_naive_forecast(history, season_length=4, horizon=4)
    assert preds == [10.0, 15.0, 20.0, 25.0]


def test_holt_linear_trend_projection():
    """Verify Holt Linear captures upward trend."""
    history = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
    preds = holt_linear_forecast(history, horizon=3)
    assert preds[0] > 20.0
    assert preds[1] > preds[0]
    assert preds[2] > preds[1]


def test_mape_and_mae_calculations():
    actual = [100.0, 50.0]
    pred = [110.0, 45.0]
    mae = compute_mae(actual, pred)
    mape = compute_mape(actual, pred)
    assert mae == 7.5  # (10 + 5) / 2
    assert round(mape, 2) == 0.10  # (0.10 + 0.10) / 2


def test_forecasting_service_tournament(db_session):
    """Verify tournament execution for a seeded product."""
    service = DemandForecastingService(db_session)
    shop_id = "shop_kibera_01"
    prod = db_session.query(Product).filter(Product.shop_id == shop_id).first()

    res = service.forecast_product_demand(shop_id, prod.id, horizon=4)
    assert "champion_model" in res
    assert "final_forecast" in res
    assert len(res["final_forecast"]) == 4
    assert res["recommended_reorder"] >= 0
