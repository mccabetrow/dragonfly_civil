from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Literal, Tuple

import httpx
from postgrest.constants import DEFAULT_POSTGREST_CLIENT_TIMEOUT
from psycopg.conninfo import conninfo_to_dict

from supabase import Client, ClientOptions, create_client

from .core_config import Settings, get_settings

SupabaseClient = Any
SupabaseEnv = Literal["dev", "prod"]
_EnvInput = str | SupabaseEnv | None

logger = logging.getLogger(__name__)

_HTTPX_TIMEOUT = DEFAULT_POSTGREST_CLIENT_TIMEOUT


def _build_supabase_http_client() -> httpx.Client:
    """Return an httpx client configured for Supabase REST calls."""

    timeout = httpx.Timeout(_HTTPX_TIMEOUT)
    return httpx.Client(timeout=timeout)


def _client_options() -> ClientOptions:
    """Construct ClientOptions that avoid deprecated timeout/verify kwargs."""

    options = ClientOptions()
    options.httpx_client = _build_supabase_http_client()
    return options


def _normalize_mode(value: str | None) -> SupabaseEnv:
    if not value:
        return "dev"
    lowered = value.strip().lower()
    if lowered in {"prod", "production"}:
        return "prod"
    if lowered in {"dev", "demo", "development"}:
        return "dev"
    logger.warning("Unknown SUPABASE_MODE=%s; defaulting to dev credentials", value)
    return "dev"


def _coerce_supabase_env(value: _EnvInput) -> SupabaseEnv:
    if value is None:
        return get_supabase_env()
    if isinstance(value, str):
        return _normalize_mode(value)
    return value


def get_supabase_env() -> SupabaseEnv:
    settings = get_settings()
    return _normalize_mode(os.getenv("SUPABASE_MODE", settings.supabase_mode))


def get_supabase_credentials(env: _EnvInput = None) -> tuple[str, str]:
    """
    Get Supabase URL and service role key.

    Uses canonical SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.
    The env parameter is ignored (kept for backward compatibility).
    """
    settings = get_settings()
    url = (settings.SUPABASE_URL or "").strip()
    key = (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()

    missing = []
    if not url:
        missing.append("SUPABASE_URL")
    if not key:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")

    if missing:
        mode = get_supabase_env()
        raise RuntimeError(
            f"Missing required Supabase credential(s): {', '.join(missing)}\n"
            f"Current SUPABASE_MODE: {mode}\n"
            f"Set these in your environment or .env file."
        )
    return url, key


def _verify_service_role(jwt_token: str) -> None:
    try:
        segments = jwt_token.split(".")
        if len(segments) < 2:
            raise ValueError("missing JWT payload")
        payload_segment = segments[1]
        padding = "=" * (-len(payload_segment) % 4)
        decoded = base64.urlsafe_b64decode(payload_segment + padding)
        claims = json.loads(decoded)
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Invalid SUPABASE_SERVICE_ROLE_KEY JWT") from exc

    role = claims.get("role")
    if role != "service_role":
        raise RuntimeError(f"Service role key has unexpected role: {role}")


def create_supabase_client(env: _EnvInput = None) -> Client:
    supabase_env = _coerce_supabase_env(env)
    url, key = get_supabase_credentials(supabase_env)
    _verify_service_role(key)
    options = _client_options()
    client = create_client(url, key, options=options)
    setattr(client, "_dragonfly_env", supabase_env)
    setattr(client, "_dragonfly_schema_mutations", supabase_env != "prod")
    setattr(client, "_dragonfly_httpx_client", options.httpx_client)
    logger.info(
        "Initialized Supabase client for env='%s' (schema mutations %s)",
        supabase_env,
        "enabled" if supabase_env != "prod" else "disabled",
    )
    return client


def _strip(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip()
    return stripped or None


# =============================================================================
# SINGLE DSN CONTRACT: DATABASE_URL is the canonical variable
# =============================================================================

# Canonical variable name
_CANONICAL_DSN_VAR = "DATABASE_URL"

# Deprecated variable (maps to canonical with warning)
_DEPRECATED_DSN_VAR = "SUPABASE_DB_URL"


def get_supabase_db_url(env: _EnvInput = None) -> str:
    """
    Get the database URL using Single DSN Contract.

    CANONICAL VARIABLE: DATABASE_URL
    DEPRECATED (with warning): SUPABASE_DB_URL

    Priority:
        1. DATABASE_URL (canonical)
        2. SUPABASE_DB_URL (deprecated, emits warning)
        3. Settings fallback

    The env parameter is ignored (kept for backward compatibility).

    Returns:
        PostgreSQL connection string

    Raises:
        RuntimeError: If no database URL is configured
    """
    import warnings

    settings = get_settings()

    # Priority 1: Canonical DATABASE_URL
    db_url = _strip(os.getenv(_CANONICAL_DSN_VAR))
    if db_url:
        return db_url

    # Priority 2: Deprecated SUPABASE_DB_URL (with warning)
    db_url = _strip(os.getenv(_DEPRECATED_DSN_VAR))
    if db_url:
        msg = (
            f"Environment variable '{_DEPRECATED_DSN_VAR}' is DEPRECATED. "
            f"Use '{_CANONICAL_DSN_VAR}' instead. "
            "This will be removed in a future release."
        )
        warnings.warn(msg, DeprecationWarning, stacklevel=2)
        logger.warning(msg)
        return db_url

    # Priority 3: Settings fallback (may come from .env)
    if hasattr(settings, "SUPABASE_DB_URL") and settings.SUPABASE_DB_URL:
        db_url = _strip(settings.SUPABASE_DB_URL)
        if db_url:
            return db_url

    # Fail fast with clear error message
    mode = get_supabase_env()
    raise RuntimeError(
        f"Missing required environment variable: {_CANONICAL_DSN_VAR}\n\n"
        f"SINGLE DSN CONTRACT:\n"
        f"  Canonical variable: {_CANONICAL_DSN_VAR}\n"
        f"  Deprecated (still works): {_DEPRECATED_DSN_VAR}\n\n"
        f"Required for database connectivity:\n"
        f"  SUPABASE_URL              {'✓ set' if settings.SUPABASE_URL else '✗ MISSING'}\n"
        f"  SUPABASE_SERVICE_ROLE_KEY {'✓ set' if settings.SUPABASE_SERVICE_ROLE_KEY else '✗ MISSING'}\n"
        f"  {_CANONICAL_DSN_VAR:<23} ✗ MISSING\n\n"
        f"Current SUPABASE_MODE: {mode}\n\n"
        f"Set {_CANONICAL_DSN_VAR} in your environment or .env file:\n"
        f"  {_CANONICAL_DSN_VAR}=postgresql://user:pass@host:6543/postgres?sslmode=require"
    )


def describe_db_url(db_url: str) -> Tuple[str, str, str]:
    host = "unknown"
    dbname = "unknown"
    user = "unknown"
    try:
        parts = conninfo_to_dict(db_url)
        host_value = parts.get("host") or parts.get("hostaddr")
        if host_value:
            host = str(host_value)
        dbname_value = parts.get("dbname")
        if dbname_value:
            dbname = str(dbname_value)
        user_value = parts.get("user")
        if user_value:
            user = str(user_value)
    except Exception:  # pragma: no cover - defensive logging guard
        pass
    return host, dbname, user
