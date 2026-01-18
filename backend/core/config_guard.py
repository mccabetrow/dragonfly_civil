"""
Dragonfly Civil - Configuration Guard

CRITICAL STARTUP VALIDATION
============================

This module MUST be imported at the very top of all entrypoints:
- backend/api/main.py
- backend/workers/base.py
- Any standalone worker scripts

It enforces strict separation between Runtime and Migration environments,
preventing accidental exposure of direct database credentials in production.

SINGLE DSN CONTRACT:
====================
CANONICAL VARIABLE: DATABASE_URL
DEPRECATED (with warning): SUPABASE_DB_URL

All runtime code should use DATABASE_URL. SUPABASE_DB_URL is accepted
with a deprecation warning for backward compatibility.

SECURITY MODEL:
- Runtime services use DATABASE_URL (port 6543, connection pooler)
- Migrations use SUPABASE_MIGRATE_DB_URL (port 5432, direct connection)
- These MUST NEVER be mixed in production runtime

EXECUTION MODE DETECTION:
- Runtime mode: API servers, workers, background services
- Scripts mode: CLI tools (tools.*, etl.*), migrations, one-off scripts

The module distinguishes execution modes to allow scripts to use
SUPABASE_MIGRATE_DB_URL while blocking it in runtime services.

Usage:
    # At the very top of your entrypoint (before other imports)
    from backend.core.config_guard import validate_production_config
    validate_production_config()

    # Now safe to import the rest of your application
    from backend.main import app

Author: Principal DevOps Engineer
Date: 2026-01-07
Updated: 2026-01-11 - Added execution mode detection and auth failure handling
Updated: 2026-01-15 - Single DSN Contract (DATABASE_URL canonical)
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Literal, Optional
from urllib.parse import urlparse

# Use basic logging since this runs before structured logging is configured
logger = logging.getLogger("dragonfly.config_guard")

# ANSI colors for terminal output (falls back gracefully)
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RESET = "\033[0m"
BOLD = "\033[1m"

# =============================================================================
# RUNTIME CONFIG POLICY TABLE (for documentation)
# =============================================================================
# Rule                          | Condition                | Severity | Action
# ------------------------------|--------------------------|----------|--------
# ENV_FILE missing              | .env.{env} not found     | INFO     | Warn, continue
# SUPABASE_MIGRATE_DB_URL       | Var present in runtime   | FATAL    | Exit 1
# SUPABASE_MIGRATE_DB_URL       | Var present in scripts   | ALLOWED  | Continue
# Port 5432 in prod runtime     | DB URL port 5432, prod   | FATAL    | Exit 1
# sslmode missing in prod       | No sslmode, prod runtime | FATAL    | Exit 1
# sslmode=disable in prod       | sslmode=disable, prod    | FATAL    | Exit 1
# Auth failure                  | password/role/db error   | FATAL    | Exit immediately
# Network/transient failure     | timeout, unreachable     | WARN     | Backoff + retry
# =============================================================================

# Patterns that indicate auth failures (no retry, exit fast)
AUTH_FAILURE_PATTERNS = frozenset(
    [
        "password authentication failed",
        "role",  # "role X does not exist"
        "does not exist",
        "server_login_retry",
        "too many connections",
        "FATAL:  password",
        "authentication failed",
    ]
)

# Patterns that indicate network/transient failures (retry with backoff)
NETWORK_FAILURE_PATTERNS = frozenset(
    [
        "could not connect",
        "connection refused",
        "connection timed out",
        "network is unreachable",
        "timeout expired",
        "server closed the connection unexpectedly",
        "SSL SYSCALL error",
    ]
)

# Script module prefixes that indicate non-runtime execution
SCRIPT_MODULE_PREFIXES = ("tools.", "etl.", "tests.", "scripts.")

ExecutionMode = Literal["runtime", "script"]

_EXECUTION_MODE: ExecutionMode | None = None


# =============================================================================
# SINGLE DSN CONTRACT HELPERS
# =============================================================================

# Canonical variable name
CANONICAL_DB_VAR = "DATABASE_URL"

# Deprecated variable (maps to canonical with warning)
DEPRECATED_DB_VAR = "SUPABASE_DB_URL"

_dsn_deprecation_warned = False


def _get_database_url_for_guard() -> str | None:
    """
    Get database URL using Single DSN Contract.

    Priority:
        1. DATABASE_URL (canonical)
        2. SUPABASE_DB_URL (deprecated, emits warning once)

    Returns:
        Database URL or None if not set.
    """
    global _dsn_deprecation_warned

    # Priority 1: Canonical
    db_url = os.environ.get(CANONICAL_DB_VAR, "").strip()
    if db_url:
        return db_url

    # Priority 2: Deprecated (with warning)
    db_url = os.environ.get(DEPRECATED_DB_VAR, "").strip()
    if db_url:
        if not _dsn_deprecation_warned:
            _dsn_deprecation_warned = True
            logger.warning(
                "Environment variable '%s' is DEPRECATED. "
                "Use '%s' instead. This will be removed in a future release.",
                DEPRECATED_DB_VAR,
                CANONICAL_DB_VAR,
            )
        return db_url

    return None


def _infer_scripts_mode_from_context() -> bool:
    """Best-effort detection based on __main__ metadata and argv."""

    main_module = getattr(sys.modules.get("__main__"), "__name__", "")
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    if spec and spec.name:
        main_module = spec.name

    for prefix in SCRIPT_MODULE_PREFIXES:
        if main_module.startswith(prefix):
            return True

    if sys.argv:
        script_path = sys.argv[0].replace("\\", "/").lower()
        for prefix in SCRIPT_MODULE_PREFIXES:
            normalized = prefix.rstrip(".").replace(".", "/")
            if f"/{normalized}" in script_path:
                return True
        if "/scripts/" in script_path:
            return True

    return False


def _resolve_execution_mode() -> ExecutionMode:
    """Resolve execution mode using env override first, then heuristics."""

    explicit = os.environ.get("DRAGONFLY_EXECUTION_MODE", "").strip().lower()
    if explicit == "script":
        return "script"
    if explicit == "runtime":
        return "runtime"

    return "script" if _infer_scripts_mode_from_context() else "runtime"


def _reset_execution_mode_cache() -> None:
    """Reset cached execution mode (used by tests)."""

    global _EXECUTION_MODE
    _EXECUTION_MODE = None


def get_execution_mode() -> ExecutionMode:
    """Return cached execution mode for deterministic policy evaluation."""

    global _EXECUTION_MODE
    if _EXECUTION_MODE is None:
        _EXECUTION_MODE = _resolve_execution_mode()
    return _EXECUTION_MODE


@dataclass
class ConfigValidationResult:
    """Result of configuration validation."""

    passed: bool
    fatal_errors: list[str]
    warnings: list[str]
    missing_vars: list[str]


class ConfigurationSecurityViolation(SystemExit):
    """Raised when a critical security misconfiguration is detected."""

    def __init__(self, message: str):
        super().__init__(1)
        self.message = message


# =============================================================================
# EXECUTION MODE DETECTION
# =============================================================================


def is_scripts_mode() -> bool:
    """
    Determine if we're running in scripts mode (CLI tools, migrations).

    Scripts mode is detected by:
    1. DRAGONFLY_EXECUTION_MODE env var set to "script"
    2. __main__ module starts with tools., etl., tests., or scripts.
    3. sys.argv[0] contains known script paths

    In scripts mode, SUPABASE_MIGRATE_DB_URL is ALLOWED.

    Returns:
        True if running as a script/CLI tool, False for runtime services
    """
    return get_execution_mode() == "script"


def is_runtime_mode() -> bool:
    """
    Determine if we're running in runtime mode (API servers, workers).

    Runtime mode is the default. In runtime mode:
    - SUPABASE_MIGRATE_DB_URL is FORBIDDEN
    - Port 5432 is FORBIDDEN in production
    - sslmode=require is REQUIRED in production

    Returns:
        True if running as a runtime service, False for scripts
    """
    return get_execution_mode() == "runtime"


def _get_env() -> str:
    """Get the current environment name."""
    return os.environ.get(
        "DRAGONFLY_ENV",
        os.environ.get("ENVIRONMENT", os.environ.get("RAILWAY_ENVIRONMENT", "dev")),
    ).lower()


def _is_production() -> bool:
    """Check if running in production environment."""
    env = _get_env()
    return env in ("prod", "production")


def _parse_db_port(url: Optional[str]) -> Optional[int]:
    """Extract port from database URL."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        return parsed.port
    except Exception:
        return None


