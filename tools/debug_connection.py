#!/usr/bin/env python3
"""
DSN Detective - Brute-force test DSN username variations to find the working one.

This script tests different username formats against the Supabase pooler to identify
which combination works. Useful for diagnosing "Tenant or user not found" errors.

Usage:
    python -m tools.debug_connection --password "YOUR_PASSWORD"
    python -m tools.debug_connection --password "YOUR_PASSWORD" --project-ref iaketsyhmqbwaabgykux

The script will try these username variations:
    1. postgres (Standard direct connection)
    2. postgres.{project_ref} (Shared Pooler - Transaction mode)
    3. dragonfly_app.{project_ref} (App Role via shared pooler)

For each variation, it attempts a TCP connect followed by SELECT 1.
"""

import argparse
import os
import sys
import socket
from urllib.parse import quote_plus, urlparse, urlunparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_tcp_connect(host: str, port: int, timeout: float = 5.0) -> tuple[bool, str]:
    """Test raw TCP connectivity to host:port."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True, "TCP connection successful"
    except socket.timeout:
        return False, f"TCP timeout after {timeout}s"
    except socket.error as e:
        return False, f"TCP error: {e}"


def test_postgres_auth(dsn: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Test PostgreSQL authentication with the given DSN."""
    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=int(timeout)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()
                if result and result[0] == 1:
                    return True, "SELECT 1 succeeded - AUTH OK"
                return False, "SELECT 1 returned unexpected result"
    except Exception as e:
        error_str = str(e).lower()

        # Classify the error
        if "password authentication failed" in error_str:
            return False, "AUTH FAIL: Wrong password"
        elif "role" in error_str and "does not exist" in error_str:
            return False, f"AUTH FAIL: Role/user not found - {str(e)[:100]}"
        elif "tenant or user not found" in error_str:
            return False, "AUTH FAIL: Tenant or user not found (pooler issue)"
        elif "server_login_retry" in error_str:
            return False, "LOCKOUT: server_login_retry - wait 15+ minutes"
        elif "connection refused" in error_str:
            return False, f"NETWORK: Connection refused - {str(e)[:100]}"
        elif "timeout" in error_str:
            return False, f"TIMEOUT: {str(e)[:100]}"
        else:
            return False, f"ERROR: {type(e).__name__}: {str(e)[:200]}"


def build_dsn(
    user: str,
    password: str,
    host: str,
    port: int,
    database: str = "postgres",
    sslmode: str = "require",
) -> str:
    """Build a PostgreSQL DSN with proper URL encoding."""
    # URL-encode the password (handles special chars like @, +, %, etc.)
    encoded_password = quote_plus(password)
    return f"postgresql://{user}:{encoded_password}@{host}:{port}/{database}?sslmode={sslmode}"


def redact_dsn(dsn: str) -> str:
    """Redact password from DSN for safe logging."""
    parsed = urlparse(dsn)
    if parsed.password:
        redacted = dsn.replace(f":{parsed.password}@", ":***@")
        return redacted
    return dsn


