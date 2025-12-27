# tools/test_db_connection.py
"""Verify database connectivity for both Runtime and Migration connections."""

import os
import sys
from urllib.parse import urlparse

import psycopg


def test_connection():
    print("\n[DB-TEST] Testing Database Connectivity...")
    print("===================================")

    # 1. Test Runtime Connection (Pooler preferred, Direct allowed)
    runtime_url = os.environ.get("SUPABASE_DB_URL")
    if not runtime_url:
        print("[FAIL] Missing SUPABASE_DB_URL in environment.")
        sys.exit(1)

    try:
        parsed = urlparse(runtime_url)
        if parsed.port == 6543:
            conn_type = "Pooler"
        elif parsed.port == 5432:
            conn_type = "Direct"
            print("   [WARN] Using Direct connection for runtime (Pooler preferred)")
        else:
            print(
                f"[FAIL] SUPABASE_DB_URL must use Port 6543 (Pooler) or 5432 (Direct). Found: {parsed.port}"
            )
            sys.exit(1)

        print(f"   Target: {parsed.hostname}:{parsed.port} ({conn_type})")
        with psycopg.connect(runtime_url, connect_timeout=5):
            print("   [OK] Runtime Connection: OK")
    except Exception as e:
        print(f"   [FAIL] Runtime Connection FAILED: {e}")
        sys.exit(1)

    # 2. Test Migration Connection (Direct)
    migrate_url = os.environ.get("SUPABASE_MIGRATE_DB_URL")
    if not migrate_url:
        print("[FAIL] Missing SUPABASE_MIGRATE_DB_URL in environment.")
        sys.exit(1)

    try:
        parsed = urlparse(migrate_url)
        if parsed.port != 5432:
            print(
                f"[FAIL] SUPABASE_MIGRATE_DB_URL must use Port 5432 (Direct). Found: {parsed.port}"
            )
            sys.exit(1)

        print(f"   Target: {parsed.hostname}:5432 (Direct)")
        with psycopg.connect(migrate_url, connect_timeout=5):
            print("   [OK] Migration Connection: OK")
    except Exception as e:
        print(f"   [FAIL] Migration Connection FAILED: {e}")
        sys.exit(1)

    print("\n[OK] ALL CONNECTIONS OK")
    sys.exit(0)


if __name__ == "__main__":
    test_connection()
