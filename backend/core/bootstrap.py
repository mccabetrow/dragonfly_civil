"""
Dragonfly Engine - Environment Bootstrap

STRICT ENVIRONMENT LOADING
==========================

This module handles environment loading BEFORE Pydantic touches anything.
It enforces strict precedence: CLI Args > System Env Vars.

CRITICAL: No implicit .env loading!
    This module NEVER loads a local .env file unless explicitly told
    to load .env.{env_name} for the specified environment.

Usage:
------
    # In entrypoints (main.py, workers, scripts):
    from backend.core.bootstrap import bootstrap_environment

    # MUST run before importing any config
    env_name = bootstrap_environment()

    # Now safe to import settings
    from backend.core.config import get_settings
    settings = get_settings()

    print(f"🚀 Booting in [{env_name.upper()}] mode")

SECURITY:
    After bootstrap, call verify_safe_environment() to ensure
    credentials match the target environment.

PRODUCTION SAFETY:
    Call generate_boot_report() at startup to verify critical
    dependencies and log a signed boot report.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

# Environment marker key - set after successful load
ENV_MARKER = "DRAGONFLY_ACTIVE_ENV"

# Project root (where .env files live)
_PROJECT_ROOT: Path | None = None


def _find_project_root() -> Path:
    """Find the project root directory (contains .env.dev or pyproject.toml)."""
    global _PROJECT_ROOT
    if _PROJECT_ROOT is not None:
        return _PROJECT_ROOT

    # Start from current working directory
    search_paths = [
        Path.cwd(),
        Path(__file__).parent.parent.parent,  # backend/core -> backend -> project_root
    ]

    markers = [".env.dev", ".env.prod", "pyproject.toml", "supabase"]

    for start in search_paths:
        current = start.resolve()
        for _ in range(5):  # Max 5 levels up
            for marker in markers:
                if (current / marker).exists():
                    _PROJECT_ROOT = current
                    return current
            parent = current.parent
            if parent == current:
                break
            current = parent

    # Fallback to cwd
    _PROJECT_ROOT = Path.cwd()
    return _PROJECT_ROOT


def _parse_env_from_argv() -> str | None:
    """
    Parse sys.argv manually to find --env or -e flags.

    This avoids argparse conflicts with other CLI tools.

    Returns:
        Environment name if found, None otherwise
    """
    args = sys.argv[1:]  # Skip script name

    for i, arg in enumerate(args):
        # Handle --env=prod or --env prod
        if arg.startswith("--env="):
            return arg.split("=", 1)[1].strip()
        if arg == "--env" and i + 1 < len(args):
            return args[i + 1].strip()

        # Handle -e prod
        if arg == "-e" and i + 1 < len(args):
            return args[i + 1].strip()

    return None


def _load_dotenv_file(env_file: Path) -> int:
    """
    Load environment variables from a dotenv file.

    Args:
        env_file: Path to the .env.{env} file

    Returns:
        Number of variables loaded

    Raises:
        FileNotFoundError: If the env file doesn't exist
    """
    try:
        from dotenv import load_dotenv
    except ImportError as e:
        raise ImportError(
            "python-dotenv is required for environment loading. "
            "Install with: pip install python-dotenv"
        ) from e

    # STRICT: No fallback - file MUST exist
    if not env_file.exists():
        raise FileNotFoundError(
            f"Environment file not found: {env_file}\n"
            f"Expected: .env.dev or .env.prod in project root.\n"
            f"Searched: {env_file.parent}"
        )

    # Load with override=True to force these values into os.environ
    load_dotenv(env_file, override=True)

    # Count loaded vars (for logging)
    from dotenv import dotenv_values

    values = dotenv_values(env_file)
    return len([v for v in values.values() if v is not None])


def bootstrap_environment(
    cli_override: str | None = None,
    project_root: Path | None = None,
    verbose: bool = True,
) -> Literal["dev", "prod"]:
    """
    Bootstrap the environment with strict precedence.

    Precedence (highest to lowest):
        1. cli_override parameter (for programmatic control)
        2. CLI args (--env prod or -e prod)
        3. System env var DRAGONFLY_ACTIVE_ENV
        4. Default: 'dev'

    Args:
        cli_override: Override environment (highest priority)
        project_root: Project root directory (auto-detected if None)
        verbose: Print startup diagnostics

    Returns:
        The environment name ('dev' or 'prod')

    Raises:
        FileNotFoundError: If .env.{env} file doesn't exist
        ValueError: If environment name is invalid
    """
    # Step 1: Determine target environment
    env_name: str

    if cli_override:
        env_name = cli_override
        source = "cli_override"
    else:
        argv_env = _parse_env_from_argv()
        if argv_env:
            env_name = argv_env
            source = "CLI (--env)"
        elif os.environ.get(ENV_MARKER):
            env_name = os.environ[ENV_MARKER]
            source = f"env var ({ENV_MARKER})"
        else:
            env_name = "dev"
            source = "default"

    # Step 2: Validate environment name
    env_name = env_name.lower().strip()
    if env_name not in ("dev", "prod"):
        raise ValueError(f"Invalid environment: '{env_name}'. Must be 'dev' or 'prod'.")

    # Step 3: Find project root
    root = project_root or _find_project_root()

    # Step 4: Construct target filename
    env_file = root / f".env.{env_name}"

    # Step 5: Load the env file (STRICT - no fallback)
    var_count = _load_dotenv_file(env_file)

    # Step 6: Set the environment marker
    os.environ[ENV_MARKER] = env_name
    os.environ["DRAGONFLY_ENV"] = env_name  # For Pydantic Settings
    os.environ["SUPABASE_MODE"] = env_name  # Legacy compatibility

    # Step 7: Print startup banner
    if verbose:
        _print_startup_banner(env_name, source, env_file, var_count)

    return env_name  # type: ignore[return-value]


def _print_startup_banner(
    env_name: str,
    source: str,
    env_file: Path,
    var_count: int,
) -> None:
    """Print startup diagnostics."""
    db_url = os.environ.get("SUPABASE_DB_URL", "")
    db_host = "unknown"

    if db_url:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(db_url)
            db_host = parsed.hostname or "unknown"
        except Exception:
            pass

    # Color based on environment
    if env_name == "prod":
        env_badge = "\033[91m[PROD]\033[0m"  # Red
    else:
        env_badge = "\033[92m[DEV]\033[0m"  # Green

    print(
        f"\n"
        f"╔══════════════════════════════════════════════════════════════════╗\n"
        f"║  🐉 DRAGONFLY BOOTSTRAP                                          ║\n"
        f"╠══════════════════════════════════════════════════════════════════╣\n"
        f"║  Environment: {env_badge:<44}║\n"
        f"║  Source:      {source:<44}║\n"
        f"║  Env File:    {env_file.name:<44}║\n"
        f"║  Variables:   {var_count:<44}║\n"
        f"║  DB Host:     {db_host[:44]:<44}║\n"
        f"╚══════════════════════════════════════════════════════════════════╝\n"
    )


def get_active_environment() -> str | None:
    """
    Get the currently active environment.

    Returns:
        Environment name or None if not bootstrapped
    """
    return os.environ.get(ENV_MARKER)


def require_environment(expected: Literal["dev", "prod"]) -> None:
    """
    Assert that the current environment matches expected.

    Args:
        expected: The required environment

    Raises:
        RuntimeError: If environment doesn't match or not bootstrapped
    """
    current = get_active_environment()

    if current is None:
        raise RuntimeError(
            "Environment not bootstrapped. Call bootstrap_environment() before importing config."
        )

    if current != expected:
        raise RuntimeError(f"Environment mismatch: running '{current}' but expected '{expected}'")


def verify_alerting_status() -> bool:
    """
    Log Discord alerting status at boot time (without leaking secrets).

    Call this after bootstrap_environment() and verify_safe_environment()
    to confirm whether operational alerts are wired up.

    Returns:
        True if Discord alerting is enabled, False otherwise.
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")

    if webhook_url and webhook_url.startswith("http"):
        print("🔔 Discord alerts: ENABLED")
        return True
    else:
        print("🔕 Discord alerts: DISABLED (Webhook missing)")
        return False


