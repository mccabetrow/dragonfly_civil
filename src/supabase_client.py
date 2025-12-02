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

from .settings import Settings, get_settings

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
    supabase_env = _coerce_supabase_env(env)
    settings = get_settings()

    if supabase_env == "prod":
        url = (settings.SUPABASE_URL_PROD or "").strip()
        key = (settings.SUPABASE_SERVICE_ROLE_KEY_PROD or "").strip()
        missing = [
            name
            for name, value in {
                "SUPABASE_URL_PROD": url,
                "SUPABASE_SERVICE_ROLE_KEY_PROD": key,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Missing Supabase credential(s) for 'prod' environment: "
                + ", ".join(missing)
            )
        return url, key

    url = (settings.supabase_url or "").strip()
    key = (settings.supabase_service_role_key or "").strip()
    missing = [
        name
        for name, value in {
            "SUPABASE_URL": url,
            "SUPABASE_SERVICE_ROLE_KEY": key,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing Supabase credential(s) for 'dev' environment: "
            + ", ".join(missing)
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


def _project_ref_from_url(url: str | None) -> str:
    if not url:
        return ""
    url = url.strip()
    if not url:
        return ""
    prefix = "https://"
    if url.startswith(prefix):
        url = url[len(prefix) :]
    return url.split(".")[0]


def _strip(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip()
    return stripped or None


def _setting_value(settings: Settings, name: str) -> str | None:
    value = getattr(settings, name, None)
    return _strip(value) if isinstance(value, str) else None


def _resolve_project_ref(settings: Settings, suffix: str) -> str | None:
    explicit_ref = _strip(os.getenv(f"SUPABASE_PROJECT_REF{suffix}"))
    if explicit_ref:
        return explicit_ref
    url_attr = "SUPABASE_URL_PROD" if suffix == "_PROD" else "SUPABASE_URL"
    candidate_url = _strip(os.getenv(url_attr))
    if not candidate_url:
        settings_url = _setting_value(settings, url_attr)
        candidate_url = settings_url
    if candidate_url:
        return _project_ref_from_url(candidate_url)
    return None


def get_supabase_db_url(env: _EnvInput = None) -> str:
    supabase_env = _coerce_supabase_env(env)
    settings = get_settings()

    suffix = "_PROD" if supabase_env == "prod" else ""

    if supabase_env == "prod":
        direct_env = _strip(os.getenv("SUPABASE_DB_URL_DIRECT_PROD"))
        if not direct_env:
            direct_env = _setting_value(settings, "SUPABASE_DB_URL_DIRECT_PROD")
        if direct_env:
            return direct_env

    explicit_name = f"SUPABASE_DB_URL{suffix}"
    explicit = _strip(os.getenv(explicit_name))
    if not explicit and supabase_env == "prod":
        explicit = _setting_value(settings, "SUPABASE_DB_URL_PROD")
    if explicit:
        return explicit

    password_name = f"SUPABASE_DB_PASSWORD{suffix}"
    password = _strip(os.getenv(password_name))
    project_ref = _resolve_project_ref(settings, suffix)

    if not password or not project_ref:
        suffix_hint = suffix or ""
        raise RuntimeError(
            "Missing Supabase database configuration for {env}. Set SUPABASE_DB_URL{suffix} or "
            "SUPABASE_DB_PASSWORD{suffix} and SUPABASE_PROJECT_REF{suffix}/SUPABASE_URL{url_suffix}.".format(
                env=supabase_env,
                suffix=suffix_hint,
                url_suffix="_PROD" if supabase_env == "prod" else "",
            )
        )

    region_host = _strip(os.getenv("SUPABASE_DB_HOST"))
    if supabase_env == "prod":
        region_host = _strip(os.getenv("SUPABASE_DB_HOST_PROD")) or region_host

    if not region_host:
        region_host = "aws-1-us-east-2.pooler.supabase.com"

    return (
        "postgresql://postgres:{password}@"
        "{host}:5432/postgres"
        "?user=postgres.{project_ref}&sslmode=require"
    ).format(password=password, project_ref=project_ref, host=region_host)


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
