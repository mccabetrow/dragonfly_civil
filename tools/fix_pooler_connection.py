#!/usr/bin/env python3
"""
tools/fix_pooler_connection.py - Circuit Breaker Bypass for Pooler Failures

Diagnoses Supabase connection pooler issues and provides direct connection
bypass strings when the pooler (port 6543) is unreachable.

Usage:
    python -m tools.fix_pooler_connection
    python -m tools.fix_pooler_connection --env prod
    python -m tools.fix_pooler_connection --timeout 5

Failure Mode: Pooler Unreachable / Circuit Breaker Open
Resolution: Bypass pooler using direct connection (port 5432)
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Environment Setup
# ---------------------------------------------------------------------------


def get_env(env: str) -> dict[str, str]:
    """Load environment variables for the specified environment."""
    os.environ.setdefault("SUPABASE_MODE", env)

    from src.supabase_client import get_supabase_db_url, get_supabase_env

    actual_env = get_supabase_env()
    db_url = get_supabase_db_url()

    return {
        "env": actual_env,
        "db_url": db_url,
    }


def parse_db_url(db_url: str) -> dict[str, str]:
    """Parse database URL into components."""
    parsed = urlparse(db_url)
    return {
        "host": parsed.hostname or "",
        "port": parsed.port or 5432,
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
        "database": parsed.path.lstrip("/") or "postgres",
    }


def test_connection(host: str, port: int, timeout: float = 5.0) -> tuple[bool, float, str]:
    """
    Test TCP connection to host:port.

    Returns:
        (success, latency_ms, error_message)
    """
    start = time.perf_counter()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.close()
        latency = (time.perf_counter() - start) * 1000
        return True, latency, ""
    except socket.timeout:
        return False, timeout * 1000, "Connection timed out"
    except socket.error as e:
        return False, (time.perf_counter() - start) * 1000, str(e)


def build_connection_string(components: dict[str, str], port: int) -> str:
    """Build a PostgreSQL connection string with specified port."""
    # Build connection URL from components
    user = components["user"]
    password = components["password"]
    host = components["host"]
    database = components["database"]
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def mask_password(url: str) -> str:
    """Mask password in URL for safe display."""
    parsed = urlparse(url)
    if parsed.password:
        masked = url.replace(parsed.password, "****")
        return masked
    return url


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose and bypass Supabase pooler connection issues"
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Target environment (default: dev)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Connection timeout in seconds (default: 5)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  CIRCUIT BREAKER BYPASS - Pooler Connection Diagnostics")
    print("=" * 70)
    print(f"\n  Environment: {args.env.upper()}")
    print(f"  Timeout: {args.timeout}s")
    print()

    # Get environment config
    try:
        config = get_env(args.env)
    except Exception as e:
        print(f"❌ Failed to load environment: {e}")
        return 1

    db_url = config["db_url"]
    components = parse_db_url(db_url)
    host = components["host"]

    # Extract project ref from host (e.g., db.xxxxx.supabase.co -> xxxxx)
    project_ref = host.replace("db.", "").replace(".supabase.co", "")

    print(f"  Project: {project_ref}")
    print(f"  Host: {host}")
    print()

    # Test ports
    ports_to_test = [
        (6543, "Transaction Pooler (pgbouncer)"),
        (5432, "Direct Connection (postgres)"),
    ]

    results = {}
    print("─" * 70)
    print("  CONNECTION TESTS")
    print("─" * 70)

    for port, description in ports_to_test:
        success, latency, error = test_connection(host, port, args.timeout)
        results[port] = (success, latency, error)

        if success:
            print(f"  ✅ Port {port} ({description})")
            print(f"     Latency: {latency:.1f}ms")
        else:
            print(f"  ❌ Port {port} ({description})")
            print(f"     Error: {error}")
        print()

    # Analysis and recommendations
    print("─" * 70)
    print("  DIAGNOSIS")
    print("─" * 70)

    pooler_ok = results[6543][0]
    direct_ok = results[5432][0]

    if pooler_ok and direct_ok:
        print("  ✅ Both connections healthy - No action needed")
        print()
        print("  Recommendation: Use Transaction Pooler (6543) for production")
        print("  - Better connection management")
        print("  - Handles connection limits gracefully")
        return 0

    elif not pooler_ok and direct_ok:
        print("  ⚠️  POOLER UNREACHABLE / CIRCUIT BREAKER OPEN")
        print()
        print("  The Supabase connection pooler is not responding.")
        print("  This typically happens during:")
        print("    - Supabase infrastructure maintenance")
        print("    - Connection pool exhaustion")
        print("    - Network routing issues")
        print()
        print("─" * 70)
        print("  AUTO-FIX: Direct Connection Bypass")
        print("─" * 70)
        print()

        direct_url = build_connection_string(components, 5432)

        print("  Copy this connection string to bypass the pooler:")
        print()
        print(f"  {direct_url}")
        print()
        print("  Set in your environment:")
        print(f"    SUPABASE_DB_URL={mask_password(direct_url)}")
        print()
        print("  ⚠️  Note: Direct connections bypass pooling.")
        print("     - Max connections limited (~60 for Supabase)")
        print("     - Revert to pooler (6543) once issue resolves")
        return 1

    elif pooler_ok and not direct_ok:
        print("  ⚠️  DIRECT CONNECTION BLOCKED")
        print()
        print("  The direct Postgres port (5432) is unreachable.")
        print("  This may indicate:")
        print("    - Network firewall blocking direct connections")
        print("    - Supabase project in restricted mode")
        print()
        print("  Use Transaction Pooler (6543) which is healthy.")
        return 1

    else:
        print("  ❌ ALL CONNECTIONS FAILED")
        print()
        print("  Neither pooler nor direct connections are working.")
        print("  Possible causes:")
        print("    - Supabase project paused or deleted")
        print("    - Network/DNS issues")
        print("    - Invalid credentials")
        print()
        print("  Action Required:")
        print("    1. Check Supabase Dashboard for project status")
        print("    2. Verify .env credentials are correct")
        print("    3. Test network connectivity: ping {host}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