def _parse_db_host(url: Optional[str]) -> Optional[str]:
    """Extract hostname from database URL."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        return parsed.hostname
    except Exception:
        return None


def _is_pooler_host(hostname: Optional[str], port: Optional[int] = None) -> bool:
    """
    Check if hostname is a Supabase transaction pooler.

    Supabase pooler hostnames follow TWO patterns:
    1. Shared pooler:    *.pooler.supabase.com (e.g., aws-0-us-east-1.pooler.supabase.com)
    2. Dedicated pooler: db.<ref>.supabase.co:6543 (same host as direct, but port 6543)

    Direct connection (FORBIDDEN in runtime):
    - db.<project-ref>.supabase.co:5432 (bypasses pooler)

    Args:
        hostname: The database hostname
        port: The port number (required to distinguish dedicated pooler from direct)

    Returns:
        True if hostname+port indicates a pooler connection
    """
    if not hostname:
        return False
    hostname_lower = hostname.lower()

    # Shared pooler patterns
    if "pooler" in hostname_lower or hostname_lower.startswith("aws-"):
        return True

    # Dedicated pooler: db.<ref>.supabase.co with port 6543
    is_dedicated_host = hostname_lower.startswith("db.") and ".supabase.co" in hostname_lower
    if is_dedicated_host and port == 6543:
        return True

    return False


def _parse_db_sslmode(url: Optional[str]) -> Optional[str]:
    """Extract sslmode from database URL query string."""
    if not url:
        return None
    try:
        from urllib.parse import parse_qs

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        sslmode_list = params.get("sslmode", [])
        return sslmode_list[0] if sslmode_list else None
    except Exception:
        return None


def _enforce_prod_pooler_contract() -> None:
    """Exit immediately if production runtime DB URL violates pooler contract.

    Production DSN Contract (all REQUIRED):
    1. Host MUST contain '.pooler.supabase.com' (e.g., aws-0-us-east-1.pooler.supabase.com)
    2. Host MUST NOT be direct connection (db.*.supabase.co is FORBIDDEN)
    3. Port MUST be 6543 (transaction pooler)
    4. sslmode MUST be 'require' (explicit encryption)

    If ANY condition is violated, prints operator-friendly FATAL block and exits.

    SINGLE DSN CONTRACT: Uses DATABASE_URL (canonical) or SUPABASE_DB_URL (deprecated).
    """
    if not (_is_production() and is_runtime_mode()):
        return

    # Use Single DSN Contract helper
    db_url = _get_database_url_for_guard()

    if not db_url:
        return  # Missing URL handled elsewhere

    host = _parse_db_host(db_url) or ""
    port = _parse_db_port(db_url)
    sslmode = _parse_db_sslmode(db_url)
    host_lower = host.lower()

    violations: list[str] = []
    remediations: list[str] = []

    # Determine pooler type
    # Two valid pooler patterns when port=6543:
    #   1. Shared pooler:    *.pooler.supabase.com:6543
    #   2. Dedicated pooler: db.<ref>.supabase.co:6543
    #
    # Direct connection (FORBIDDEN):
    #   - db.<ref>.supabase.co:5432 (bypasses pooler)
    is_shared_pooler = ".pooler.supabase.com" in host_lower
    is_dedicated_pooler_host = host_lower.startswith("db.") and ".supabase.co" in host_lower

    # CHECK 0: Direct connection detection (db.*.supabase.co with port 5432)
    # This is FORBIDDEN - direct connections bypass the pooler
    is_direct_connection = is_dedicated_pooler_host and port == 5432
    if is_direct_connection:
        violations.append(
            f"host='{host}:5432' is DIRECT connection (bypasses pooler, FORBIDDEN in prod)"
        )
        remediations.append(
            "CRITICAL: Port 5432 is direct connection. "
            "Use port 6543 for dedicated pooler, or use *.pooler.supabase.com."
        )

    # CHECK 1: Host must be a valid pooler pattern
    # Dedicated pooler (db.*.supabase.co) is ONLY valid when port=6543
    is_dedicated_pooler = is_dedicated_pooler_host and port == 6543
    is_valid_pooler_host = is_shared_pooler or is_dedicated_pooler

    if not is_valid_pooler_host and not is_direct_connection:
        if is_dedicated_pooler_host and port != 6543:
            violations.append(
                f"host='{host}' with port={port} is invalid. "
                "Dedicated pooler requires port 6543."
            )
            remediations.append(
                "Change port to 6543 for dedicated pooler, or use shared pooler: "
                "*.pooler.supabase.com:6543"
            )
        elif not is_dedicated_pooler_host:
            violations.append(f"host='{host or 'missing'}' is not a valid Supabase pooler")
            remediations.append(
                "Use Supabase Dashboard → Settings → Database → Connection string → "
                "'Transaction Pooler' mode. Valid patterns: "
                "*.pooler.supabase.com:6543 (shared) or db.<ref>.supabase.co:6543 (dedicated)"
            )

    # CHECK 2: Port must be 6543
    if port != 6543:
        violations.append(f"port={port or 'missing'} (expected 6543)")
        remediations.append(f"Change port from 5432 to 6543 in {CANONICAL_DB_VAR}")

    # CHECK 3: sslmode must be explicitly 'require'
    if sslmode is None or sslmode.lower() != "require":
        violations.append(f"sslmode='{sslmode or 'missing'}' (expected 'require')")
        remediations.append(f"Append ?sslmode=require to {CANONICAL_DB_VAR}")

    if violations:
        # Print operator-friendly FATAL block
        border = "═" * 70
        print(f"\n{RED}{BOLD}{border}", file=sys.stderr)
        print("  ⛔ FATAL: PRODUCTION DSN CONTRACT VIOLATION", file=sys.stderr)
        print(f"{border}{RESET}\n", file=sys.stderr)

        print(
            f"{RED}{CANONICAL_DB_VAR} does not meet production requirements.{RESET}\n",
            file=sys.stderr,
        )
        print(
            f"{RED}Required: *.pooler.supabase.com:6543 OR db.<ref>.supabase.co:6543 with sslmode=require{RESET}\n",
            file=sys.stderr,
        )

        print(f"{YELLOW}Violations:{RESET}", file=sys.stderr)
        for v in violations:
            print(f"  • {v}", file=sys.stderr)

        print(f"\n{YELLOW}How to fix:{RESET}", file=sys.stderr)
        for r in remediations:
            print(f"  → {r}", file=sys.stderr)

        print(f"\n{YELLOW}Railway Clickpath:{RESET}", file=sys.stderr)
        print("  1. Supabase Dashboard → Settings → Database", file=sys.stderr)
        print(
            "  2. Copy 'Transaction' mode connection string (NOT Session/Direct)", file=sys.stderr
        )
        print(f"  3. Railway Dashboard → Service → Variables → {CANONICAL_DB_VAR}", file=sys.stderr)
        print("  4. Paste new DSN, ensure port=6543 & sslmode=require", file=sys.stderr)
        print("  5. Redeploy", file=sys.stderr)

        print(f"\n{RED}{BOLD}APPLICATION STARTUP BLOCKED{RESET}\n", file=sys.stderr)

        logger.critical(
            f"Production DSN contract violation: {', '.join(violations)}",
            extra={"violations": violations, "host": host, "port": port, "sslmode": sslmode},
        )
        sys.exit(1)


def _log_banner(title: str, color: str = RED) -> None:
    """Print a prominent banner for visibility in logs."""
    border = "=" * 70
    print(f"\n{color}{BOLD}{border}", file=sys.stderr)
    print(f"  {title}", file=sys.stderr)
    print(f"{border}{RESET}\n", file=sys.stderr)


# =============================================================================
# AUTH FAILURE CLASSIFICATION
# =============================================================================


def classify_db_error(error_message: str) -> str:
    """
    Classify a database error as 'auth', 'network', or 'unknown'.

    Auth failures should exit immediately (no retry) to prevent lockouts.
    Network failures should use exponential backoff with jitter.

    Args:
        error_message: The error message string from psycopg or connection

    Returns:
        'auth' - Authentication failure (exit fast, no retry)
        'network' - Network/transient failure (retry with backoff)
        'unknown' - Unknown error type
    """
    error_lower = error_message.lower()

    # Check for auth failures first (exit fast)
    for pattern in AUTH_FAILURE_PATTERNS:
        if pattern.lower() in error_lower:
            return "auth"

    # Check for network failures (retry with backoff)
    for pattern in NETWORK_FAILURE_PATTERNS:
        if pattern.lower() in error_lower:
            return "network"

    return "unknown"


def is_auth_failure(error_message: str) -> bool:
    """
    Check if an error message indicates an authentication failure.

    Auth failures include:
    - password authentication failed
    - role X does not exist
    - database X does not exist
    - server_login_retry (Supabase-specific lockout indicator)
    - too many connections

    These should trigger immediate exit, NOT retry, to avoid lockouts.

    Args:
        error_message: The error message string

    Returns:
        True if this is an auth failure that should not be retried
    """
    return classify_db_error(error_message) == "auth"


def is_network_failure(error_message: str) -> bool:
    """
    Check if an error message indicates a network/transient failure.

    Network failures include:
    - could not connect
    - connection refused
    - connection timed out
    - network is unreachable

    These should use exponential backoff with jitter.

    Args:
        error_message: The error message string

    Returns:
        True if this is a network failure that can be retried
    """
    return classify_db_error(error_message) == "network"


def check_forbidden_vars() -> tuple[bool, Optional[str]]:
    """
    Check 1: Forbidden Variables (Anti-Footgun)

    SUPABASE_MIGRATE_DB_URL must NEVER be present in RUNTIME environments.
    This URL provides direct database access (port 5432) which bypasses
    the connection pooler and can exhaust database connections.

    IMPORTANT: This check is SKIPPED in scripts mode (tools.*, etl.*, etc.)
    because scripts legitimately need the migration URL.

    Returns:
        Tuple of (passed, error_message)
    """
    # POLICY: SUPABASE_MIGRATE_DB_URL is ALLOWED in scripts mode
    if is_scripts_mode():
        migrate_url = os.environ.get("SUPABASE_MIGRATE_DB_URL")
        if migrate_url:
            logger.debug("SUPABASE_MIGRATE_DB_URL present in scripts mode (allowed)")
        return True, None

    # POLICY: SUPABASE_MIGRATE_DB_URL is FORBIDDEN in runtime mode
    migrate_url = os.environ.get("SUPABASE_MIGRATE_DB_URL")
    if migrate_url:
        return False, (
            "⛔ FATAL: SUPABASE_MIGRATE_DB_URL detected in runtime environment!\n"
            "\n"
            "This URL provides direct database access (port 5432) which:\n"
            "  - Bypasses the connection pooler\n"
            "  - Can exhaust DB connection limit (max 60 connections)\n"
            "  - May trigger server_login_retry lockouts\n"
            "\n"
            "IMMEDIATE ACTION REQUIRED:\n"
            "  1. Go to Railway Dashboard → Your Service → Variables\n"
            "  2. DELETE the SUPABASE_MIGRATE_DB_URL variable\n"
            "  3. Redeploy the service\n"
            "\n"
            f"Runtime services must ONLY use {CANONICAL_DB_VAR} (port 6543).\n"
            "Migration URLs are for CI/CD pipelines, not runtime services."
        )

    return True, None


def check_pooler_enforcement() -> tuple[bool, Optional[str], bool]:
    """
    Check 2: Pooler Enforcement

    Runtime database connections MUST use the Transaction Pooler (port 6543)
    instead of direct connections (port 5432) in production.

    Returns:
        Tuple of (passed, message, is_fatal)
    """
    # Use Single DSN Contract helper
    db_url = _get_database_url_for_guard()
    is_prod = _is_production()

    if not db_url:
        # No DB URL - will be caught by critical vars check
        return True, None, False

    port = _parse_db_port(db_url)

    if port == 6543:
        return True, None, False  # Correct port

    is_runtime_prod = is_runtime_mode() and is_prod

    if port is None:
        if is_runtime_prod:
            return (
                False,
                "⛔ CRITICAL: Unable to determine database port. Production runtime must explicitly use port 6543.",
                True,
            )
        return True, None, False

    if is_runtime_prod and port != 6543:
        return (
            False,
            (
                "⛔ CRITICAL: Production runtime is not using the Supabase pooler (port 6543).\n"
                f"\nCurrent port: {port}\n"
                "Required port: 6543 (transaction pooler)\n"
                "\nDirect connections bypass the pooler and can exhaust the database connection limit.\n"
                f"Update {CANONICAL_DB_VAR} to use the pooler and redeploy."
            ),
            True,
        )

    if port != 6543:
        # Non-prod warning
        return (
            False,
            (
                "⚠️  Runtime is not connected to the transaction pooler (port 6543).\n"
                f"Current port: {port}. Consider switching to 6543 for parity."
            ),
            False,
        )

    return True, None, False


def check_sslmode() -> tuple[bool, Optional[str]]:
    """
    Check 3: SSL Mode Verification

    Ensure sslmode is configured for secure database connections.
    In production, missing sslmode is a warning (Supabase defaults to require).

    Returns:
        Tuple of (passed, warning_message)
    """
    # Use Single DSN Contract helper
    db_url = _get_database_url_for_guard()

    if not db_url:
        return True, None

    sslmode = _parse_db_sslmode(db_url)

    if sslmode:
        # sslmode is set - good
        if sslmode in ("require", "verify-ca", "verify-full"):
            return True, None
        elif sslmode == "disable":
            return False, (
                "⚠️  SSL is DISABLED for database connection!\n"
                "\n"
                "sslmode=disable is insecure for production.\n"
                "Consider using sslmode=require or stronger."
            )
        else:
            return True, f"Using sslmode={sslmode}"

    # sslmode not explicitly set
    if _is_production():
        return False, (
            f"⚠️  sslmode not explicitly set in {CANONICAL_DB_VAR}.\n"
            "\n"
            "Supabase defaults to sslmode=require, but explicit is better.\n"
            "Consider adding ?sslmode=require to your connection string."
        )

    return True, None


def _is_api_process() -> bool:
    """Detect if running as API server (resilient) vs worker (strict)."""
    # Explicit env var takes precedence
    role = os.environ.get("DRAGONFLY_PROCESS_ROLE", "").lower()
    if role == "api":
        return True
    if role in ("worker", "ingest", "enforcement"):
        return False

    # Heuristics based on how the process was started
    import sys as _sys

    script = _sys.argv[0] if _sys.argv else ""
    # Workers have specific patterns in their invocation
    worker_patterns = ("worker", "celery", "rq", "dramatiq", "ingest", "watcher")
    if any(p in script.lower() for p in worker_patterns):
        return False

    # Default to API (resilient) - better to stay alive than crash
    return True


def validate_db_config() -> None:
    """
    Validate database configuration at startup.

    INDESTRUCTIBLE BOOT: For API processes, this function logs errors but DOES NOT
    exit. The API will boot in degraded mode and serve /health and /whoami while
    /readyz returns 503.

    For workers, configuration errors are still fatal (they can't do useful work
    without a database).

    This function performs strict validation of DATABASE_URL:
    - FATAL (workers) / WARN (API) if SUPABASE_MIGRATE_DB_URL is present
    - FATAL (workers) / WARN (API) if port is 5432 in production (must use 6543)
    - Warns if sslmode is not explicitly set

    SINGLE DSN CONTRACT: Uses DATABASE_URL (canonical) or SUPABASE_DB_URL (deprecated).

    Call this BEFORE db.start() in your application entrypoint.

    For workers:
        Raises SystemExit if fatal configuration issues are detected.

    For API:
        Logs errors but returns normally to allow degraded boot.
    """
    is_prod = _is_production()
    env = _get_env()
    is_api = _is_api_process()

    # Use Single DSN Contract helper
    db_url = _get_database_url_for_guard()

    # CHECK 1: SUPABASE_MIGRATE_DB_URL must NEVER be present (any env)
    migrate_url = os.environ.get("SUPABASE_MIGRATE_DB_URL")
    if migrate_url:
        _log_banner("FATAL: MIGRATION URL IN RUNTIME", RED)
        print(
            f"{RED}⛔ SUPABASE_MIGRATE_DB_URL is set in runtime environment.{RESET}\n"
            f"{RED}This leaks direct database credentials (port 5432) into the app tier.{RESET}\n"
            f"\n"
            f"{YELLOW}ACTION: Remove SUPABASE_MIGRATE_DB_URL from Railway service variables.{RESET}\n",
            file=sys.stderr,
        )
        logger.critical(
            "Migration database URL detected in runtime environment",
            extra={"environment": env, "is_api": is_api},
        )
        if not is_api:
            sys.exit(1)
        # API: Continue in degraded mode
        return

    if not db_url:
        if is_prod:
            _log_banner("DATABASE CONFIGURATION WARNING", YELLOW if is_api else RED)
            print(
                f"{YELLOW if is_api else RED}{CANONICAL_DB_VAR} is not set.{RESET}\n",
                file=sys.stderr,
            )
            if is_api:
                print(
                    f"{YELLOW}API will start in DEGRADED MODE. /readyz will return 503.{RESET}\n",
                    file=sys.stderr,
                )
                logger.warning(
                    f"{CANONICAL_DB_VAR} not set - API starting in degraded mode",
                    extra={"environment": env},
                )
                return  # API: Allow degraded boot
            else:
                print(f"{RED}Worker cannot start without database.{RESET}\n", file=sys.stderr)
                sys.exit(1)
        else:
            logger.warning(f"{CANONICAL_DB_VAR} not set (acceptable in dev)")
            return

    # CHECK 2: Port must be 6543 (pooler) in production
    port = _parse_db_port(db_url)
    if port == 5432 and is_prod:
        _log_banner("WRONG DATABASE PORT", YELLOW if is_api else RED)
        print(
            f"{YELLOW if is_api else RED}⛔ Production Runtime is using Direct Connection (5432).{RESET}\n"
            f"{YELLOW if is_api else RED}   Must use Pooler (6543).{RESET}\n"
            f"\n"
            f"{YELLOW}FIX: Update {CANONICAL_DB_VAR} to use port 6543 and redeploy.{RESET}\n",
            file=sys.stderr,
        )
        logger.critical(
            "Production using direct DB port 5432 instead of pooler 6543",
            extra={"port": port, "environment": env, "is_api": is_api},
        )
        if not is_api:
            sys.exit(1)
        # API: Continue in degraded mode (connection will likely fail anyway)

    # CHECK 3: sslmode (warning only)
    sslmode = _parse_db_sslmode(db_url)
    if not sslmode:
        if is_prod:
            logger.warning(
                f"sslmode not explicitly set in {CANONICAL_DB_VAR}. "
                "Add '?sslmode=require' to enforce encrypted connections."
            )
        # Not fatal - Supabase defaults to require

    # SUCCESS: Print verification message
    if port == 6543:
        print(f"{GREEN}✅ Config Verified (Pooler: 6543){RESET}", file=sys.stderr)
        logger.info("Config Verified (Pooler: 6543)")
    elif port:
        logger.debug(f"DB config validated: port={port}, sslmode={sslmode or 'default'}")


def check_critical_vars() -> tuple[bool, list[str]]:
    """
    Check 3: Critical Variables

    Ensure all required environment variables are present for production.

    Returns:
        Tuple of (passed, list_of_missing_vars)
    """
    # Required in production
    critical_vars = [
        "SUPABASE_SERVICE_ROLE_KEY",
        "DRAGONFLY_API_KEY",
    ]

    # These are required for observability but not fatal if missing
    observability_vars = [
        "RAILWAY_GIT_COMMIT_SHA",
    ]

    missing_critical = []
    missing_observability = []

    for var in critical_vars:
        if not os.environ.get(var):
            missing_critical.append(var)

    for var in observability_vars:
        if not os.environ.get(var):
            missing_observability.append(var)

    # In production, critical vars are fatal
    if _is_production() and missing_critical:
        return False, missing_critical

    # Log observability warnings but don't fail
    if missing_observability:
        logger.warning(
            f"Missing observability vars (non-fatal): {', '.join(missing_observability)}"
        )

    return True, missing_critical


def validate_production_config() -> ConfigValidationResult:
    """
    Validate production configuration at startup.

    This function MUST be called at the very top of all entrypoints,
    BEFORE importing any other application modules.

    Exits with code 1 if critical security violations are detected.

    Returns:
        ConfigValidationResult with validation details

    Raises:
        SystemExit: If fatal security violations are detected in production
    """
    env = _get_env()
    is_prod = _is_production()

    # Immediate production enforcement (single-line operator signal)
    _enforce_prod_pooler_contract()

    result = ConfigValidationResult(
        passed=True,
        fatal_errors=[],
        warnings=[],
        missing_vars=[],
    )

    # =========================================================================
    # CHECK 1: Forbidden Variables (FATAL in production)
    # =========================================================================
    passed, error = check_forbidden_vars()
    if not passed and error:
        result.passed = False
        result.fatal_errors.append(error)

    # =========================================================================
    # CHECK 2: Pooler Enforcement (FATAL in production, WARNING in dev)
    # =========================================================================
    passed, message, is_fatal = check_pooler_enforcement()
    if not passed and message:
        if is_fatal:
            result.passed = False
            result.fatal_errors.append(message)
        else:
            result.warnings.append(message)

    # =========================================================================
    # CHECK 3: SSL Mode (WARNING only)
    # =========================================================================
    passed, ssl_warning = check_sslmode()
    if not passed and ssl_warning:
        result.warnings.append(ssl_warning)

    # =========================================================================
    # CHECK 4: Critical Variables (FATAL in production)
    # =========================================================================
    passed, missing = check_critical_vars()
    if not passed:
        result.passed = False
        result.missing_vars = missing
        result.fatal_errors.append(f"Missing critical environment variables: {', '.join(missing)}")

    # =========================================================================
    # OUTPUT RESULTS
    # =========================================================================

    # Print warnings (non-fatal)
    for warning in result.warnings:
        _log_banner("CONFIGURATION WARNING", YELLOW)
        print(f"{YELLOW}{warning}{RESET}\n", file=sys.stderr)

    # Print fatal errors and exit
    if result.fatal_errors:
        _log_banner("CONFIGURATION SECURITY VIOLATION", RED)
        for error in result.fatal_errors:
            print(f"{RED}{error}{RESET}\n", file=sys.stderr)

        if is_prod:
            print(
                f"{RED}{BOLD}APPLICATION STARTUP BLOCKED{RESET}\n",
                file=sys.stderr,
            )
            print(
                f"{RED}Environment: {env.upper()}{RESET}\n",
                file=sys.stderr,
            )
            print(
                f"{RED}Fix the above issues and redeploy.{RESET}\n",
                file=sys.stderr,
            )
            # Log to structured logging as well
            logger.critical(
                "Configuration security violation - startup blocked",
                extra={
                    "errors": result.fatal_errors,
                    "environment": env,
                },
            )
            raise ConfigurationSecurityViolation(result.fatal_errors[0])
        else:
            # In dev, warn but don't crash
            print(
                f"{YELLOW}[DEV MODE] Would block in production. Continuing...{RESET}\n",
                file=sys.stderr,
            )

    # Success message - prominent for operator visibility
    if result.passed:
        # Use Single DSN Contract helper
        db_url = _get_database_url_for_guard()
        host = _parse_db_host(db_url)
        port = _parse_db_port(db_url)
        sslmode = _parse_db_sslmode(db_url)
        is_pooler = ".pooler.supabase.com" in (host or "").lower()

        # Operator-visible log line (grep for this in Railway)
        print(
            f"{GREEN}[CONFIG_GUARD] ✅ DB URL validated: pooler={is_pooler}, port={port}, ssl={sslmode}{RESET}",
            file=sys.stderr,
        )
        logger.info(
            f"Configuration validated OK (env={env}, pooler={is_pooler}, port={port}, ssl={sslmode})"
        )

    return result


def require_pooler_connection() -> None:
    """
    Strict check that REQUIRES pooler connection (port 6543).

    Use this for workers that absolutely must use the pooler.
    Raises SystemExit if not using pooler in production.

    SINGLE DSN CONTRACT: Uses DATABASE_URL (canonical) or SUPABASE_DB_URL (deprecated).
    """
    if not _is_production():
        return

    # Use Single DSN Contract helper
    db_url = _get_database_url_for_guard()
    port = _parse_db_port(db_url)

    if port and port != 6543:
        _log_banner("POOLER CONNECTION REQUIRED", RED)
        print(
            f"{RED}This worker requires connection pooler (port 6543).{RESET}\n",
            f"{RED}Current port: {port}{RESET}\n",
            file=sys.stderr,
        )
        sys.exit(1)


def validate_runtime_config() -> None:
    """
    STRICT Runtime Configuration Guard for Production.

    This function enforces Phase 0/Phase 1 containment rules:
    1. Pooler Enforcement: Port MUST be 6543 in production (FATAL if 5432)
    2. SSL Enforcement: sslmode=require MUST be present (FATAL if missing)
    3. Migration Credential Leak: SUPABASE_MIGRATE_DB_URL must NOT exist (FATAL)

    IMPORTANT: This function is a NO-OP in scripts mode (tools.*, etl.*, etc.)
    because scripts may legitimately need different configuration.

    Call this at the TOP of your entrypoint, BEFORE db.start().

    Usage:
        # In backend/api/main.py or backend/workers/base.py
        from backend.core.config_guard import validate_runtime_config
        validate_runtime_config()

    Raises:
        SystemExit(1): If any invariant is violated in runtime mode
    """
    # POLICY: Skip strict runtime checks in scripts mode
    if is_scripts_mode():
        logger.debug("validate_runtime_config() skipped in scripts mode")
        return

    env = _get_env()
    is_prod = _is_production()
    # Use Single DSN Contract helper
    db_url = _get_database_url_for_guard()

    # =========================================================================
    # CHECK 1: Migration Credential Leak (FATAL in runtime mode)
    # =========================================================================
    migrate_url = os.environ.get("SUPABASE_MIGRATE_DB_URL")
    if migrate_url:
        logger.critical("[CRITICAL] Migration DSN leaked in Runtime!")
        _log_banner("CRITICAL: MIGRATION DSN LEAKED IN RUNTIME", RED)
        print(
            f"{RED}[CRITICAL] Migration DSN leaked in Runtime!{RESET}\n"
            f"\n"
            f"{RED}SUPABASE_MIGRATE_DB_URL must NEVER be present in runtime services.{RESET}\n"
            f"{RED}This exposes direct database credentials (port 5432) to the app tier.{RESET}\n"
            f"\n"
            f"{YELLOW}IMMEDIATE ACTION:{RESET}\n"
            f"{YELLOW}  1. Railway Dashboard → Service → Variables{RESET}\n"
            f"{YELLOW}  2. DELETE the SUPABASE_MIGRATE_DB_URL variable{RESET}\n"
            f"{YELLOW}  3. Redeploy{RESET}\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # =========================================================================
    # CHECK 2: Database URL Required
    # =========================================================================
    if not db_url:
        if is_prod:
            logger.critical(f"[CRITICAL] {CANONICAL_DB_VAR} is not set!")
            _log_banner("CRITICAL: DATABASE URL MISSING", RED)
            print(
                f"{RED}[CRITICAL] {CANONICAL_DB_VAR} is not set.{RESET}\n"
                f"{RED}Production services cannot start without a database connection.{RESET}\n",
                file=sys.stderr,
            )
            sys.exit(1)
        else:
            logger.warning(f"{CANONICAL_DB_VAR} not set (acceptable in dev)")
            return

    # =========================================================================
    # CHECK 3: Pooler Enforcement (FATAL if port 5432 or non-pooler host in prod)
    # =========================================================================
    port = _parse_db_port(db_url)
    hostname = _parse_db_host(db_url)
    # Pass port to _is_pooler_host to support dedicated pooler format (db.<ref>.supabase.co:6543)
    is_pooler = _is_pooler_host(hostname, port)

    if is_prod:
        # In production, BOTH conditions must be met:
        # 1. Port must be 6543
        # 2. Host must be a valid pooler:
        #    - Shared pooler: *.pooler.supabase.com
        #    - Dedicated pooler: db.<ref>.supabase.co:6543
        if port != 6543:
            logger.critical("[CRITICAL] Production runtime must use Supabase pooler port 6543.")
            _log_banner("CRITICAL: WRONG DATABASE PORT", RED)
            printable_port = port if port is not None else "unknown/default"
            print(
                f"{RED}⛔ FATAL: Prod using Direct Connection/Wrong Port. Must use Pooler (6543).{RESET}\n"
                f"\n"
                f"{RED}Current port: {printable_port}{RESET}\n"
                f"{RED}Required port: 6543 (transaction pooler){RESET}\n"
                f"\n"
                f"{RED}Direct connections bypass the pooler and can exhaust the{RESET}\n"
                f"{RED}database connection limit (max 60), causing cascading failures.{RESET}\n"
                f"\n"
                f"{YELLOW}IMMEDIATE ACTION:{RESET}\n"
                f"{YELLOW}  1. Railway Dashboard → Service → Variables{RESET}\n"
                f"{YELLOW}  2. Update SUPABASE_DB_URL to use port 6543{RESET}\n"
                f"{YELLOW}  3. Redeploy{RESET}\n",
                file=sys.stderr,
            )
            sys.exit(1)

        if not is_pooler:
            logger.critical("[CRITICAL] Production runtime must use Supabase pooler hostname.")
            _log_banner("CRITICAL: NOT USING POOLER HOST", RED)
            print(
                f"{RED}⛔ FATAL: Invalid pooler host for production.{RESET}\n"
                f"\n"
                f"{RED}Current host: {hostname or 'unknown'}{RESET}\n"
                f"{RED}Valid patterns:{RESET}\n"
                f"{RED}  - *.pooler.supabase.com:6543 (shared pooler){RESET}\n"
                f"{RED}  - db.<ref>.supabase.co:6543 (dedicated pooler){RESET}\n"
                f"\n"
                f"{YELLOW}IMMEDIATE ACTION:{RESET}\n"
                f"{YELLOW}  1. Supabase Dashboard → Settings → Database → Connection string{RESET}\n"
                f"{YELLOW}  2. Use the 'Transaction Pooler' string (port 6543){RESET}\n"
                f"{YELLOW}  3. Update SUPABASE_DB_URL in Railway and redeploy{RESET}\n",
                file=sys.stderr,
            )
            sys.exit(1)

    elif port != 6543:
        logger.warning(
            f"⚠️  Runtime using direct connection (port {port}) instead of pooler (6543). "
            "This may cause connection exhaustion under load."
        )

    # =========================================================================
    # CHECK 4: SSL Enforcement (FATAL if missing in prod)
    # =========================================================================
    sslmode = _parse_db_sslmode(db_url)
    normalized_ssl = sslmode.lower() if sslmode else None

    if is_prod and normalized_ssl != "require":
        logger.critical("[CRITICAL] Production runtime must set sslmode=require.")
        _log_banner("CRITICAL: SSL MODE INCORRECT", RED)
        printable = normalized_ssl or "missing"
        print(
            f"{RED}[CRITICAL] Production database connections must include sslmode=require.{RESET}\n"
            f"\n"
            f"{RED}Current sslmode: {printable}{RESET}\n"
            f"{RED}Required sslmode: require{RESET}\n"
            f"\n"
            f"{RED}Unencrypted or misconfigured connections expose credentials in transit.{RESET}\n"
            f"\n"
            f"{YELLOW}IMMEDIATE ACTION:{RESET}\n"
            f"{YELLOW}  1. Railway Dashboard → Service → Variables{RESET}\n"
            f"{YELLOW}  2. Append ?sslmode=require to SUPABASE_DB_URL{RESET}\n"
            f"{YELLOW}  3. Redeploy{RESET}\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # =========================================================================
    # SUCCESS: All checks passed
    # =========================================================================
    if port == 6543 and is_pooler:
        print(
            f"{GREEN}✅ Runtime Config Verified (Pooler: 6543, Host: pooler, SSL: {sslmode or 'default'}){RESET}",
            file=sys.stderr,
        )
        logger.info(
            f"Runtime Config Verified (Pooler: 6543, Host: {hostname}, SSL: {sslmode or 'default'})"
        )
    elif port == 6543:
        print(
            f"{GREEN}✅ Runtime Config Verified (Pooler: 6543, SSL: {sslmode or 'default'}){RESET}",
            file=sys.stderr,
        )
        logger.info(f"Runtime Config Verified (Pooler: 6543, SSL: {sslmode or 'default'})")
    else:
        logger.info(
            f"Runtime config OK: port={port}, host={hostname}, sslmode={sslmode or 'default'}, env={env}"
        )


# Auto-validate if this module is run directly
if __name__ == "__main__":
    # Configure basic logging for standalone run
    logging.basicConfig(level=logging.DEBUG)

    print("Running configuration validation...\n")

    result = validate_production_config()

    print("\n" + "=" * 50)
    print("VALIDATION RESULT")
    print("=" * 50)
    print(f"Environment: {_get_env()}")
    print(f"Production: {_is_production()}")
    print(f"Passed: {result.passed}")
    print(f"Fatal Errors: {len(result.fatal_errors)}")
    print(f"Warnings: {len(result.warnings)}")
    print(f"Missing Vars: {result.missing_vars}")

    if result.passed:
        print(f"\n{GREEN}✅ Configuration is valid{RESET}")
    else:
        print(f"\n{RED}❌ Configuration has issues{RESET}")
        sys.exit(1)
