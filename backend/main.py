"""
Dragonfly Engine - FastAPI Application

Main application entry point. Creates the FastAPI app, wires up routers,
initializes database pool and scheduler on startup.

Run with: uvicorn backend.main:app --reload

Note: On Windows, psycopg async requires SelectorEventLoop. If you see
"ProactorEventLoop" errors, run via WSL or deploy to Linux container.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import configure_logging, get_settings
from .core.errors import setup_error_handlers
from .core.middleware import (
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    ResponseSanitizationMiddleware,
)
from .db import close_db_pool, init_db_pool
from .routers import (
    analytics_router,
    budget_router,
    enforcement_router,
    foil_router,
    health_router,
    ingest_router,
    intake_router,
    search_router,
)
from .routers.events import router as events_router
from .routers.ingest_v2 import router as ingest_v2_router
from .routers.intelligence import router as intelligence_router
from .routers.offers import router as offers_router
from .routers.ops_guardian import router as ops_guardian_router
from .routers.packets import router as packets_router
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
    - Request logging middleware
    - Rate limiting middleware
    - CORS middleware
    - Structured error handlers
    - Routers
    - Scheduler

    Returns:
        Configured FastAPI application
    """
    settings = get_settings()

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

    # ==========================================================================
    # Middleware (order matters: first added = outermost = runs first)
    # ==========================================================================

    # 1. Request logging (outermost - logs all requests)
    app.add_middleware(RequestLoggingMiddleware)

    # 2. Rate limiting for sensitive endpoints
    if settings.is_production:
        app.add_middleware(RateLimitMiddleware)
        logger.info("Rate limiting enabled for production")

    # 3. Response sanitization (safety net for credential leaks)
    app.add_middleware(
        ResponseSanitizationMiddleware, strict_mode=settings.is_production
    )

    # 4. CORS (must be near the bottom to handle preflight correctly)
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

    # ==========================================================================
    # Error Handlers
    # ==========================================================================
    setup_error_handlers(app)

    # ==========================================================================
    # Routers
    # ==========================================================================

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

    # v0.2.x search router (semantic search)
    app.include_router(search_router, prefix="/api/v1", tags=["search"])

    # v0.2.x intelligence router (judgment graph)
    app.include_router(intelligence_router, prefix="/api", tags=["intelligence"])

    # v0.2.x offers router (transaction engine)
    app.include_router(offers_router, prefix="/api", tags=["offers"])

    # v0.2.x packets router (document assembly engine)
    app.include_router(packets_router, prefix="/api", tags=["packets"])

    # v0.2.x events router (event stream / timeline)
    app.include_router(events_router, prefix="/api", tags=["events"])

    # v0.3.x intake fortress router (hardened intake system)
    app.include_router(intake_router, prefix="/api/v1", tags=["intake"])

    # v0.3.x ops guardian router (self-healing intake monitor)
    app.include_router(ops_guardian_router, prefix="/api/v1", tags=["ops"])

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

    # Root-level health check for Railway/load balancers
    @app.get("/health", tags=["Health"])
    async def health() -> dict[str, str]:
        """Simple health check at root level for Railway."""
        return {
            "service": "Dragonfly Engine",
            "status": "ok",
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
