#!/usr/bin/env python3
"""
Validate production SUPABASE_DB_URL contract.

Production DSN Contract (ALL REQUIRED):
  1. Port MUST be 6543 (transaction pooler)
  2. sslmode MUST be 'require' (explicit encryption)
  3. Host MUST be one of:
     - *.pooler.supabase.com (shared pooler)
     - db.<ref>.supabase.co:6543 (dedicated pooler)

Usage:
    python -m tools.validate_prod_dsn                    # reads from SUPABASE_DB_URL env
    python -m tools.validate_prod_dsn "postgresql://..." # reads from CLI arg
    echo "postgresql://..." | python -m tools.validate_prod_dsn --stdin

Exit codes:
    0 = DSN is valid for production
    1 = DSN violates one or more contract requirements

How to get the correct DSN:
    1. Supabase Dashboard → Settings → Database → Connection string
    2. Select "Transaction" mode (NOT Session, NOT Direct)
    3. Copy the connection string
    4. Verify it matches one of these patterns:
       Shared:    postgresql://postgres.<ref>:<pass>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require
       Dedicated: postgresql://postgres:<pass>@db.<ref>.supabase.co:6543/postgres?sslmode=require
    5. Paste into Railway → Service → Variables → SUPABASE_DB_URL
"""
from __future__ import annotations

import os
import sys
from urllib.parse import parse_qs, urlparse

# ANSI colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def validate_supabase_dsn(url: str) -> list[str]:
    """
    Validate that the provided Supabase DSN satisfies production constraints.

    Production DSN Contract:
    1. Port MUST be 6543 (transaction pooler)
    2. sslmode MUST be 'require' (explicit encryption)
    3. Host MUST be one of:
       - *.pooler.supabase.com (shared pooler)
       - db.<ref>.supabase.co:6543 (dedicated pooler)

    Returns list of violations (empty if valid).
    """
    if not url:
        return ["SUPABASE_DB_URL is not set or empty"]

    try:
        parsed = urlparse(url)
    except Exception as e:
        return [f"Failed to parse URL: {e}"]

    host = (parsed.hostname or "").lower()
    port = parsed.port
    query = parse_qs(parsed.query)
    sslmode = (query.get("sslmode") or [None])[0]

    violations: list[str] = []

    # CHECK 1: Port must be 6543 (transaction pooler)
    if port == 5432:
        violations.append(
            "Port 5432 is a DIRECT connection port. " "Transaction Pooler requires port 6543"
        )
    elif port != 6543:
        violations.append(f"Port {port or 'missing'} is invalid. Must be 6543 (Transaction Pooler)")

    # CHECK 2: sslmode must be explicitly 'require'
    if sslmode is None:
        violations.append("sslmode is missing. Append '?sslmode=require' to the connection string")
    elif sslmode.lower() != "require":
        violations.append(f"sslmode='{sslmode}' is invalid. Must be sslmode=require for production")

    # CHECK 3: Host must be a valid pooler host
    # Two valid patterns:
    #   1. Shared pooler:    *.pooler.supabase.com
    #   2. Dedicated pooler: db.<ref>.supabase.co (ONLY when port=6543)
    is_shared_pooler = ".pooler.supabase.com" in host
    is_dedicated_pooler_host = host.startswith("db.") and ".supabase.co" in host
    is_dedicated_pooler = is_dedicated_pooler_host and port == 6543
    is_direct_connection = is_dedicated_pooler_host and port == 5432

    if is_direct_connection:
        violations.append(
            f"Host '{parsed.hostname}:5432' is a DIRECT connection. "
            "Direct connections bypass the pooler. Use port 6543 for dedicated pooler."
        )
    elif not is_shared_pooler and not is_dedicated_pooler:
        if is_dedicated_pooler_host:
            violations.append(
                f"Host '{parsed.hostname}' with port {port} is invalid. "
                "Dedicated pooler requires port 6543."
            )
        else:
            violations.append(
                f"Host '{parsed.hostname or 'missing'}' is not a valid Supabase pooler. "
                "Expected: *.pooler.supabase.com OR db.<ref>.supabase.co:6543"
            )

    return violations


def print_runbook() -> None:
    """Print operator runbook for getting correct DSN."""
    print(f"\n{YELLOW}═══════════════════════════════════════════════════════════════════{RESET}")
    print(f"{YELLOW}  HOW TO GET THE CORRECT DSN{RESET}")
    print(f"{YELLOW}═══════════════════════════════════════════════════════════════════{RESET}")
    print()
    print("  1. Go to Supabase Dashboard → Settings → Database")
    print("  2. Scroll to 'Connection string'")
    print("  3. Click 'Transaction' mode (NOT Session, NOT Direct)")
    print("     • Transaction = Port 6543, connection pooling for API/workers")
    print("     • Session = Port 5432, for long-lived connections (NOT for API)")
    print("     • Direct = Port 5432, bypasses pooler (migrations only)")
    print()
    print("  4. Copy the URI and verify it matches this pattern:")
    print(
        f"     {GREEN}postgresql://postgres.<ref>:<pass>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require{RESET}"
    )
    print()
    print("  5. Paste into Railway → Service → Variables → SUPABASE_DB_URL")
    print("  6. Redeploy the service")
    print()


def main() -> int:
    """Entry point supporting env var, CLI arg, or stdin input."""
    url: str = ""
    show_runbook = False

    # Priority: CLI arg > stdin flag > env var
    args = sys.argv[1:]
    if "--runbook" in args:
        show_runbook = True
        args = [a for a in args if a != "--runbook"]

    if args:
        if args[0] == "--stdin":
            url = sys.stdin.read().strip()
        elif args[0] in ("--help", "-h"):
            print(__doc__)
            return 0
        else:
            url = args[0]
    else:
        url = os.environ.get("SUPABASE_DB_URL", "").strip()

    if not url:
        print(f"{YELLOW}Usage:{RESET}")
        print("  python -m tools.validate_prod_dsn <dsn>")
        print("  python -m tools.validate_prod_dsn              # reads SUPABASE_DB_URL env")
        print("  echo '<dsn>' | python -m tools.validate_prod_dsn --stdin")
        print("  python -m tools.validate_prod_dsn --runbook    # show how to get correct DSN")
        print()
        print(f"{YELLOW}Production DSN Contract:{RESET}")
        print("  • Host: *.pooler.supabase.com (aws-0-<region>.pooler.supabase.com)")
        print("  • Port: 6543 (Transaction Pooler)")
        print("  • SSL:  sslmode=require")
        return 1

    violations = validate_supabase_dsn(url)

    if violations:
        print(
            f"\n{RED}{BOLD}╔══════════════════════════════════════════════════════════════════╗{RESET}"
        )
        print(
            f"{RED}{BOLD}║  ⛔ DSN CONTRACT VIOLATION                                       ║{RESET}"
        )
        print(
            f"{RED}{BOLD}╚══════════════════════════════════════════════════════════════════╝{RESET}\n"
        )

        for v in violations:
            print(f"  {RED}✗{RESET} {v}")

        print_runbook()
        return 1

    print(f"\n{GREEN}✅ VALID TRANSACTION POOLER DSN{RESET}")
    print("   Host: *.pooler.supabase.com ✓")
    print("   Port: 6543 ✓")
    print("   SSL:  sslmode=require ✓")

    if show_runbook:
        print_runbook()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
