"""FastAPI Application Entrypoint for DukaPulse."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import settings
from ..db.session import init_db
from .routes import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dukapulse")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: initialize database schemas and extensions."""
    logger.info("Initializing DukaPulse schemas and Tiger Data hypertables...")
    init_db()
    yield
    logger.info("DukaPulse shutdown complete.")


app = FastAPI(
    title="DukaPulse API",
    description=(
        "Micro-Retail Inventory Intelligence & Concurrency Guard. "
        "Powered by Tiger Data Hypertables, pgvector embeddings, and Auth0 RBAC."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration for Streamlit and external frontend clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health", tags=["Health"])
def healthcheck():
    return {
        "status": "online",
        "service": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "auth0_domain": settings.AUTH0_DOMAIN,
        "mock_auth_allowed": settings.DEV_MODE_MOCK_AUTH,
    }
