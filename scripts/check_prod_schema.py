"""Validate prod Supabase schema exactly matches the frozen snapshot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.supabase_client import describe_db_url, get_supabase_db_url
from tools.schema_guard import (
    SCHEMA_FREEZE_PATH,
    SchemaDiff,
    diff_connection_against_freeze,
    format_drift,
    load_schema_freeze,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ensure prod schema matches the canonical freeze snapshot.",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="prod",
        help="Supabase credential set to validate (default: prod)",
    )
    parser.add_argument(
        "--tolerant",
        action="store_true",
        help="Downgrade schema drift from FAIL to WARN (for initial deploys)",
    )
    return parser.parse_args(argv)


def _format_hash(hash_value: str | None) -> str:
    if not hash_value:
        return "n/a"
    return f"{hash_value[:12]}..."


def _print_drift(drift: SchemaDiff, *, tolerant: bool = False) -> None:
    label = "WARN" if tolerant else "FAIL"
    for message in format_drift(drift):
        print(f"[{label}] {message}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    env = args.env
    tolerant = args.tolerant

    try:
        db_url = get_supabase_db_url(env)
    except RuntimeError as exc:
        print(f"Missing configuration for {env}: {exc}")
        return 1

    try:
        freeze_data = load_schema_freeze(SCHEMA_FREEZE_PATH)
    except FileNotFoundError:
        if tolerant:
            print(
                f"[WARN] schema freeze missing at {SCHEMA_FREEZE_PATH} (Allowed for Initial Deploy)"
            )
            return 0
        print(f"[FAIL] schema freeze missing at {SCHEMA_FREEZE_PATH}")
        return 1
    except ValueError as exc:
        print(f"[FAIL] schema freeze invalid: {exc}")
        return 1

    hash_raw = freeze_data.get("hash") if isinstance(freeze_data, dict) else None
    hash_value = hash_raw if isinstance(hash_raw, str) else None

    print(f"[INFO] Validating {env} schema against freeze {_format_hash(hash_value)}")

    host, dbname, user = describe_db_url(db_url)
    print(f"[INFO] Connecting to {host}/{dbname} as {user}")

    try:
        with psycopg.connect(db_url, connect_timeout=5) as conn:
            drift = diff_connection_against_freeze(
                conn,
                freeze_data=freeze_data,
                freeze_path=SCHEMA_FREEZE_PATH,
            )
    except psycopg.Error as exc:
        print(f"[FAIL] Unable to compare schema: {exc}")
        return 1

    if drift.is_clean():
        print(f"[OK] {env} schema matches {_format_hash(hash_value)}")
        return 0

    _print_drift(drift, tolerant=tolerant)

    if tolerant:
        print(f"[WARN] {env} schema deviates from frozen snapshot (Allowed for Initial Deploy)")
        return 0

    print(f"[FAIL] {env} schema deviates from the frozen snapshot")
    return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
