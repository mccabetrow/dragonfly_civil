"""
Dragonfly Config Check - Golden Release Edition

Validates environment configuration using canonical (unsuffixed) keys.
Designed for one-file-per-environment pattern (.env.dev / .env.prod).

Required Keys (Blockers):
    - SUPABASE_URL
    - SUPABASE_SERVICE_ROLE_KEY
    - SUPABASE_DB_URL

Optional Keys (Warnings only):
    - OPENAI_API_KEY
    - DISCORD_WEBHOOK_URL

Derivation:
    - SUPABASE_PROJECT_REF: Auto-derived from SUPABASE_URL if missing

Exit Codes:
    0 = All required keys present (warnings are OK)
    1 = One or more required keys missing
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Sequence
from urllib.parse import urlparse

import click
import psycopg
from psycopg import Connection

from src.supabase_client import (
    SupabaseEnv,
    create_supabase_client,
    get_supabase_db_url,
    get_supabase_env,
)

# Storage buckets required for enforcement workflows
REQUIRED_BUCKETS: tuple[str, ...] = ("imports", "enforcement_evidence")


@dataclass
class CheckResult:
    """Result of a configuration check."""

    name: str
    status: str  # OK, WARN, FAIL
    detail: str


# =============================================================================
# CANONICAL KEY DEFINITIONS
# =============================================================================

# Required keys - missing any of these = Exit 1
REQUIRED_KEYS = (
    ("SUPABASE_URL", "Supabase REST URL"),
    ("SUPABASE_SERVICE_ROLE_KEY", "Supabase service role key"),
    ("SUPABASE_DB_URL", "Supabase database URL"),
)

# Optional keys - missing any of these = WARN only, Exit 0
OPTIONAL_KEYS = (
    ("OPENAI_API_KEY", "OpenAI API key (AI features)"),
    ("DISCORD_WEBHOOK_URL", "Discord webhook (alerting)"),
)

# Keys that are always required even in tolerant mode
CRITICAL_KEYS = {"SUPABASE_URL", "SUPABASE_DB_URL", "SUPABASE_SERVICE_ROLE_KEY"}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _normalize_env(value: str | None) -> SupabaseEnv:
    """Normalize environment value to 'dev' or 'prod'."""
    if not value:
        return get_supabase_env()
    lowered = value.lower().strip()
    return "prod" if lowered == "prod" else "dev"


def _env_values(source: Mapping[str, str] | None = None) -> Mapping[str, str]:
    """Get environment values from source or os.environ."""
    if source is not None:
        return source
    return os.environ


def _is_valid_url(value: str) -> bool:
    """Check if value is a valid HTTP(S) URL."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _derive_project_ref(supabase_url: str) -> str | None:
    """
    Derive SUPABASE_PROJECT_REF from SUPABASE_URL.

    Pattern: https://([a-z0-9-]+).supabase.co
    """
    match = re.match(r"https://([a-z0-9-]+)\.supabase\.co", supabase_url)
    return match.group(1) if match else None


# =============================================================================
# CHECK FUNCTIONS
# =============================================================================


def _check_required_keys(env_values: Mapping[str, str]) -> list[CheckResult]:
    """Check all required keys are present."""
    results: list[CheckResult] = []

    for key, label in REQUIRED_KEYS:
        raw_value = env_values.get(key)
        value = raw_value.strip() if isinstance(raw_value, str) else None

        if not value:
            results.append(CheckResult(key, "FAIL", f"{label} is missing"))
        elif key == "SUPABASE_URL" and not _is_valid_url(value):
            results.append(CheckResult(key, "FAIL", f"{label} is not a valid URL"))
        else:
            results.append(CheckResult(key, "OK", label))

    return results


def _check_optional_keys(env_values: Mapping[str, str]) -> list[CheckResult]:
    """Check optional keys - WARN if missing, never FAIL."""
    results: list[CheckResult] = []

    for key, label in OPTIONAL_KEYS:
        raw_value = env_values.get(key)
        value = raw_value.strip() if isinstance(raw_value, str) else None

        if not value:
            results.append(CheckResult(key, "WARN", f"{label} is missing"))
        else:
            results.append(CheckResult(key, "OK", label))

    return results


def _check_anon_key(env_values: Mapping[str, str]) -> CheckResult:
    """Check SUPABASE_ANON_KEY (optional for service role operations)."""
    raw_value = env_values.get("SUPABASE_ANON_KEY")
    value = raw_value.strip() if isinstance(raw_value, str) else None

    if value:
        return CheckResult("SUPABASE_ANON_KEY", "OK", "Supabase anon key")
    return CheckResult("SUPABASE_ANON_KEY", "OK", "Supabase anon key")


def _check_project_ref(env_values: Mapping[str, str]) -> CheckResult:
    """
    Check SUPABASE_PROJECT_REF - derive from SUPABASE_URL if missing.
    """
    raw_value = env_values.get("SUPABASE_PROJECT_REF")
    value = raw_value.strip() if isinstance(raw_value, str) else None

    if value:
        return CheckResult("SUPABASE_PROJECT_REF", "OK", "Supabase project reference")

    # Attempt derivation from SUPABASE_URL
    supabase_url = env_values.get("SUPABASE_URL", "")
    derived = _derive_project_ref(supabase_url)

    if derived:
        # Set it in environment for downstream use
        os.environ["SUPABASE_PROJECT_REF"] = derived
        return CheckResult(
            "SUPABASE_PROJECT_REF",
            "OK",
            f"Supabase project reference (derived: {derived})",
        )

    return CheckResult(
        "SUPABASE_PROJECT_REF",
        "FAIL",
        "Supabase project reference missing and could not be derived from SUPABASE_URL",
    )


