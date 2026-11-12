"""Pytest fixtures for DukaPulse."""

from __future__ import annotations

import os

# Set DEV_MODE_MOCK_AUTH=true for unit tests to exercise dev-token path
os.environ["DEV_MODE_MOCK_AUTH"] = "true"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dukapulse.api.main import app
from dukapulse.auth.jwt import create_dev_token
from dukapulse.db.models import Base
from dukapulse.db.session import get_db
from dukapulse.seed import seed_database


@pytest.fixture(scope="session")
def test_db_engine():
    """In-memory SQLite database with single static pool for multi-thread test isolation."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture(scope="function")
def db_session(test_db_engine):
    """Yield a database session per test with automatic rollback."""
    connection = test_db_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    # Seed catalog
    seed_database(session, num_days=14)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def client(db_session):
    """FastAPI test client with database dependency override."""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def owner_token() -> str:
    return create_dev_token(sub="auth0|prince_owner", role="owner", shop_id="shop_kibera_01")


@pytest.fixture
def staff_token() -> str:
    return create_dev_token(sub="auth0|clerk_kibera_01", role="staff", shop_id="shop_kibera_01")
