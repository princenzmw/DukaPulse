"""Database engine, session management, and Tiger Data initialization."""

from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from .models import Base

logger = logging.getLogger(__name__)

# Determine connection URL
is_sqlite = False
engine_url = settings.DATABASE_URL

if settings.USE_SQLITE_FALLBACK:
    is_sqlite = True
    engine_url = f"sqlite:///{settings.SQLITE_PATH}"
else:
    # Try connecting to postgres, fall back to sqlite if unreachable
    try:
        test_engine = create_engine(engine_url, connect_args={"connect_timeout": 2})
        with test_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Successfully connected to PostgreSQL / Tiger Data.")
    except Exception as exc:
        logger.warning(
            "PostgreSQL / Tiger Data is not reachable at %s (%s). Falling back to SQLite for local mode.",
            engine_url,
            exc,
        )
        is_sqlite = True
        engine_url = f"sqlite:///{settings.SQLITE_PATH}"

connect_args = {"check_same_thread": False} if is_sqlite else {}
engine = create_engine(engine_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create tables and apply Tiger Data extensions if on PostgreSQL."""
    Base.metadata.create_all(bind=engine)
    if not is_sqlite:
        with engine.begin() as conn:
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector CASCADE;"))
                conn.execute(
                    text(
                        "SELECT create_hypertable('sales_events', 'sale_time', if_not_exists => TRUE);"
                    )
                )
                logger.info("Tiger Data hypertable 'sales_events' initialized.")
            except Exception as e:
                logger.warning("Tiger Data hypertable setup note: %s", e)


def get_db() -> Generator[Session, None, None]:
    """Dependency for obtaining a database session with automatic cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