# =============================================================================
# Runtime Configuration Guard - Production Safety
# =============================================================================


class ConfigurationError(Exception):
    """Critical configuration error that prevents application startup."""

    pass


def verify_runtime_config(env: str) -> None:
    """
    Verify runtime configuration hygiene before boot.

    This function enforces strict configuration rules for production safety:

    RULE 1 - THE BAN (Production Only):
        SUPABASE_MIGRATE_DB_URL must NOT be present in production runtime.
        This variable uses Direct Connection (bypasses pooler) and is
        dangerous for runtime services (API/Workers).

    RULE 2 - THE REQUIREMENT:
        SUPABASE_DB_URL must be set for database-dependent services.

    RULE 3 - POOLER ENFORCEMENT (Warning):
        Runtime should use the Supabase Pooler (port 6543) for connection
        management. Direct connections (port 5432) are warned.

    Args:
        env: The target environment ('dev' or 'prod')

    Raises:
        ConfigurationError: If SUPABASE_MIGRATE_DB_URL is found in production
        ConfigurationError: If SUPABASE_DB_URL is missing

    Example:
        from backend.core.bootstrap import verify_runtime_config

        verify_runtime_config(env_name)  # Call before generate_boot_report()
    """
    from urllib.parse import urlparse

    # =========================================================================
    # RULE 1: BAN SUPABASE_MIGRATE_DB_URL in Production Runtime
    # =========================================================================
    migrate_url = os.environ.get("SUPABASE_MIGRATE_DB_URL")

    if env == "prod" and migrate_url is not None:
        # This is a CRITICAL security violation
        logger.critical(
            "CRITICAL: SUPABASE_MIGRATE_DB_URL detected in runtime environment. "
            "Direct DB access is forbidden in Production runtime services."
        )

        # Print visible error
        red = "\033[91m"
        bold = "\033[1m"
        reset = "\033[0m"

        print(
            f"\n{red}{bold}"
            f"╔══════════════════════════════════════════════════════════════════╗\n"
            f"║  🚨 CRITICAL: FORBIDDEN CONFIGURATION DETECTED                   ║\n"
            f"╠══════════════════════════════════════════════════════════════════╣\n"
            f"║                                                                  ║\n"
            f"║  SUPABASE_MIGRATE_DB_URL is present in PRODUCTION runtime.      ║\n"
            f"║                                                                  ║\n"
            f"║  This variable uses Direct Connection (bypasses pooler) and     ║\n"
            f"║  is ONLY allowed for migration scripts, NOT runtime services.   ║\n"
            f"║                                                                  ║\n"
            f"║  ACTION: Remove SUPABASE_MIGRATE_DB_URL from your production    ║\n"
            f"║          Railway service environment variables.                 ║\n"
            f"║                                                                  ║\n"
            f"╚══════════════════════════════════════════════════════════════════╝"
            f"{reset}\n"
        )

        raise ConfigurationError(
            "SECURITY: Direct DB access forbidden in Runtime. "
            "Unset SUPABASE_MIGRATE_DB_URL from production environment."
        )

    # In dev, just log a warning if migrate URL is present
    if env == "dev" and migrate_url is not None:
        logger.info(
            "Migration-only environment variables detected "
            "(OK for scripts, not for runtime): SUPABASE_MIGRATE_DB_URL"
        )

    # =========================================================================
    # RULE 2: REQUIRE SUPABASE_DB_URL
    # =========================================================================
    db_url = os.environ.get("SUPABASE_DB_URL")

    if not db_url:
        # Some services might be REST-only, so this is a warning in dev
        if env == "prod":
            logger.warning(
                "SUPABASE_DB_URL not configured - database-dependent features unavailable"
            )
        # Don't raise - allow REST-only operation

    # =========================================================================
    # RULE 3: POOLER ENFORCEMENT (Warning Only)
    # =========================================================================
    if db_url:
        try:
            parsed = urlparse(db_url)
            port = parsed.port
            hostname = parsed.hostname or ""

            # Supabase Pooler uses port 6543
            # Direct connection uses port 5432
            is_pooler = port == 6543 or "pooler" in hostname.lower()
            is_direct = port == 5432

            if is_direct and not is_pooler:
                yellow = "\033[93m"
                reset = "\033[0m"

                print(
                    f"{yellow}⚠️  Runtime might be using direct connection instead of pooler.{reset}"
                )
                print(f"   DB Port: {port} (Pooler uses 6543, Direct uses 5432)")
                print(f"   DB Host: {hostname[:50]}")
                print()

                logger.warning(
                    f"Runtime using direct connection (port {port}) instead of pooler (6543). "
                    "This may cause connection exhaustion under load."
                )

        except Exception as e:
            logger.debug(f"Could not parse SUPABASE_DB_URL for pooler check: {e}")

    # All checks passed
    logger.debug(f"Runtime configuration verified for [{env}] environment")


