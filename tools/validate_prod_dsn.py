#!/usr/bin/env python3
"""
Validate production SUPABASE_DB_URL contract.

Production DSN Contract (ALL REQUIRED):
  1. Host MUST contain '.pooler.supabase.com' (or aws-*.pooler.supabase.com)
  2. Port MUST be 6543 (transaction pooler, NOT 5432 direct)
  3. sslmode MUST be 'require' (explicit encryption)

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
    4. Verify it looks like:
       postgresql://postgres.<ref>:<pass>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require
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
    1. Host MUST contain '.pooler.supabase.com' (or aws-*.pooler.supabase.com)
    2. Port MUST be 6543 (transaction pooler)
    3. sslmode MUST be 'require' (explicit encryption)

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

    # CHECK 1: Host must be pooler, not direct
    is_pooler_host = ".pooler.supabase.com" in host or (
        host.startswith("aws-") and ".pooler.supabase.com" in host
    )
    if "db." in host and ".supabase.co" in host:
        violations.append(
            f"Host '{parsed.hostname}' is a DIRECT connection (db.*.supabase.co). "
            "Use the Transaction Pooler: aws-*.pooler.supabase.com"
        )
    elif not is_pooler_host:
        violations.append(
            f"Host '{parsed.hostname or 'missing'}' must contain '.pooler.supabase.com'. "
            "Use Supabase Dashboard → Settings → Database → Transaction mode"
        )

    # CHECK 2: Port must be 6543 (transaction pooler)
    if port == 5432:
        violations.append(
            "Port 5432 is a DIRECT connection port. " "Transaction Pooler requires port 6543"
        )
    elif port != 6543:
        violations.append(f"Port {port or 'missing'} is invalid. Must be 6543 (Transaction Pooler)")

    # CHECK 3: sslmode must be explicitly 'require'
    if sslmode is None:
        violations.append("sslmode is missing. Append '?sslmode=require' to the connection string")
    elif sslmode.lower() != "require":
        violations.append(f"sslmode='{sslmode}' is invalid. Must be sslmode=require for production")

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