def main():
    parser = argparse.ArgumentParser(
        description="DSN Detective - Find the working Supabase connection string"
    )
    parser.add_argument(
        "--password",
        required=True,
        help="Database password (will be URL-encoded automatically)",
    )
    parser.add_argument(
        "--project-ref",
        default="iaketsyhmqbwaabgykux",
        help="Supabase project reference ID (default: production)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Custom host (default: aws-0-us-east-1.pooler.supabase.com for pooler)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=6543,
        help="Database port (6543=pooler, 5432=direct)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Connection timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--include-direct",
        action="store_true",
        help="Also test direct connection (port 5432)",
    )
    args = parser.parse_args()

    project_ref = args.project_ref
    password = args.password
    port = args.port
    timeout = args.timeout

    # Determine hosts to test
    pooler_host = args.host or f"aws-0-us-east-1.pooler.supabase.com"
    direct_host = f"db.{project_ref}.supabase.co"

    # Username variations to test
    username_variations = [
        ("postgres", "Standard PostgreSQL user"),
        (f"postgres.{project_ref}", "Shared Pooler (Transaction mode)"),
        (f"dragonfly_app.{project_ref}", "App Role via Shared Pooler"),
    ]

    print("=" * 72)
    print("  🔍 DSN DETECTIVE - Finding Your Working Connection String")
    print("=" * 72)
    print(f"  Project Ref:    {project_ref}")
    print(f"  Pooler Host:    {pooler_host}:{port}")
    if args.include_direct:
        print(f"  Direct Host:    {direct_host}:5432")
    print(f"  Timeout:        {timeout}s")
    print("=" * 72)
    print()

    # Test TCP connectivity first
    print("📡 Testing TCP Connectivity...")
    print("-" * 50)

    tcp_ok, tcp_msg = test_tcp_connect(pooler_host, port, timeout=5.0)
    status = "✅" if tcp_ok else "❌"
    print(f"  {status} {pooler_host}:{port} - {tcp_msg}")

    if args.include_direct:
        tcp_ok_direct, tcp_msg_direct = test_tcp_connect(direct_host, 5432, timeout=5.0)
        status = "✅" if tcp_ok_direct else "❌"
        print(f"  {status} {direct_host}:5432 - {tcp_msg_direct}")

    print()

    # Track results
    working_dsns = []
    failed_dsns = []

    # Test each username variation against the pooler
    print("🔐 Testing Username Variations (Pooler)...")
    print("-" * 50)

    for username, description in username_variations:
        dsn = build_dsn(username, password, pooler_host, port)
        redacted = redact_dsn(dsn)

        print(f"\n  Testing: {username}")
        print(f"  Desc:    {description}")
        print(f"  DSN:     {redacted}")

        auth_ok, auth_msg = test_postgres_auth(dsn, timeout=timeout)
        status = "✅" if auth_ok else "❌"
        print(f"  Result:  {status} {auth_msg}")

        if auth_ok:
            working_dsns.append((username, pooler_host, port, description))
        else:
            failed_dsns.append((username, pooler_host, port, auth_msg))

    # Optionally test direct connection
    if args.include_direct:
        print("\n🔐 Testing Direct Connection (Port 5432)...")
        print("-" * 50)

        # Direct connection uses simple 'postgres' username
        dsn = build_dsn("postgres", password, direct_host, 5432)
        redacted = redact_dsn(dsn)

        print(f"\n  Testing: postgres (Direct)")
        print(f"  DSN:     {redacted}")

        auth_ok, auth_msg = test_postgres_auth(dsn, timeout=timeout)
        status = "✅" if auth_ok else "❌"
        print(f"  Result:  {status} {auth_msg}")

        if auth_ok:
            working_dsns.append(("postgres", direct_host, 5432, "Direct Connection"))

    # Summary
    print()
    print("=" * 72)
    print("  📋 SUMMARY")
    print("=" * 72)

    if working_dsns:
        print()
        print("  ✅ WORKING CONFIGURATIONS:")
        print()
        for username, host, port, desc in working_dsns:
            dsn = build_dsn(username, password, host, port)
            redacted = redact_dsn(dsn)
            print(f"    • {desc}")
            print(f"      Username: {username}")
            print(f"      Host:     {host}:{port}")
            print()
            print(f"      📋 COPY THIS DSN (with your password):")
            print(f"      {redacted.replace('***', '<YOUR_PASSWORD>')}")
            print()
    else:
        print()
        print("  ❌ NO WORKING CONFIGURATIONS FOUND")
        print()
        print("  Possible causes:")
        print("    1. Wrong password - verify in Supabase Dashboard → Settings → Database")
        print("    2. Project paused - check Supabase Dashboard")
        print("    3. IP restrictions - check if your IP is allowed")
        print("    4. Pooler lockout - wait 15+ minutes if you see server_login_retry")
        print()
        print("  Failed attempts:")
        for username, host, port, error in failed_dsns:
            print(f"    • {username}@{host}:{port}")
            print(f"      Error: {error}")
        print()
        return 1

    print("=" * 72)
    print()

    # Print the recommended DATABASE_URL for Railway
    if working_dsns:
        best = working_dsns[0]
        username, host, port, _ = best

        print("🚀 RECOMMENDED ACTION:")
        print()
        print("  Set this in Railway (replace <PASSWORD> with your actual password):")
        print()
        print(
            f'    railway variables set DATABASE_URL="postgresql://{username}:<PASSWORD>@{host}:{port}/postgres?sslmode=require"'
        )
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
