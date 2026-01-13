#!/usr/bin/env python3
"""Validate production SUPABASE_DB_URL contract."""
from __future__ import annotations

import os
import sys
from urllib.parse import parse_qs, urlparse


def _fatal(message: str) -> None:
    """Print a single-line operator friendly error and exit."""
    print(f"[VALIDATE_PROD_DSN] FATAL: {message}")
    sys.exit(1)


def _validate_supabase_dsn(url: str) -> None:
    """Validate that the provided Supabase DSN satisfies production constraints."""
    if not url:
        raise ValueError("SUPABASE_DB_URL is not set")

    parsed = urlparse(url)

    username = parsed.username or ""
    host = parsed.hostname or ""
    port = parsed.port
    query = parse_qs(parsed.query)
    sslmode = (query.get("sslmode") or [None])[0]

    violations: list[str] = []

    if "pooler.supabase.com" not in host.lower():
        violations.append("host must include pooler.supabase.com")

    if port != 6543:
        violations.append("port must be 6543")

    if sslmode != "require":
        violations.append("sslmode must be require")

    if not (username.startswith("postgres.") and len(username.split(".", 1)[-1]) > 0):
        violations.append("username must be postgres.<project_ref>")

    if violations:
        raise ValueError("; ".join(violations))


def main() -> int:
    url = os.environ.get("SUPABASE_DB_URL", "").strip()

    try:
        _validate_supabase_dsn(url)
    except ValueError as exc:
        _fatal(str(exc))

    print("[VALIDATE_PROD_DSN] OK: pooler contract satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
