"""Centralized configuration for DukaPulse using Pydantic Settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
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
        default="postgresql+psycopg://postgres:postgres@localhost:5432/dukapulse",
        description="PostgreSQL / Tiger Data Timescale connection URL",
    )

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str | None) -> str:
        """Normalize PostgreSQL connection schemes to postgresql+psycopg://.

        WHY: Tiger Data's Timescale Cloud console yields raw 'postgres://...' or
        'postgresql://...' URIs, and Streamlit Cloud / Hugging Face Secrets frequently
        paste these connection strings unedited. SQLAlchemy 2.0 with modern psycopg 3
        requires the explicit 'postgresql+psycopg://' dialect scheme to prevent
        legacy driver fallback or dialect rejection.
        """
        if not v:
            return "postgresql+psycopg://postgres:postgres@localhost:5432/dukapulse"
        url = v.strip()
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url[len("postgres://") :]
        if url.startswith("postgresql://") and not url.startswith("postgresql+"):
            return "postgresql+psycopg://" + url[len("postgresql://") :]
        return url
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
