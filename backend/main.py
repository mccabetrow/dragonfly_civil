"""
Dragonfly Engine - FastAPI Application

Main application entry point. Creates the FastAPI app, wires up routers,
initializes database pool and scheduler on startup.

Run with: uvicorn backend.main:app --reload
"""

# Must be first - fixes Windows asyncio compatibility with psycopg3
from .asyncio_compat import ensure_selector_policy_on_windows

ensure_selector_policy_on_windows()

import logging  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from typing import AsyncGenerator  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from . import __version__  # noqa: E402
from .config import configure_logging, get_settings  # noqa: E402
from .core.errors import setup_error_handlers  # noqa: E402
from .core.middleware import (  # noqa: E402
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    ResponseSanitizationMiddleware,
)
from .db import close_db_pool, init_db_pool  # noqa: E402
from .routers import (  # noqa: E402
    analytics_router,
    budget_router,
    enforcement_router,
    foil_router,
    health_router,
    ingest_router,
    intake_router,
    search_router,
)
from .routers.events import router as events_router  # noqa: E402
from .routers.ingest_v2 import router as ingest_v2_router  # noqa: E402
from .routers.intelligence import router as intelligence_router  # noqa: E402
from .routers.offers import router as offers_router  # noqa: E402
from .routers.ops_guardian import router as ops_guardian_router  # noqa: E402
from .routers.packets import router as packets_router  # noqa: E402
from .scheduler import init_scheduler  # noqa: E402

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
    #    Origins are ENV-driven via DRAGONFLY_CORS_ORIGINS for Railway/Vercel.
    #    See backend/config.py for docs on setting this variable.
    #
    # IMPORTANT: allow_credentials=True is required for the Vercel frontend
    # to include cookies/auth headers in cross-origin requests.
    #
    # For Vercel preview deployments (e.g., dragonfly-console1-abc123.vercel.app),
    # we use allow_origin_regex to match the pattern dynamically.
    cors_regex = settings.cors_origin_regex
    logger.info(
        f"[CORS] Startup origins: {settings.cors_allowed_origins} "
        f"(from DRAGONFLY_CORS_ORIGINS={settings.dragonfly_cors_origins!r})"
    )
    if cors_regex:
        logger.info(f"[CORS] Origin regex enabled: {cors_regex}")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_origin_regex=cors_regex,  # Matches Vercel preview deployments
        allow_credentials=True,  # Required for Vercel console cross-origin requests
        allow_methods=["*"],
        allow_headers=[
            "*"
        ],  # Accept all headers including X-DRAGONFLY-API-KEY, X-API-Key
        expose_headers=["Content-Disposition"],
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
