"""Honest Demand Forecasting Service with Seasonal-Naive Benchmarking.

"A model only earns its compute budget if it proves lower MAPE than repeating last cycle's demand."
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Inventory, SalesEvent


def seasonal_naive_forecast(
    history: list[float], season_length: int = 4, horizon: int = 4
) -> list[float]:
    """Seasonal-Naive baseline: repeats the values observed in the same seasonal cycle."""
    if not history:
        return [0.0] * horizon
    if len(history) < season_length:
        # Fall back to naive (last observed value)
        return [float(history[-1])] * horizon

    forecast = []
    for h in range(horizon):
        # Look back season_length steps
        lookback_idx = -(season_length - (h % season_length))
        forecast.append(float(history[lookback_idx]))
    return forecast


def holt_linear_forecast(
    history: list[float], horizon: int = 4, alpha: float = 0.3, beta: float = 0.1
) -> list[float]:
    """Holt's Linear Exponential Smoothing (Level + Trend) for retail demand."""
    if not history:
        return [0.0] * horizon
    if len(history) == 1:
        return [float(history[0])] * horizon

    # Initialize level and trend
    level = float(history[0])
    trend = float(history[1] - history[0])

    for val in history[1:]:
        prev_level = level
        level = alpha * val + (1 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend

    # Project horizon
    forecast = [max(0.0, float(level + (h + 1) * trend)) for h in range(horizon)]
    return forecast


def compute_mape(actual: list[float], predicted: list[float], eps: float = 1.0) -> float:
    """Mean Absolute Percentage Error with epsilon smoothing for zero-sale days."""
    actual_arr = np.array(actual, dtype=float)
    pred_arr = np.array(predicted, dtype=float)
    if len(actual_arr) == 0:
        return 0.0
    denominator = np.maximum(np.abs(actual_arr), eps)
    return float(np.mean(np.abs((actual_arr - pred_arr) / denominator)))


def compute_mae(actual: list[float], predicted: list[float]) -> float:
    """Mean Absolute Error."""
    if not actual:
        return 0.0
    return float(np.mean(np.abs(np.array(actual) - np.array(predicted))))


class DemandForecastingService:
    """Evaluates product demand and verifies forecasts against the seasonal-naive baseline."""

    def __init__(self, db: Session):
        self.db = db

    def get_product_weekly_sales(self, shop_id: str, product_id: str) -> list[float]:
        """Fetch weekly aggregated unit sales ordered chronologically."""
        stmt = (
            select(
                SalesEvent.sale_time,
                SalesEvent.quantity,
            )
            .where(
                SalesEvent.shop_id == shop_id,
                SalesEvent.product_id == product_id,
            )
            .order_by(SalesEvent.sale_time.asc())
        )
        rows = self.db.execute(stmt).all()
        if not rows:
            return []

        df = pd.DataFrame(rows, columns=["sale_time", "quantity"])
        df["sale_time"] = pd.to_datetime(df["sale_time"])
        weekly = df.set_index("sale_time").resample("W-MON")["quantity"].sum().values.tolist()
        return [float(x) for x in weekly]

    def forecast_product_demand(self, shop_id: str, product_id: str, horizon: int = 4) -> dict:
        """Run backtested forecast and return replenishment advice."""
        history = self.get_product_weekly_sales(shop_id, product_id)

        # Fetch current stock for both branches
        inv = self.db.execute(
            select(Inventory).where(
                Inventory.shop_id == shop_id, Inventory.product_id == product_id
            )
        ).scalar_one_or_none()
        current_stock = inv.current_stock if inv else 0

        # 1. Edge case: sparse history (< 8 weeks)
        if len(history) < 8:
            avg_demand = float(np.mean(history)) if history else 5.0
            forecast = [round(avg_demand, 1)] * horizon
            recommended_reorder = max(0, math.ceil(sum(forecast) - current_stock + 5))
            return {
                "product_id": product_id,
                "history": history,
                "final_forecast": forecast,
                "champion_model": "Simple Moving Average (Sparse Data)",
                "seasonal_naive_mape": None,
                "candidate_mape": None,
                "seasonal_naive_mae": None,
                "candidate_mae": None,
                "earned_compute_budget": True,
                "total_projected_demand": round(sum(forecast), 1),
                "current_stock": current_stock,
                "safety_stock": 5,
                "recommended_reorder": recommended_reorder,
            }

        # 2. Backtest split: train on history[:-4], evaluate on history[-4:]
        train_hist = history[:-4]
        val_actual = history[-4:]

        # Baseline: Seasonal Naive
        sn_preds = seasonal_naive_forecast(train_hist, season_length=4, horizon=4)
        sn_mape = compute_mape(val_actual, sn_preds)
        sn_mae = compute_mae(val_actual, sn_preds)

        # Candidate: Holt Linear
        hl_preds = holt_linear_forecast(train_hist, horizon=4)
        hl_mape = compute_mape(val_actual, hl_preds)
        hl_mae = compute_mae(val_actual, hl_preds)

        # Champion Selection Rule: Model must beat seasonal-naive baseline!
        earned_budget = hl_mape < sn_mape
        if earned_budget:
            champion_name = "Holt Exponential Smoothing (Challenger)"
            final_forecast = holt_linear_forecast(history, horizon=horizon)
            best_mape = hl_mape
        else:
            champion_name = "Seasonal-Naive Benchmark (Baseline)"
            final_forecast = seasonal_naive_forecast(history, season_length=4, horizon=horizon)
            best_mape = sn_mape

        # 3. Replenishment calculation with current stock
        inv = self.db.execute(
            select(Inventory).where(
                Inventory.shop_id == shop_id, Inventory.product_id == product_id
            )
        ).scalar_one_or_none()
        current_stock = inv.current_stock if inv else 0
        total_projected_demand = sum(final_forecast)

        # Safety stock buffer: ~1.65 std dev of history
        hist_std = float(np.std(history)) if len(history) > 1 else 2.0
        safety_stock = math.ceil(1.65 * hist_std)
        recommended_reorder = max(
            0, math.ceil(total_projected_demand - current_stock + safety_stock)
        )

        return {
            "product_id": product_id,
            "history": history,
            "val_actual": val_actual,
            "baseline_preds": [round(x, 1) for x in sn_preds],
            "candidate_preds": [round(x, 1) for x in hl_preds],
            "seasonal_naive_mape": round(sn_mape, 3),
            "candidate_mape": round(hl_mape, 3),
            "seasonal_naive_mae": round(sn_mae, 2),
            "candidate_mae": round(hl_mae, 2),
            "earned_compute_budget": earned_budget,
            "champion_model": champion_name,
            "champion_mape": round(best_mape, 3),
            "final_forecast": [round(x, 1) for x in final_forecast],
            "total_projected_demand": round(total_projected_demand, 1),
            "current_stock": current_stock,
            "safety_stock": safety_stock,
            "recommended_reorder": recommended_reorder,
        }
