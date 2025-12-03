"""
Dragonfly Engine - FastAPI Application

Main application entry point. Creates the FastAPI app, wires up routers,
initializes database pool and scheduler on startup.

Run with: uvicorn backend.main:app --reload
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import configure_logging, get_settings
from .db import close_db_pool, init_db_pool
from .routers import (
    analytics_router,
    budget_router,
    enforcement_router,
    foil_router,
    health_router,
    ingest_router,
)
from .routers.ingest_v2 import router as ingest_v2_router
from .scheduler import init_scheduler

# Configure logging before anything else
configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler.

    Handles startup and shutdown events:
    - Startup: Initialize database pool
    - Shutdown: Close database pool

    Note: Scheduler is initialized separately via init_scheduler()
    which uses the older on_event pattern (works with APScheduler).
    """
    settings = get_settings()

    # Startup
    logger.info(f"🚀 Starting Dragonfly Engine v{__version__} ({settings.environment})")

    try:
        await init_db_pool(settings)
        logger.info("✅ Database pool initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize database pool: {e}")
        # Don't raise - allow app to start for health checks

    yield

    # Shutdown
    logger.info("🛑 Shutting down Dragonfly Engine...")
    await close_db_pool()
    logger.info("✅ Shutdown complete")


def create_app() -> FastAPI:
    """
    Application factory.

    Creates and configures the FastAPI application with:
    - Lifespan handler for DB pool
    - CORS middleware
    - Routers
    - Scheduler

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="Dragonfly Engine",
        description=(
            "Backend service for Dragonfly Civil enforcement automation. "
            "Handles scheduled jobs, enforcement workflows, and API endpoints."
        ),
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:5173",
            "https://*.vercel.app",
            "https://dragonfly-dashboard.vercel.app",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    # Health check - no auth required
    app.include_router(health_router, prefix="/api")

    # Core functionality routers (legacy)
    app.include_router(ingest_router, prefix="/api")
    app.include_router(foil_router, prefix="/api")

    # v0.2.x enterprise ingest router
    app.include_router(ingest_v2_router)

    # v0.2.0 routers
    app.include_router(analytics_router, prefix="/api")
    app.include_router(budget_router, prefix="/api")
    app.include_router(enforcement_router, prefix="/api")

    # Initialize scheduler (uses on_event internally)
    init_scheduler(app)

    # Root endpoint
    @app.get("/", tags=["Root"])
    async def root() -> dict[str, str]:
        """Root endpoint - service info."""
        return {
            "service": "Dragonfly Engine",
            "version": __version__,
            "status": "running",
            "docs": "/docs",
        }

    @app.get("/api", tags=["Root"])
    async def api_root() -> dict[str, str]:
        """API root endpoint."""
        return {
            "message": "Dragonfly Engine API",
            "version": __version__,
            "health": "/api/health",
        }

    logger.info(f"FastAPI app created: {app.title} v{app.version}")

    return app


# Create the application instance
app = create_app()


# =============================================================================
# CLI Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()

    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.is_development,
        log_level=settings.log_level.lower(),
    )