# =============================================================================
# Boot Report - Production Safety
# =============================================================================


class BootError(Exception):
    """Critical boot error that prevents application startup."""

    pass


@dataclass
class BootReport:
    """
    Signed boot report for production safety.

    This report captures the state of the application at boot time,
    including critical dependency checks and environment verification.
    """

    git_sha: str
    env: str
    boot_time: str
    postgrest_status: str
    alerting_enabled: bool
    rag_enabled: bool
    openai_configured: bool
    database_url_configured: bool
    supabase_url: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "git_sha": self.git_sha,
            "env": self.env,
            "boot_time": self.boot_time,
            "postgrest_status": self.postgrest_status,
            "alerting_enabled": self.alerting_enabled,
            "rag_enabled": self.rag_enabled,
            "openai_configured": self.openai_configured,
            "database_url_configured": self.database_url_configured,
            "supabase_url": self.supabase_url,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def is_healthy(self) -> bool:
        """Check if boot report indicates healthy state."""
        return len(self.errors) == 0


def _check_postgrest_health(env: str) -> str:
    """
    Check PostgREST health status.

    Returns:
        Status string: 'healthy', 'stale_cache', 'unavailable', or 'unknown'
    """
    try:
        from backend.core.health import HealthStatus, check_postgrest_status

        result = check_postgrest_status(env=env)  # type: ignore[arg-type]
        return result.status.value
    except ImportError:
        return "unknown (health module not available)"
    except Exception as e:
        logger.warning(f"PostgREST health check failed: {e}")
        return f"error: {str(e)[:50]}"


