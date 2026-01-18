"""
Dragonfly Engine - FastAPI Application

Main application entry point. Creates the FastAPI app, wires up routers,
initializes database pool and scheduler on startup.

Run with: uvicorn backend.main:app --reload

PRODUCTION HARDENING NOTES:
- CORS middleware is FIRST (outermost) to handle preflight correctly
- Global exception handlers include CORS headers for frontend error visibility
- All routers explicitly wired with versioned prefixes

ENVIRONMENT LOADING:
- Environment is loaded BEFORE config import via backend.core.loader
- This ensures strict isolation: --env prod will NEVER load .env.dev
"""

# =============================================================================
# CRITICAL: Configuration Guard - Must run FIRST before any other imports
# =============================================================================
from backend.core.config_guard import (
    validate_db_config,
    validate_production_config,
    validate_runtime_config,
)

validate_runtime_config()  # Phase 0/1: Strict pooler, SSL, and credential leak checks
validate_production_config()  # Additional production safety checks
# =============================================================================

# Must be second - fixes Windows asyncio compatibility with psycopg3
from .asyncio_compat import ensure_selector_policy_on_windows

ensure_selector_policy_on_windows()

# ============================================================================
# CRITICAL: Load environment BEFORE importing config
# This ensures os.environ is populated with the correct .env.{env} values
# ============================================================================
import os  # noqa: E402

from .core.bootstrap import (  # noqa: E402
    BootError,
    ConfigurationError,
    bootstrap_environment,
    generate_boot_report,
    verify_alerting_status,
    verify_runtime_config,
)
from .core.security_guard import verify_safe_environment  # noqa: E402

# Bootstrap environment (respects --env CLI arg, defaults to 'dev')
# Skip if already loaded (e.g., by uvicorn wrapper or test harness)
if not os.environ.get("DRAGONFLY_ACTIVE_ENV"):
    _env_name = bootstrap_environment(verbose=True)
    verify_safe_environment(_env_name)
    verify_runtime_config(_env_name)  # Enforce config hygiene before boot
    verify_alerting_status()
else:
    _env_name = os.environ.get("DRAGONFLY_ACTIVE_ENV", "dev")

# ============================================================================
# Now safe to import config - os.environ is populated
# ============================================================================
import logging  # noqa: E402
import traceback  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from typing import Any, AsyncGenerator  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from . import __version__  # noqa: E402

# Router imports - explicit for clarity
from .api.routers.analytics import router as analytics_router  # noqa: E402
from .api.routers.budget import router as budget_router  # noqa: E402
from .api.routers.cases import router as cases_router  # noqa: E402
from .api.routers.ceo_metrics import router as ceo_metrics_router  # noqa: E402
from .api.routers.dashboard import router as dashboard_router  # noqa: E402
from .api.routers.enforcement import router as enforcement_router  # noqa: E402
from .api.routers.events import router as events_router  # noqa: E402
from .api.routers.finance import router as finance_router  # noqa: E402
from .api.routers.foil import router as foil_router  # noqa: E402
from .api.routers.health import root_router as health_root_router  # noqa: E402
from .api.routers.health import router as health_router  # noqa: E402
from .api.routers.ingest import router as ingest_router  # noqa: E402
from .api.routers.ingest_v2 import router as ingest_v2_router  # noqa: E402
from .api.routers.intake import router as intake_router  # noqa: E402
from .api.routers.integrity import router as integrity_router  # noqa: E402
from .api.routers.intelligence import router as intelligence_router  # noqa: E402

# Optional metrics module - graceful degradation if missing
try:
    from .api.routers.metrics import router as metrics_router  # noqa: E402
except ModuleNotFoundError:
    metrics_router = None  # type: ignore[assignment, misc]
    logging.getLogger(__name__).warning(
        "[BOOT] metrics router unavailable; skipping metrics endpoints"
    )

