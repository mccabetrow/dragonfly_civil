#!/usr/bin/env python3
"""
tools/verify_pooler.py
======================
Transaction Pooler Connection Verification

Validates that the current DATABASE_URL connects through the Supabase
Transaction Pooler (port 6543) rather than direct connection (port 5432).

Usage:
    python -m tools.verify_pooler
    python -m tools.verify_pooler --dsn "postgresql://..."

Environment:
    DATABASE_URL: PostgreSQL connection string

Author: Principal Database Reliability Engineer
Date: 2026-01-18
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from urllib.parse import urlparse

# =============================================================================
# Constants
# =============================================================================

POOLER_PORT = 6543
DIRECT_PORT = 5432

# Expected pooler hostname pattern
POOLER_HOST_PATTERN = r"aws-\d+-.*\.pooler\.supabase\.com"

# =============================================================================
# Helpers
# =============================================================================


def redact_dsn(dsn: str) -> str:
    """Redact password from DSN for safe logging."""
    return re.sub(r"(://[^:]+:)([^@]+)(@)", r"\1****\3", dsn)


def parse_dsn(dsn: str) -> dict:
    """Parse DSN into components."""
    parsed = urlparse(dsn)
    return {
        "user": parsed.username,
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "database": parsed.path.lstrip("/").split("?")[0] if parsed.path else "postgres",
    }


# =============================================================================
# Main Verification
# =============================================================================


def verify_pooler_connection(dsn: str) -> dict:
    """
    Verify the DSN uses the Transaction Pooler.

    Returns:
        dict with keys: success, port, host, is_pooler, actual_port, message
    """
    import psycopg2

    result = {
        "success": False,
        "dsn_port": None,
        "dsn_host": None,
        "is_pooler_host": False,
        "connected_port": None,
        "message": "",
    }

    # Parse DSN
    try:
        components = parse_dsn(dsn)
        result["dsn_port"] = components["port"]
        result["dsn_host"] = components["host"]
        result["is_pooler_host"] = bool(re.match(POOLER_HOST_PATTERN, components["host"] or ""))
    except Exception as e:
        result["message"] = f"Failed to parse DSN: {e}"
        return result

    # Check port in DSN
    if components["port"] != POOLER_PORT:
        result["message"] = (
            f"DSN port is {components['port']}, expected {POOLER_PORT} for pooler. "
            f"This is a DIRECT connection, not pooled!"
        )
        # Don't return yet - still try to connect to get actual port

    # Try to connect and verify
    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
        cur = conn.cursor()

        # Get actual connected port
        cur.execute("SELECT inet_server_port();")
        row = cur.fetchone()
        actual_port = row[0] if row else None
        result["connected_port"] = actual_port

        # Get backend PID and info for diagnostics
        cur.execute("SELECT pg_backend_pid(), current_user, current_database();")
        pid_row = cur.fetchone()

        cur.close()
        conn.close()

        # Validate connected port
        if actual_port == POOLER_PORT:
            result["success"] = True
            result["message"] = (
                f"✅ Connected via Transaction Pooler (port {POOLER_PORT}). "
                f"Backend PID: {pid_row[0]}, User: {pid_row[1]}, DB: {pid_row[2]}"
            )
        elif actual_port == DIRECT_PORT:
            result["message"] = (
                f"⚠️ Connected via DIRECT connection (port {DIRECT_PORT}). "
                f"This bypasses connection pooling and may cause issues at scale. "
                f"Update DATABASE_URL to use port {POOLER_PORT}."
            )
        else:
            result["message"] = f"Connected on unexpected port: {actual_port}"

    except Exception as e:
        result["message"] = f"Connection failed: {e}"

    return result


def verify_pooler_username(dsn: str) -> dict:
    """
    Verify the DSN username includes the project ref for shared pooler.

    For Supabase Shared Pooler, username must be: postgres.PROJECT_REF
    """
    result = {
        "valid": False,
        "username": None,
        "has_project_ref": False,
        "message": "",
    }

    try:
        components = parse_dsn(dsn)
        username = components["user"]
        result["username"] = username

        if not username:
            result["message"] = "No username in DSN"
            return result

        # Check for project ref format: user.project_ref
        if "." in username:
            parts = username.split(".", 1)
            if len(parts) == 2 and len(parts[1]) >= 10:  # Project refs are ~20 chars
                result["has_project_ref"] = True
                result["valid"] = True
                result["message"] = f"✅ Username '{username}' includes project ref"
            else:
                result["message"] = f"Username '{username}' has dot but project ref looks invalid"
        else:
            result["message"] = (
                f"⚠️ Username '{username}' is missing project ref. "
                f"Shared Pooler requires format: {username}.YOUR_PROJECT_REF"
            )

    except Exception as e:
        result["message"] = f"Failed to parse username: {e}"

    return result


# =============================================================================
# CLI
# =============================================================================


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Verify Transaction Pooler connection")
    parser.add_argument(
        "--dsn",
        default=os.environ.get("DATABASE_URL", ""),
        help="DSN to verify (default: $DATABASE_URL)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )

    args = parser.parse_args()

    if not args.dsn:
        print("ERROR: No DSN provided. Set DATABASE_URL or use --dsn")
        return 2

    print()
    print("=" * 70)
    print("  DRAGONFLY POOLER VERIFICATION")
    print("=" * 70)
    print()
    print(f"DSN (redacted): {redact_dsn(args.dsn)}")
    print()

    # Check 1: Username format
    print("─" * 70)
    print("CHECK 1: Username Format (Shared Pooler Requirement)")
    print("─" * 70)
    username_result = verify_pooler_username(args.dsn)
    print(f"  Username: {username_result['username']}")
    print(f"  Has Project Ref: {username_result['has_project_ref']}")
    print(f"  Status: {username_result['message']}")
    print()

    # Check 2: Connection test
    print("─" * 70)
    print("CHECK 2: Connection Test")
    print("─" * 70)

    try:
        import psycopg2  # noqa: F401
    except ImportError:
        print("  ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
        return 2

    conn_result = verify_pooler_connection(args.dsn)
    print(f"  DSN Port: {conn_result['dsn_port']}")
    print(f"  DSN Host: {conn_result['dsn_host']}")
    print(f"  Is Pooler Host: {conn_result['is_pooler_host']}")
    print(f"  Connected Port: {conn_result['connected_port']}")
    print(f"  Status: {conn_result['message']}")
    print()

    # Summary
    print("=" * 70)

    all_pass = username_result["valid"] and conn_result["success"]

    if all_pass:
        print("  ✅ POOLER VERIFICATION PASSED")
        print("=" * 70)
        print()
        return 0
    else:
        print("  ❌ POOLER VERIFICATION FAILED")
        print("=" * 70)
        print()
        print("REMEDIATION:")

        if not username_result["valid"]:
            print("  1. Update DATABASE_URL username to include project ref:")
            print(f"     Current: {username_result['username']}")
            print(f"     Required: {username_result['username']}.YOUR_PROJECT_REF")
            print("     Find this in: Supabase Dashboard → Settings → Database → Connection String")
            print()

        if not conn_result["success"]:
            print("  2. Update DATABASE_URL port to use Transaction Pooler:")
            print(f"     Current port: {conn_result['dsn_port']}")
            print(f"     Required port: {POOLER_PORT}")
            print()

        return 1


if __name__ == "__main__":
    sys.exit(main())