def _redact_url(url: str) -> str:
    """Redact password from URL for safe logging."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.password:
            # Replace password with [REDACTED]
            return url.replace(f":{parsed.password}@", ":[REDACTED]@")
        return parsed.hostname or url[:30]
    except Exception:
        return url[:30] + "..."


def get_git_sha() -> str:
    """
    Resolve the current git commit SHA for boot reports.

    Resolution order:
        1. RAILWAY_GIT_COMMIT_SHA env var (Railway deployment)
        2. GIT_COMMIT env var (Generic CI systems)
        3. VERCEL_GIT_COMMIT_SHA env var (Vercel deployment)
        4. Local git rev-parse --short HEAD (local dev)
        5. Fallback: "unknown"

    Returns:
        Short git SHA (e.g., "a1b2c3d") or "unknown"
    """
    # Step 1: Check Railway environment variable (primary production target)
    railway_sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA")
    if railway_sha:
        sha = railway_sha[:7] if len(railway_sha) > 7 else railway_sha
        logger.debug(f"Resolved git SHA from RAILWAY_GIT_COMMIT_SHA: {sha}")
        return sha

    # Step 2: Check generic CI environment variable
    generic_sha = os.environ.get("GIT_COMMIT")
    if generic_sha:
        sha = generic_sha[:7] if len(generic_sha) > 7 else generic_sha
        logger.debug(f"Resolved git SHA from GIT_COMMIT: {sha}")
        return sha

    # Step 3: Check Vercel environment variable
    vercel_sha = os.environ.get("VERCEL_GIT_COMMIT_SHA")
    if vercel_sha:
        sha = vercel_sha[:7] if len(vercel_sha) > 7 else vercel_sha
        logger.debug(f"Resolved git SHA from VERCEL_GIT_COMMIT_SHA: {sha}")
        return sha

    # Step 4: Try local git (dev mode)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=_find_project_root(),
        )
        if result.returncode == 0 and result.stdout.strip():
            sha = result.stdout.strip()
            logger.debug(f"Resolved git SHA from local repo: {sha}")
            return sha
    except FileNotFoundError:
        # git command not found (e.g., minimal Docker container)
        logger.debug("git command not found, using fallback")
    except subprocess.TimeoutExpired:
        logger.warning("git rev-parse timed out, using fallback")
    except Exception as e:
        logger.debug(f"Failed to get local git SHA: {e}")

    # Step 5: Final fallback
    logger.warning("Could not resolve git SHA from any source")
    return "unknown"


class RuntimeConfigurationError(RuntimeError):
    """Raised when runtime environment is dangerously misconfigured."""

    pass


def verify_runtime_env() -> None:
    """
    Verify runtime environment is safe before starting the application.

    This function MUST be called during application startup (FastAPI lifespan,
    worker boot) to prevent dangerous misconfigurations.

    CRITICAL CHECKS:
    ----------------
    1. Migration URL in Production: If SUPABASE_MIGRATE_DB_URL is present
       AND we're in prod, CRASH immediately. The migration URL (port 5432)
       bypasses the connection pooler and should NEVER be in runtime.

    2. Database URL Missing: If neither DATABASE_URL nor SUPABASE_DB_URL
       is configured, log a warning (may work with REST-only mode).

    3. Pooler Port Warning: If the DB URL uses port 5432 instead of 6543,
       warn that we're bypassing the pooler (higher connection usage).

    Raises:
        RuntimeConfigurationError: If migration URL detected in production

    Example:
        >>> from backend.core.bootstrap import verify_runtime_env
        >>> verify_runtime_env()  # Call at startup
    """
    env_name = os.environ.get("DRAGONFLY_ENV", os.environ.get("ENVIRONMENT", "dev")).lower()
    is_prod = env_name in ("prod", "production")

    # ═══════════════════════════════════════════════════════════════════════
    # CHECK 1: Migration URL in Production (FATAL)
    # ═══════════════════════════════════════════════════════════════════════
    migrate_url = os.environ.get("SUPABASE_MIGRATE_DB_URL")
    if migrate_url and is_prod:
        error_msg = (
            "CRITICAL: Migration URL detected in Production Runtime!\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "SUPABASE_MIGRATE_DB_URL uses port 5432 (direct connection)\n"
            "which bypasses the connection pooler and can exhaust DB slots.\n"
            "\n"
            "ACTION REQUIRED:\n"
            "  1. Go to Railway Dashboard → Variables\n"
            "  2. DELETE the SUPABASE_MIGRATE_DB_URL variable\n"
            "  3. Redeploy the service\n"
            "\n"
            "The runtime should ONLY use SUPABASE_DB_URL (port 6543 pooler).\n"
            "Migration URLs are for CI/CD pipelines only, not runtime."
        )
        logger.critical(error_msg)
        raise RuntimeConfigurationError(
            "CRITICAL: Migration URL detected in Runtime. "
            "Remove SUPABASE_MIGRATE_DB_URL from Railway."
        )

    # ═══════════════════════════════════════════════════════════════════════
    # CHECK 2: Database URL Presence
    # ═══════════════════════════════════════════════════════════════════════
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        logger.warning(
            "⚠️ No DATABASE_URL or SUPABASE_DB_URL configured. "
            "Application may only work in REST-only mode."
        )
        return  # Can't check port if no URL

    # ═══════════════════════════════════════════════════════════════════════
    # CHECK 3: Pooler Port Warning (Non-fatal)
    # ═══════════════════════════════════════════════════════════════════════
    try:
        from urllib.parse import urlparse

        parsed = urlparse(db_url)
        port = parsed.port

        if port == 5432:
            logger.warning(
                "⚠️ Database URL uses port 5432 (direct connection). "
                "Consider using port 6543 (pooler) for better connection management. "
                f"Host: {parsed.hostname}"
            )
        elif port == 6543:
            logger.debug("✓ Database URL correctly uses pooler port 6543")
        elif port:
            logger.info(f"Database URL uses non-standard port {port}")

    except Exception as e:
        logger.debug(f"Could not parse database URL for port check: {e}")

    logger.info(f"✓ Runtime environment verified (env={env_name}, prod={is_prod})")


def generate_boot_report(
    env: str | None = None,
    skip_postgrest_check: bool = False,
) -> BootReport:
    """
    Generate a signed boot report for production safety.

    This function verifies critical dependencies and produces a structured
    report suitable for logging and monitoring.

    CRITICAL CHECKS:
    - If RAG_ENABLED=true and OPENAI_API_KEY is missing → BootError
    - If SUPABASE_DB_URL is missing → Warning (may work with REST only)

    Args:
        env: Environment name (auto-detected if None)
        skip_postgrest_check: Skip PostgREST health check (for faster boot)

    Returns:
        BootReport with all checks completed

    Raises:
        BootError: If critical dependencies are missing (e.g., OpenAI key with RAG)
    """
    # Determine environment
    if env is None:
        env = get_active_environment() or "unknown"

    errors: list[str] = []
    warnings: list[str] = []

    # Collect boot metadata - use get_git_sha() for reliable resolution
    git_sha = get_git_sha()
    boot_time = datetime.now(timezone.utc).isoformat()

    # Check RAG/OpenAI dependency
    rag_enabled = os.environ.get("RAG_ENABLED", "false").lower() == "true"
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    openai_configured = bool(openai_key and openai_key.startswith("sk-"))

    # CRITICAL: RAG requires OpenAI
    if rag_enabled and not openai_configured:
        errors.append("CRITICAL: RAG_ENABLED=true but OPENAI_API_KEY is missing or invalid")

    # Check database configuration
    db_url = os.environ.get("SUPABASE_DB_URL", "")
    database_url_configured = bool(db_url and "postgresql" in db_url.lower())

    if not database_url_configured:
        warnings.append("SUPABASE_DB_URL not configured - direct DB access unavailable")

    # Check Supabase REST URL
    supabase_url = os.environ.get("SUPABASE_URL", "")
    if not supabase_url:
        warnings.append("SUPABASE_URL not configured - REST API unavailable")

    # Check alerting
    alerting_enabled = bool(os.environ.get("DISCORD_WEBHOOK_URL", "").startswith("http"))

    if env == "prod" and not alerting_enabled:
        warnings.append("Discord alerting not configured in production")

    # PostgREST health check (optional)
    if skip_postgrest_check:
        postgrest_status = "skipped"
    else:
        postgrest_status = _check_postgrest_health(env)

    # Build report
    report = BootReport(
        git_sha=git_sha,
        env=env,
        boot_time=boot_time,
        postgrest_status=postgrest_status,
        alerting_enabled=alerting_enabled,
        rag_enabled=rag_enabled,
        openai_configured=openai_configured,
        database_url_configured=database_url_configured,
        supabase_url=_redact_url(supabase_url) if supabase_url else "",
        errors=errors,
        warnings=warnings,
    )

    # Log the boot report as structured JSON
    log_data = {"event": "BOOT_REPORT", "data": report.to_dict()}
    print(json.dumps(log_data))

    # Print human-readable summary
    _print_boot_report_summary(report)

    # CRITICAL: Refuse to start if there are errors
    if errors:
        error_msg = f"Boot failed with {len(errors)} critical error(s):\n" + "\n".join(
            f"  - {e}" for e in errors
        )
        logger.critical(error_msg)
        raise BootError(error_msg)

    return report


def _print_boot_report_summary(report: BootReport) -> None:
    """Print human-readable boot report summary."""
    # Status indicator
    if report.errors:
        status = "❌ BOOT FAILED"
        color = "\033[91m"  # Red
    elif report.warnings:
        status = "⚠️  BOOT OK (with warnings)"
        color = "\033[93m"  # Yellow
    else:
        status = "✅ BOOT OK"
        color = "\033[92m"  # Green

    reset = "\033[0m"

    print(
        f"\n"
        f"╔══════════════════════════════════════════════════════════════════╗\n"
        f"║  📋 SIGNED BOOT REPORT                                           ║\n"
        f"╠══════════════════════════════════════════════════════════════════╣\n"
        f"║  Status:      {color}{status:<44}{reset}║\n"
        f"║  Environment: {report.env.upper():<44}║\n"
        f"║  Git SHA:     {report.git_sha[:44]:<44}║\n"
        f"║  Boot Time:   {report.boot_time[:44]:<44}║\n"
        f"╠══════════════════════════════════════════════════════════════════╣\n"
        f"║  PostgREST:   {report.postgrest_status[:44]:<44}║\n"
        f"║  Alerting:    {'ENABLED' if report.alerting_enabled else 'DISABLED':<44}║\n"
        f"║  RAG:         {'ENABLED' if report.rag_enabled else 'DISABLED':<44}║\n"
        f"║  OpenAI:      {'CONFIGURED' if report.openai_configured else 'NOT CONFIGURED':<44}║\n"
        f"║  Database:    {'CONFIGURED' if report.database_url_configured else 'NOT CONFIGURED':<44}║\n"
        f"╚══════════════════════════════════════════════════════════════════╝"
    )

    if report.warnings:
        print(f"\n{color}⚠️  Warnings:{reset}")
        for warning in report.warnings:
            print(f"   - {warning}")

    if report.errors:
        print(f"\n{color}❌ Errors:{reset}")
        for error in report.errors:
            print(f"   - {error}")

    print()  # Blank line for readability