from .api.routers.offers import router as offers_router  # noqa: E402
from .api.routers.ops_guardian import router as ops_guardian_router  # noqa: E402
from .api.routers.packets import router as packets_router  # noqa: E402
from .api.routers.platform import router as platform_router  # noqa: E402
from .api.routers.portfolio import router as portfolio_router  # noqa: E402
from .api.routers.search import router as search_router  # noqa: E402
from .api.routers.system import router as system_router  # noqa: E402
from .api.routers.telemetry import router as telemetry_router  # noqa: E402
from .api.routers.webhooks import router as webhooks_router  # noqa: E402
from .config import get_settings, log_startup_diagnostics, validate_required_env  # noqa: E402
from .core.middleware import PerformanceLoggingMiddleware  # noqa: E402
from .core.middleware import (
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    ResponseSanitizationMiddleware,
    get_request_id,
)
from .core.trace_middleware import TraceMiddleware, get_trace_id  # noqa: E402
from .db import close_db_pool, database, init_db_pool  # noqa: E402

# Optional: Correlation Middleware - graceful degradation if missing
try:
    from .middleware.correlation import CorrelationMiddleware  # noqa: E402

    _CORRELATION_MIDDLEWARE_AVAILABLE = True
except ModuleNotFoundError as _correlation_err:
    CorrelationMiddleware = None  # type: ignore[assignment, misc]
    _CORRELATION_MIDDLEWARE_AVAILABLE = False
    logging.getLogger(__name__).critical(
        "[BOOT] CorrelationMiddleware missing; proceeding WITHOUT request-id correlation. Error: %s",
        _correlation_err,
    )

from .middleware.metrics import MetricsMiddleware  # noqa: E402
from .middleware.version import VersionMiddleware, get_version_info  # noqa: E402
from .scheduler import init_scheduler  # noqa: E402
from .utils.logging import get_log_metadata, setup_logging  # noqa: E402

# Configure logging before anything else
setup_logging(service_name="dragonfly-api")
logger = logging.getLogger(__name__)
_LOG_METADATA = get_log_metadata()


def _version_log_extra() -> dict[str, str]:
    """Create a fresh copy of version metadata for log records."""

    return dict(_LOG_METADATA)


# Log environment at module load
logger.info(
    f"🚀 Dragonfly booting in [{_env_name.upper()}] mode",
    extra=_version_log_extra(),
)

