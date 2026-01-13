#!/usr/bin/env python3
"""
Validate production SUPABASE_DB_URL contract.

Usage:
    python -m tools.validate_prod_dsn                    # reads from SUPABASE_DB_URL env
    python -m tools.validate_prod_dsn "postgresql://..." # reads from CLI arg
    echo "postgresql://..." | python -m tools.validate_prod_dsn --stdin
"""
from __future__ import annotations

import os
import sys
from urllib.parse import parse_qs, urlparse


def _fatal(message: str) -> None:
    """Print a single-line operator friendly error and exit."""
    print(f"❌ INVALID: {message}")
    sys.exit(1)


def validate_supabase_dsn(url: str) -> list[str]:
    """
    Validate that the provided Supabase DSN satisfies production constraints.

    Returns list of violations (empty if valid).
    """
    if not url:
        return ["SUPABASE_DB_URL is not set or empty"]

    parsed = urlparse(url)

    username = parsed.username or ""
    host = parsed.hostname or ""
    port = parsed.port
    query = parse_qs(parsed.query)
    sslmode = (query.get("sslmode") or [None])[0]

    violations: list[str] = []

    # Host validation: must be pooler, not direct
    if "db." in host.lower():
        violations.append(f"Host '{host}' is DIRECT connection (db.*). Use pooler.supabase.com")
    elif "pooler.supabase.com" not in host.lower() and "aws-0" not in host.lower():
        violations.append(f"Host '{host}' must contain pooler.supabase.com or aws-0")

    # Port validation: must be 6543 (transaction pooler)
    if port == 5432:
        violations.append("Port 5432 is DIRECT connection. Use port 6543 (transaction pooler)")
    elif port != 6543:
        violations.append(f"Port {port} is invalid. Must be 6543 (transaction pooler)")

    # SSL validation: must be sslmode=require
    if sslmode != "require":
        violations.append(f"sslmode='{sslmode}' is invalid. Must be sslmode=require")

    # Username validation (optional but recommended)
    if username and not (username.startswith("postgres.") and len(username.split(".", 1)[-1]) > 0):
        violations.append(f"Username '{username}' should be postgres.<project_ref>")

    return violations


def main() -> int:
    """Entry point supporting env var, CLI arg, or stdin input."""
    url: str = ""

    # Priority: CLI arg > stdin flag > env var
    if len(sys.argv) > 1:
        if sys.argv[1] == "--stdin":
            url = sys.stdin.read().strip()
        elif sys.argv[1] == "--help" or sys.argv[1] == "-h":
            print(__doc__)
            return 0
        else:
            url = sys.argv[1]
    else:
        url = os.environ.get("SUPABASE_DB_URL", "").strip()

    if not url:
        print("Usage: python -m tools.validate_prod_dsn <dsn>")
        print("       python -m tools.validate_prod_dsn  # reads SUPABASE_DB_URL env")
        print("       echo '<dsn>' | python -m tools.validate_prod_dsn --stdin")
        return 1

    violations = validate_supabase_dsn(url)

    if violations:
        for v in violations:
            print(f"❌ INVALID: {v}")
        return 1

    print("✅ VALID TRANSACTION POOLER DSN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
