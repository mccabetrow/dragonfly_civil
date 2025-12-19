from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence
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

REQUIRED_BUCKETS: tuple[str, ...] = ("imports", "enforcement_evidence")


@dataclass(frozen=True)
class EnvRequirement:
    base_name: str
    label: str
    kind: str  # "string" or "url"
    scoped: bool = True
    warn_on_missing_envs: tuple[SupabaseEnv, ...] = ()


@dataclass
class CheckResult:
    name: str
    status: str  # OK, WARN, FAIL
    detail: str


SCOPED_ENV_REQUIREMENTS: tuple[EnvRequirement, ...] = (
    EnvRequirement("SUPABASE_URL", "Supabase REST URL", "url"),
    EnvRequirement("SUPABASE_SERVICE_ROLE_KEY", "Supabase service role key", "string"),
    EnvRequirement("SUPABASE_ANON_KEY", "Supabase anon key", "string"),
    EnvRequirement("SUPABASE_PROJECT_REF", "Supabase project reference", "string"),
)

GLOBAL_ENV_REQUIREMENTS: tuple[EnvRequirement, ...] = (
    EnvRequirement(
        "OPENAI_API_KEY",
        "OpenAI API key",
        "string",
        scoped=False,
        warn_on_missing_envs=("dev",),
    ),
    EnvRequirement(
        "N8N_API_KEY",
        "n8n API key",
        "string",
        scoped=False,
        warn_on_missing_envs=("dev",),
    ),
)

FAILURE_STATUSES = {"FAIL"}


def _scoped_name(base: str, env: SupabaseEnv) -> str:
    return f"{base}_PROD" if env == "prod" else base


def _normalize_env(value: str | None) -> SupabaseEnv:
    if not value:
        return get_supabase_env()
    lowered = value.lower().strip()
    return "prod" if lowered == "prod" else "dev"


def _env_values(source: Mapping[str, str] | None = None) -> Mapping[str, str]:
    if source is not None:
        return source
    return os.environ


def _is_valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _check_requirement(
    var_name: str,
    requirement: EnvRequirement,
    env_values: Mapping[str, str],
    target_env: SupabaseEnv,
) -> CheckResult:
    raw_value = env_values.get(var_name)
    value = raw_value.strip() if isinstance(raw_value, str) else None
    if not value:
        status = "WARN" if target_env in requirement.warn_on_missing_envs else "FAIL"
        return CheckResult(var_name, status, f"{requirement.label} is missing")

    if requirement.kind == "url" and not _is_valid_url(value):
        return CheckResult(var_name, "FAIL", f"{requirement.label} is not a valid URL")

    return CheckResult(var_name, "OK", requirement.label)


def evaluate_env_requirements(
    target_env: SupabaseEnv,
    env_values: Mapping[str, str] | None = None,
) -> list[CheckResult]:
    values = _env_values(env_values)
    results: list[CheckResult] = []

    for requirement in SCOPED_ENV_REQUIREMENTS:
        scoped_name = _scoped_name(requirement.base_name, target_env)
        results.append(_check_requirement(scoped_name, requirement, values, target_env))

    results.append(_db_credential_result(target_env, values))

    for requirement in GLOBAL_ENV_REQUIREMENTS:
        name = (
            requirement.base_name
            if not requirement.scoped
            else _scoped_name(requirement.base_name, target_env)
        )
        results.append(_check_requirement(name, requirement, values, target_env))

    return results


def _db_credential_result(target_env: SupabaseEnv, env_values: Mapping[str, str]) -> CheckResult:
    """Check for canonical SUPABASE_DB_URL."""
    url_name = "SUPABASE_DB_URL"
    raw_value = env_values.get(url_name)
    value = raw_value.strip() if isinstance(raw_value, str) else None

    if value:
        return CheckResult(url_name, "OK", "Supabase database URL")

    return CheckResult(url_name, "FAIL", f"Missing SUPABASE_DB_URL (SUPABASE_MODE={target_env})")


def _supabase_probe(env: SupabaseEnv) -> CheckResult:
    try:
        db_url = get_supabase_db_url(env)
    except Exception as exc:  # pragma: no cover - error path validated via tests
        return CheckResult("supabase_db_url", "FAIL", f"{exc}")

    try:
        with psycopg.connect(db_url, connect_timeout=5) as conn:
            _execute_select_one(conn)
    except Exception as exc:  # pragma: no cover - exercised via tests
        return CheckResult("supabase_db_connect", "FAIL", f"SELECT 1 failed: {exc}")

    return CheckResult("supabase_db_connect", "OK", "SELECT 1 succeeded")


def _execute_select_one(conn: Connection[object] | Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1;")
        cur.fetchone()


def _storage_bucket_check(env: SupabaseEnv) -> CheckResult:
    try:
        client = create_supabase_client(env)
        buckets = {
            getattr(bucket, "name", None)
            for bucket in client.storage.list_buckets()
            if getattr(bucket, "name", None)
        }
    except Exception as exc:  # pragma: no cover - exercised via tests
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


def run_checks(
    target_env: SupabaseEnv,
    env_values: Mapping[str, str] | None = None,
) -> list[CheckResult]:
    results = evaluate_env_requirements(target_env, env_values=env_values)
    results.append(_supabase_probe(target_env))
    results.append(_storage_bucket_check(target_env))
    return results


def _render_table(results: Sequence[CheckResult]) -> None:
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


def _set_supabase_mode(env: SupabaseEnv) -> None:
    os.environ["SUPABASE_MODE"] = env


def has_failures(results: Iterable[CheckResult]) -> bool:
    return any(result.status in FAILURE_STATUSES for result in results)


def check_environment(
    requested_env: str | None = None,
    env_values: Mapping[str, str] | None = None,
) -> list[CheckResult]:
    target_env = _normalize_env(requested_env)
    _set_supabase_mode(target_env)
    results = run_checks(target_env, env_values=env_values)
    _render_table(results)
    return results


@click.command()
@click.option(
    "--env",
    "requested_env",
    type=click.Choice(["dev", "prod"]),
    default=None,
    help="Target Supabase credential set. Defaults to SUPABASE_MODE.",
)
def main(requested_env: str | None = None) -> None:
    results = check_environment(requested_env)
    if has_failures(results):
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