# =============================================================================
# INDESTRUCTIBLE BOOT: Validate env vars but NEVER crash on missing DB config
# =============================================================================
# The API must boot even if DATABASE_URL is missing - it enters "degraded mode"
# where /health returns 200 but /readyz returns 503.
#
# fail_fast=False means we log warnings but don't raise RuntimeError.
# The db_state module tracks readiness for /readyz endpoint.
_env_validation = validate_required_env(fail_fast=False)
if _env_validation["missing"]:
    logging.warning(f"[BOOT] Missing env vars (degraded mode): {_env_validation['missing']}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler.

    Handles startup and shutdown events:
    - Startup: Verify safe environment, generate boot report, initialize database pool
    - Shutdown: Close database pool, stop DB supervisor

    Uses explicit database.start()/stop() to avoid psycopg_pool deprecation warning:
    "AsyncConnectionPool constructor open is deprecated"

    SECURITY: verify_safe_environment() ensures we never boot with mismatched
    credentials (e.g., dev env with prod keys or vice versa).

    DEGRADED MODE: API starts and serves /health even if DB is unavailable.
    /readyz returns 503 with metadata until DB is ready.
    """
    from .core.db_state import create_db_supervisor, db_state

    # Log startup diagnostics (same format as workers)
    log_startup_diagnostics("DragonflyAPI")

    # ==========================================================================
    # STARTUP SECURITY VERIFICATION
    # ==========================================================================

    logger.info(
        f"Starting Dragonfly Engine v{__version__} [{_env_name.upper()}] "
        f"(process_role={db_state.process_role.value})"
    )

    # 1. Verify safe environment - prevents credential/environment mismatches
    try:
        verify_safe_environment(_env_name)
        logger.info(f"Environment verified: [{_env_name.upper()}]")
    except Exception as e:
        logger.critical(f"ENVIRONMENT VERIFICATION FAILED: {e}")
        raise  # Prevent app from starting with mismatched credentials

    # 2. Generate signed boot report (will raise BootError if critical deps missing)
    try:
        boot_report = generate_boot_report(env=_env_name)
        logger.info(f"Boot report signed: {boot_report.git_sha}")
    except BootError as e:
        logger.critical(f"BOOT REFUSED: {e}")
        raise  # Prevent app from starting

    # 3. Validate database configuration (port 6543 required in prod)
    validate_db_config()

    # 4. Initialize database with explicit lifecycle (avoids deprecation warning)
    # DEGRADED MODE: This will NOT exit on failure for API processes
    db_supervisor = None
    try:
        await database.start()
        if db_state.ready:
            logger.info("Database pool initialized")
        else:
            logger.warning(
                f"[DB] Degraded mode: {db_state.operator_status()}",
                extra={"process_role": db_state.process_role.value},
            )
    except Exception as e:
        logger.error(f"Failed to initialize database pool: {e}")
        # Don't raise - allow app to start for health checks (degraded mode)

    # 5. Start background DB supervisor for reconnection attempts (API only)
    if not db_state.ready and db_state.process_role.value == "api":
        db_supervisor = create_db_supervisor(database.start)
        await db_supervisor.start()
        logger.info("[DB Supervisor] Background reconnection supervisor started")

    yield

    # Shutdown - stop supervisor first, then close DB
    logger.info("Shutting down Dragonfly Engine...")

    if db_supervisor:
        await db_supervisor.stop()

    await database.stop()
    logger.info("Shutdown complete")


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


def _get_required_headers(settings: Any) -> dict[str, str]:
    """
    Build mandatory response headers for ALL responses.

    These headers MUST be present on every response for production certification:
    - X-Dragonfly-Env: Environment name (dev/prod)
    - X-Dragonfly-SHA-Short: Git commit short SHA
    - X-Dragonfly-Version: Package version

    Combined with CORS headers for error responses.
    """
    version_info = get_version_info()
    headers = _get_cors_headers(settings)
    headers.update(
        {
            "X-Dragonfly-Env": version_info.get("env", "unknown"),
            "X-Dragonfly-SHA": version_info.get("sha", "unknown"),
            "X-Dragonfly-SHA-Short": version_info.get("sha_short", "unknown"),
            "X-Dragonfly-Version": version_info.get("version", "unknown"),
        }
    )
    return headers


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
        title="Dragonfly Civil v1.3.1",
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
    # FastAPI adds middleware in REVERSE order (last added = outermost)
    # Execution order: CorrelationMiddleware -> TraceMiddleware -> RateLimitMiddleware -> CORSMiddleware -> VersionMiddleware
    # ==========================================================================

    # --- Add in REVERSE order (last added = first to execute) ---

    # 4. VersionMiddleware (innermost - adds X-Dragonfly-SHA headers to every response)
    app.add_middleware(VersionMiddleware)
    version_info = get_version_info()
    logger.info(
        f"[Middleware] VersionMiddleware added: SHA={version_info['sha_short']} "
        f"Env={version_info['env']}"
    )

    # 3. CORSMiddleware (handles cross-origin requests)
    cors_origins = settings.cors_allowed_origins
    cors_regex = settings.cors_origin_regex
    if not cors_origins and not cors_regex:
        logger.warning(
            "[CORS] DENY ALL - No origins configured. "
            "Set DRAGONFLY_CORS_ORIGINS to allow cross-origin requests."
        )
    else:
        logger.info(
            f"[CORS] Allowed origins: {cors_origins} "
            f"(from DRAGONFLY_CORS_ORIGINS={settings.dragonfly_cors_origins!r})"
        )
        if cors_regex:
            logger.info(f"[CORS] Origin regex enabled: {cors_regex}")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_origin_regex=cors_regex,  # Matches Vercel preview deployments
        allow_credentials=True,  # Required for cross-origin auth
        allow_methods=["*"],
        allow_headers=["*"],  # Accept all headers including X-API-Key
        expose_headers=[
            "Content-Disposition",
            "X-Request-ID",
            "X-Dragonfly-SHA",
            "X-Dragonfly-SHA-Short",
            "X-Dragonfly-Env",
            "X-Dragonfly-Version",
        ],
    )

    # 2. SecurityMiddleware: Rate limiting for abuse detection (always active in prod)
    if settings.is_production:
        app.add_middleware(RateLimitMiddleware)
        logger.info("[Middleware] RateLimitMiddleware enabled for production")
    else:
        logger.info("[Middleware] RateLimitMiddleware DISABLED (non-production)")

    # 1. TraceMiddleware (outermost before correlation - generates trace IDs for every request)
    app.add_middleware(TraceMiddleware)
    logger.info("[Middleware] TraceMiddleware added (trace IDs)")

    # 0. CorrelationMiddleware (true outermost - ensures X-Request-ID is present)
    if _CORRELATION_MIDDLEWARE_AVAILABLE and CorrelationMiddleware is not None:
        app.add_middleware(CorrelationMiddleware)
        logger.info("[Middleware] CorrelationMiddleware added (request IDs)")
    else:
        logger.critical(
            "[BOOT] CorrelationMiddleware missing; proceeding WITHOUT request-id correlation."
        )

    # --- Additional middleware (after core security stack) ---

    # Response sanitization (safety net for credential leaks)
    app.add_middleware(ResponseSanitizationMiddleware, strict_mode=settings.is_production)
    logger.info(f"[Middleware] ResponseSanitizationMiddleware (strict={settings.is_production})")

    # Performance logging (slow query detection)
    app.add_middleware(PerformanceLoggingMiddleware, threshold_s=1.0)

    # Request logging (logs after CORS/rate limit decisions)
    app.add_middleware(RequestLoggingMiddleware)

    # Metrics collection (counts requests and errors for /api/metrics)
    app.add_middleware(MetricsMiddleware)
    logger.info("[Middleware] MetricsMiddleware added (request/error counting)")

    # ==========================================================================
    # GLOBAL EXCEPTION HANDLERS WITH REQUIRED HEADERS
    # All responses include CORS + Dragonfly version headers for traceability
    # ==========================================================================

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Handle HTTP exceptions with CORS + version headers."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "http_error",
                "message": str(exc.detail),
                "status_code": exc.status_code,
            },
            headers=_get_required_headers(settings),
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """
        Handle unhandled exceptions with CORS headers.

        - Logs FULL stack trace to console (visible in Railway logs)
        - Returns CLEAN JSON to frontend (no internal details)
        - Includes request_id and trace_id for correlation
        """
        req_id = get_request_id() or "unknown"
        trace_id = get_trace_id()

        # Log full stack trace for debugging (Railway logs)
        tb_str = traceback.format_exception(type(exc), exc, exc.__traceback__)
        logger.error(
            f"[{req_id}] [trace:{trace_id}] 🔥 UNHANDLED EXCEPTION on {request.method} {request.url.path}\n"
            f"{''.join(tb_str)}",
            extra={
                "request_id": req_id,
                "trace_id": trace_id,
                "path": request.url.path,
                "method": request.method,
                "exception_type": type(exc).__name__,
            },
        )

        # Return clean JSON - NEVER expose stack trace to frontend
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal System Error",
                "code": "500",
                "request_id": req_id,
                "trace_id": trace_id,
            },
            headers=_get_required_headers(settings),
        )

    # ==========================================================================
    # ROUTERS - Explicit wiring with versioned prefixes
    # ==========================================================================

    # Platform endpoints - /api/version and /api/ready (no auth required)
    app.include_router(platform_router, prefix="/api", tags=["platform"])

    # Root-level health probes - /health and /readyz (no prefix, for load balancers)
    # These are the "World-Class Certification" endpoints
    app.include_router(health_root_router, prefix="", tags=["probes"])

    # Health check - /api/health/* for detailed monitoring
    app.include_router(health_router, prefix="/api", tags=["health"])

    # v1 API - Primary versioned endpoints
    # NOTE: These routers already have /v1/... in their internal prefix
    # We only add /api as the base prefix here
    app.include_router(cases_router, prefix="/api", tags=["cases"])  # internal: /v1/cases
    app.include_router(intake_router, prefix="/api/v1", tags=["intake"])  # internal: /intake
    app.include_router(
        enforcement_router, prefix="/api", tags=["enforcement"]
    )  # internal: /v1/enforcement
    app.include_router(offers_router, prefix="/api", tags=["offers"])  # internal: /v1/offers
    app.include_router(
        portfolio_router, prefix="/api", tags=["portfolio"]
    )  # internal: /v1/portfolio
    app.include_router(search_router, prefix="/api/v1", tags=["search"])  # internal: /search

    # v1 Ops - Operational monitoring endpoints
    app.include_router(
        ops_guardian_router, prefix="/api/v1", tags=["ops"]
    )  # internal: /ops/guardian

    # v1 Integrity - Data integrity and reconciliation dashboard
    app.include_router(
        integrity_router, prefix="/api", tags=["integrity"]
    )  # internal: /v1/integrity

    # v1 Telemetry - UI action tracking
    app.include_router(
        telemetry_router, prefix="/api", tags=["telemetry"]
    )  # internal: /v1/telemetry

    # Legacy / transitional routers (will migrate to v1)
    app.include_router(ingest_router, prefix="/api", tags=["ingest-legacy"])
    app.include_router(ingest_v2_router, tags=["ingest-v2"])
    app.include_router(foil_router, prefix="/api", tags=["foil"])
    app.include_router(
        analytics_router, prefix="/api", tags=["analytics"]
    )  # internal: /v1/analytics
    app.include_router(budget_router, prefix="/api", tags=["budget"])  # internal: /v1/budget
    app.include_router(
        ceo_metrics_router, prefix="/api", tags=["ceo"]
    )  # internal: /v1/ceo (12 CEO Metrics)
    app.include_router(
        intelligence_router, prefix="/api", tags=["intelligence"]
    )  # internal: /v1/intelligence
    app.include_router(packets_router, prefix="/api", tags=["packets"])  # internal: /v1/packets
    app.include_router(events_router, prefix="/api", tags=["events"])

    # Finance - Securitization engine (pools, NAV, performance)
    app.include_router(finance_router, prefix="/api", tags=["finance"])  # internal: /v1/finance

    # System - Worker heartbeats and system health
    app.include_router(system_router, prefix="/api", tags=["system"])  # internal: /v1/system

    # Observability - Lightweight metrics endpoint (requires API key)
    if metrics_router is not None:
        app.include_router(metrics_router, prefix="/api", tags=["observability"])  # /api/metrics

    # Webhooks - external service callbacks (Proof.com, etc.)
    app.include_router(webhooks_router, prefix="/api", tags=["webhooks"])  # internal: /v1/webhooks

    # Dashboard Fallback - Direct SQL dashboard endpoints (bypasses PostgREST)
    # Always available for PGRST002 incident mitigation
    app.include_router(dashboard_router, tags=["dashboard-fallback"])  # internal: /api/v1/dashboard
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

    # NOTE: /health and /readyz are provided by health_root_router (prefix="")
    # They are NOT duplicated here - see backend/api/routers/health.py root_router
    # This ensures consistent responses with version/sha/env fields

    @app.get("/api", tags=["root"])
    async def api_root() -> dict[str, str]:
        """API root endpoint."""
        return {
            "message": "Dragonfly Engine API",
            "version": __version__,
            "health": "/api/health",
            "readiness": "/readyz",
        }

    @app.get("/api/version", tags=["health"])
    async def api_version() -> dict[str, str]:
        """
        Get API version - cheap, no DB queries.

        Suitable for frequent polling by monitoring tools.
        """
        from datetime import datetime

        return {
            "version": __version__,
            "environment": settings.environment,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    @app.get("/api/ready", tags=["health"])
    async def api_ready() -> JSONResponse:
        """
        Readiness probe - validates DB and Supabase connectivity.

        Returns 200 if ready, 503 if not.
        """
        from .api.routers.health import readiness_check

        result = await readiness_check()
        # readiness_check returns either ReadinessResponse or JSONResponse
        if isinstance(result, JSONResponse):
            return result
        return JSONResponse(content=result.model_dump())

    logger.info(f"FastAPI app created: {app.title}")

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