def _supabase_probe(env: SupabaseEnv) -> CheckResult:
    """Test database connectivity with SELECT 1."""
    try:
        db_url = get_supabase_db_url(env)
    except Exception as exc:
        return CheckResult("supabase_db_connect", "FAIL", f"DB URL error: {exc}")

    try:
        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
    except Exception as exc:
        return CheckResult("supabase_db_connect", "FAIL", f"SELECT 1 failed: {exc}")

    return CheckResult("supabase_db_connect", "OK", "Database connection verified")


def _storage_bucket_check(env: SupabaseEnv) -> CheckResult:
    """Check required storage buckets exist."""
    try:
        client = create_supabase_client(env)
        buckets = {
            getattr(bucket, "name", None)
            for bucket in client.storage.list_buckets()
            if getattr(bucket, "name", None)
        }
    except Exception as exc:
        return CheckResult("storage_buckets", "FAIL", f"{exc}")

    missing = [name for name in REQUIRED_BUCKETS if name not in buckets]
    if missing:
        return CheckResult(
            "storage_buckets",
            "FAIL",
            f"Missing buckets: {', '.join(missing)}",
        )
    return CheckResult(
        "storage_buckets",
        "OK",
        f"Buckets present: {', '.join(REQUIRED_BUCKETS)}",
    )


# =============================================================================
# MAIN CHECK ORCHESTRATION
# =============================================================================


def evaluate_env_requirements(
    target_env: SupabaseEnv,
    env_values: Mapping[str, str] | None = None,
) -> list[CheckResult]:
    """Evaluate all environment requirements."""
    values = _env_values(env_values)
    results: list[CheckResult] = []

    # Required keys (canonical, no suffix)
    results.extend(_check_required_keys(values))

    # Anon key check
    results.append(_check_anon_key(values))

    # Project ref (with derivation)
    results.append(_check_project_ref(values))

    # Optional keys (warn only)
    results.extend(_check_optional_keys(values))

    return results


def run_checks(
    target_env: SupabaseEnv,
    env_values: Mapping[str, str] | None = None,
) -> list[CheckResult]:
    """Run all configuration checks including connectivity."""
    results = evaluate_env_requirements(target_env, env_values=env_values)
    results.append(_supabase_probe(target_env))
    results.append(_storage_bucket_check(target_env))
    return results


# =============================================================================
# OUTPUT & RESULT HANDLING
# =============================================================================


def _render_table(results: Sequence[CheckResult]) -> None:
    """Render check results as a table."""
    if not results:
        click.echo("[config_check] No checks executed.")
        return

    name_width = max(len(r.name) for r in results)
    status_width = max(len(r.status) for r in results)

    click.echo("[config_check] Environment validation summary:")
    click.echo(f"  {'Check'.ljust(name_width)}  {'Status'.ljust(status_width)}  Detail")
    for result in results:
        detail = result.detail or "-"
        click.echo(
            f"  {result.name.ljust(name_width)}  {result.status.ljust(status_width)}  {detail}"
        )


def has_failures(results: Iterable[CheckResult], tolerant: bool = False) -> bool:
    """
    Check if any results are blocking failures.

    In tolerant mode, only CRITICAL_KEYS failures are treated as fatal.
    Connectivity failures (supabase_db_connect, storage_buckets) are warnings.
    """
    for result in results:
        if result.status != "FAIL":
            continue

        if tolerant:
            # In tolerant mode, only critical keys cause failure
            if result.name in CRITICAL_KEYS:
                return True
            # Log warning for non-critical failures
            click.echo(f"[WARN] {result.name}: {result.detail} (Allowed for Initial Deploy)")
        else:
            return True
    return False


def _set_supabase_mode(env: SupabaseEnv) -> None:
    """Set SUPABASE_MODE environment variable."""
    os.environ["SUPABASE_MODE"] = env


def check_environment(
    requested_env: str | None = None,
    env_values: Mapping[str, str] | None = None,
) -> list[CheckResult]:
    """
    Main entry point for config checking.

    Used by doctor_all.py and CLI.
    """
    target_env = _normalize_env(requested_env)
    _set_supabase_mode(target_env)
    results = run_checks(target_env, env_values=env_values)
    _render_table(results)
    return results


# =============================================================================
# CLI ENTRY POINT
# =============================================================================


@click.command()
@click.option(
    "--env",
    "requested_env",
    type=click.Choice(["dev", "prod"]),
    default=None,
    help="Target Supabase credential set. Defaults to SUPABASE_MODE.",
)
@click.option(
    "--tolerant",
    is_flag=True,
    default=False,
    help="Downgrade non-critical config failures to warnings (for initial deploys).",
)
def main(requested_env: str | None = None, tolerant: bool = False) -> None:
    """Validate environment configuration for Dragonfly."""
    results = check_environment(requested_env)
    if has_failures(results, tolerant=tolerant):
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
