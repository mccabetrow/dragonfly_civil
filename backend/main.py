"""
Dragonfly Engine - FastAPI Application

Main application entry point. Creates the FastAPI app, wires up routers,
initializes database pool and scheduler on startup.

Run with: uvicorn backend.main:app --reload

PRODUCTION HARDENING NOTES:
- CORS middleware is FIRST (outermost) to handle preflight correctly
- Global exception handlers include CORS headers for frontend error visibility
- All routers explicitly wired with versioned prefixes
"""

# Must be first - fixes Windows asyncio compatibility with psycopg3
from .asyncio_compat import ensure_selector_policy_on_windows

ensure_selector_policy_on_windows()

import logging  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from typing import Any, AsyncGenerator  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from . import __version__  # noqa: E402
from .config import configure_logging, get_settings  # noqa: E402
from .core.middleware import (  # noqa: E402
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    ResponseSanitizationMiddleware,
)
from .db import close_db_pool, init_db_pool  # noqa: E402

# Router imports - explicit for clarity
from .routers.analytics import router as analytics_router  # noqa: E402
from .routers.budget import router as budget_router  # noqa: E402
from .routers.enforcement import router as enforcement_router  # noqa: E402
from .routers.events import router as events_router  # noqa: E402
from .routers.foil import router as foil_router  # noqa: E402
from .routers.health import router as health_router  # noqa: E402
from .routers.ingest import router as ingest_router  # noqa: E402
from .routers.ingest_v2 import router as ingest_v2_router  # noqa: E402
from .routers.intake import router as intake_router  # noqa: E402
from .routers.intelligence import router as intelligence_router  # noqa: E402
from .routers.offers import router as offers_router  # noqa: E402
from .routers.ops_guardian import router as ops_guardian_router  # noqa: E402
from .routers.packets import router as packets_router  # noqa: E402
from .routers.portfolio import router as portfolio_router  # noqa: E402
from .routers.search import router as search_router  # noqa: E402
from .routers.webhooks import router as webhooks_router  # noqa: E402
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


def _get_cors_headers(settings: Any) -> dict[str, str]:
    """Build CORS headers for error responses."""
    # Use first origin or wildcard for error responses
    origins = settings.cors_allowed_origins
    origin = origins[0] if origins else "*"
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
    }


def create_app() -> FastAPI:
    """
    Application factory.

    Creates and configures the FastAPI application with:
    - CORS middleware FIRST (critical for preflight handling)
    - Request logging middleware
    - Rate limiting middleware
    - Response sanitization middleware
    - Global exception handlers with CORS headers
    - All routers wired with explicit prefixes

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
    # MIDDLEWARE ORDER IS CRITICAL
    # First added = outermost = runs first on request, last on response
    # CORS MUST be outermost to handle OPTIONS preflight before anything else
    # ==========================================================================

    # 1. CORS (MUST BE FIRST - handles preflight OPTIONS before other middleware)
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
        allow_credentials=True,  # Required for cross-origin auth
        allow_methods=["*"],
        allow_headers=["*"],  # Accept all headers including X-API-Key
        expose_headers=["Content-Disposition"],
    )

    # 2. Response sanitization (safety net for credential leaks)
    app.add_middleware(
        ResponseSanitizationMiddleware, strict_mode=settings.is_production
    )

    # 3. Rate limiting for sensitive endpoints (production only)
    if settings.is_production:
        app.add_middleware(RateLimitMiddleware)
        logger.info("Rate limiting enabled for production")

    # 4. Request logging (innermost - logs after CORS/rate limit decisions)
    app.add_middleware(RequestLoggingMiddleware)

    # ==========================================================================
    # GLOBAL EXCEPTION HANDLERS WITH CORS HEADERS
    # Ensures frontend can read error responses instead of "Network Error"
    # ==========================================================================

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Handle HTTP exceptions with CORS headers."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "http_error",
                "message": str(exc.detail),
                "status_code": exc.status_code,
            },
            headers=_get_cors_headers(settings),
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Handle unhandled exceptions with CORS headers."""
        logger.exception(f"Unhandled exception: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "An unexpected error occurred",
                "status_code": 500,
            },
            headers=_get_cors_headers(settings),
        )

    # ==========================================================================
    # ROUTERS - Explicit wiring with versioned prefixes
    # ==========================================================================

    # Health check - no auth required, root-level for load balancers
    app.include_router(health_router, prefix="/api", tags=["health"])

    # v1 API - Primary versioned endpoints
    # NOTE: These routers already have /v1/... in their internal prefix
    # We only add /api as the base prefix here
    app.include_router(
        intake_router, prefix="/api/v1", tags=["intake"]
    )  # internal: /intake
    app.include_router(
        enforcement_router, prefix="/api", tags=["enforcement"]
    )  # internal: /v1/enforcement
    app.include_router(
        offers_router, prefix="/api", tags=["offers"]
    )  # internal: /v1/offers
    app.include_router(
        portfolio_router, prefix="/api", tags=["portfolio"]
    )  # internal: /v1/portfolio
    app.include_router(
        search_router, prefix="/api/v1", tags=["search"]
    )  # internal: /search

    # v1 Ops - Operational monitoring endpoints
    app.include_router(
        ops_guardian_router, prefix="/api/v1", tags=["ops"]
    )  # internal: /ops/guardian

    # Legacy / transitional routers (will migrate to v1)
    app.include_router(ingest_router, prefix="/api", tags=["ingest-legacy"])
    app.include_router(ingest_v2_router, tags=["ingest-v2"])
    app.include_router(foil_router, prefix="/api", tags=["foil"])
    app.include_router(
        analytics_router, prefix="/api", tags=["analytics"]
    )  # internal: /v1/analytics
    app.include_router(
        budget_router, prefix="/api", tags=["budget"]
    )  # internal: /v1/budget
    app.include_router(
        intelligence_router, prefix="/api", tags=["intelligence"]
    )  # internal: /v1/intelligence
    app.include_router(
        packets_router, prefix="/api", tags=["packets"]
    )  # internal: /v1/packets
    app.include_router(events_router, prefix="/api", tags=["events"])

    # Webhooks - external service callbacks (Proof.com, etc.)
    app.include_router(
        webhooks_router, prefix="/api", tags=["webhooks"]
    )  # internal: /v1/webhooks

    # Initialize scheduler (uses on_event internally)
    init_scheduler(app)

    # ==========================================================================
    # ROOT ENDPOINTS
    # ==========================================================================

    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        """Root endpoint - service info."""
        return {
            "service": "Dragonfly Engine",
            "version": __version__,
            "status": "running",
            "docs": "/docs",
        }

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        """Simple health check at root level for Railway."""
        return {
            "service": "Dragonfly Engine",
            "status": "ok",
        }

    @app.get("/api", tags=["root"])
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
