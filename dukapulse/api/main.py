"""FastAPI Application Entrypoint for DukaPulse."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from ..config import settings
from ..db.session import init_db
from .routes import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dukapulse")

STATIC_DIR = Path(__file__).resolve().parent / "static" / "kiosk"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


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

# Mount kiosk frontend static files
app.mount("/kiosk", StaticFiles(directory=str(STATIC_DIR), html=True), name="kiosk")


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/kiosk")


@app.get("/favicon.ico", include_in_schema=False)
def favicon_ico():
    return FileResponse(STATIC_DIR / "favicon.ico")


@app.get("/favicon.svg", include_in_schema=False)
def favicon_svg():
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon():
    return FileResponse(STATIC_DIR / "apple-touch-icon.png")


@app.get("/og-image.png", include_in_schema=False)
def og_image():
    return FileResponse(STATIC_DIR / "og-image.png")


@app.get("/health", tags=["Health"])
def healthcheck():
    """Health check endpoint probing database connectivity.

    WHY MINIMAL PAYLOAD:
    Public health endpoints should reveal minimal architectural internals to prevent
    information leakage. Exposes strictly operational status, active DB probe,
    service identity, and semantic version.
    """
    from sqlalchemy import text

    from ..db.session import engine

    db_status = "disconnected"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1;"))
        db_status = "connected"
    except Exception as exc:
        logger.warning("Database healthcheck probe failed: %s", exc)

    return {
        "status": "ok",
        "database": db_status,
        "service": settings.APP_NAME,
        "version": app.version,
    }
