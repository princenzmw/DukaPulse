"""Centralized configuration for DukaPulse using Pydantic Settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Application runtime settings."""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core App
    APP_NAME: str = "DukaPulse"
    ENVIRONMENT: str = Field(default="development")
    DEBUG: bool = Field(default=True)

    # Database & Tiger Data
    DATABASE_URL: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/dukapulse",
        description="PostgreSQL / Tiger Data Timescale connection URL",
    )
    USE_SQLITE_FALLBACK: bool = Field(
        default=False,
        description="When True or when PostgreSQL is unreachable, use SQLite for local demo/testing",
    )
    SQLITE_PATH: str = Field(default=str(ROOT_DIR / "dukapulse_dev.db"))

    # Auth0 Configuration
    AUTH0_DOMAIN: str = Field(
        default="dev-dukapulse.us.auth0.com",
        description="Auth0 Domain for JWT JWKS validation",
    )
    AUTH0_API_AUDIENCE: str = Field(
        default="https://api.dukapulse.africa",
        description="Expected audience for incoming JWT tokens",
    )
    AUTH0_ALGORITHMS: list[str] = Field(default=["RS256", "HS256"])
    DEV_MODE_MOCK_AUTH: bool = Field(
        default=False,
        description="Permit developer bearer tokens for local grading without live Auth0 tenant",
    )
    DEV_JWT_SECRET: str = Field(
        default="dukapulse-mlh-builders-week-secret-key-2026",
        description="Secret key for signing offline dev tokens",
    )

    # Inventory Concurrency & Business Policy
    LOW_STOCK_THRESHOLD: int = 10
    DEFAULT_FORECAST_HORIZON_WEEKS: int = 4
    BENCHMARK_MAPE_TARGET: float = 0.25  # Model must beat 25% or seasonal-naive wins


settings = Settings()
