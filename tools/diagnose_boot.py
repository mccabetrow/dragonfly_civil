#!/usr/bin/env python3
"""
Dragonfly Boot Diagnostics

Run this script inside the container during boot (or as a one-off command)
to verify the environment before the main application starts.

Usage:
    python -m tools.diagnose_boot

Railway one-off:
    railway run python -m tools.diagnose_boot

Checks performed:
    1. Database URL (SUPABASE_DB_URL or DATABASE_URL)
    2. PORT environment variable
    3. Supabase credentials (SUPABASE_URL, SUPABASE_ANON_KEY)
    4. Python version and import sanity
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone


def _mask(value: str, show_chars: int = 4) -> str:
    """Mask a value, showing only first N chars."""
    if len(value) <= show_chars:
        return "*" * len(value)
    return value[:show_chars] + "*" * (len(value) - show_chars)


def check_database_url() -> bool:
    """Check for database URL in environment."""
    print("\n" + "=" * 60)
    print("  DATABASE CONFIGURATION")
    print("=" * 60)

    # Check canonical DATABASE_URL first (Railway/Heroku standard)
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if db_url:
        print(f"✅ DATABASE_URL found (length: {len(db_url)})")
        # Show host portion for debugging (not password)
        if "@" in db_url and "/" in db_url:
            try:
                host_part = db_url.split("@")[1].split("/")[0]
                print(f"   Host: {host_part}")
            except IndexError:
                pass
        return True

    # Fallback to SUPABASE_DB_URL (deprecated but supported)
    supabase_db = os.environ.get("SUPABASE_DB_URL", "").strip()
    if supabase_db:
        print(f"✅ SUPABASE_DB_URL found (length: {len(supabase_db)})")
        print("   ⚠️  Note: DATABASE_URL is preferred (canonical)")
        if "@" in supabase_db and "/" in supabase_db:
            try:
                host_part = supabase_db.split("@")[1].split("/")[0]
                print(f"   Host: {host_part}")
            except IndexError:
                pass
        return True

    # Neither found - critical error
    print("❌ CRITICAL: Database URL is MISSING from env vars")
    print()
    print("   REMEDIATION:")
    print("   1. In Railway dashboard, set DATABASE_URL variable")
    print("   2. Format: postgresql://user:pass@host:5432/postgres?sslmode=require")
    print("   3. For Supabase pooler: use port 6543")
    return False


def check_port() -> bool:
    """Check PORT environment variable."""
    print("\n" + "=" * 60)
    print("  PORT CONFIGURATION")
    print("=" * 60)

    port = os.environ.get("PORT", "").strip()
    if port:
        try:
            port_int = int(port)
            print(f"ℹ️  PORT env var: {port_int}")
            if port_int < 1024 and port_int != 80:
                print("   ⚠️  Port < 1024 may require elevated privileges")
            return True
        except ValueError:
            print(f"❌ PORT is set but invalid: {port!r}")
            return False
    else:
        print("ℹ️  PORT env var: not set (will default to 8080)")
        return True  # Not critical - we have a default


def check_supabase_credentials() -> bool:
    """Check Supabase API credentials."""
    print("\n" + "=" * 60)
    print("  SUPABASE CREDENTIALS")
    print("=" * 60)

    all_present = True

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    if supabase_url:
        print(f"✅ SUPABASE_URL: {supabase_url}")
    else:
        print("❌ SUPABASE_URL is MISSING")
        all_present = False

    anon_key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if anon_key:
        print(f"✅ SUPABASE_ANON_KEY found (length: {len(anon_key)})")
    else:
        print("❌ SUPABASE_ANON_KEY is MISSING")
        all_present = False

    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if service_key:
        print(f"✅ SUPABASE_SERVICE_ROLE_KEY found (length: {len(service_key)})")
    else:
        print("⚠️  SUPABASE_SERVICE_ROLE_KEY not set (may be optional)")

    return all_present


def check_dragonfly_env() -> bool:
    """Check Dragonfly-specific environment variables."""
    print("\n" + "=" * 60)
    print("  DRAGONFLY ENVIRONMENT")
    print("=" * 60)

    env = os.environ.get("DRAGONFLY_ACTIVE_ENV", "").strip()
    mode = os.environ.get("SUPABASE_MODE", "").strip()

    if env:
        print(f"ℹ️  DRAGONFLY_ACTIVE_ENV: {env}")
    elif mode:
        print(f"ℹ️  SUPABASE_MODE: {mode}")
    else:
        print("⚠️  No environment marker set (DRAGONFLY_ACTIVE_ENV or SUPABASE_MODE)")

    return True  # Not critical


def check_python_imports() -> bool:
    """Verify critical Python imports work."""
    print("\n" + "=" * 60)
    print("  PYTHON ENVIRONMENT")
    print("=" * 60)

    print(f"ℹ️  Python version: {sys.version}")

    errors = []

    try:
        import uvicorn  # noqa: F401

        print("✅ uvicorn imported successfully")
    except ImportError as e:
        print(f"❌ uvicorn import failed: {e}")
        errors.append("uvicorn")

    try:
        import httpx  # noqa: F401

        print("✅ httpx imported successfully")
    except ImportError as e:
        print(f"❌ httpx import failed: {e}")
        errors.append("httpx")

    try:
        import psycopg  # noqa: F401

        print("✅ psycopg imported successfully")
    except ImportError as e:
        print(f"⚠️  psycopg import failed: {e} (may be optional)")

    try:
        # Test that our app module can be found
        # Note: This may fail if config guards block boot (expected behavior)
        import backend.main  # noqa: F401

        print("✅ backend.main imported successfully")
    except ImportError as e:
        print(f"❌ backend.main import failed: {e}")
        errors.append("backend.main")
    except Exception as e:
        # Config guards or other runtime checks may raise
        print(f"⚠️  backend.main import blocked by config guard: {type(e).__name__}")
        print("   (This is expected if SUPABASE_MIGRATE_DB_URL is set in prod mode)")

    return len(errors) == 0


def main() -> int:
    """Run all boot diagnostics."""
    print("\n" + "=" * 72)
    print("  DRAGONFLY BOOT DIAGNOSTICS")
    print(f"  Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 72)

    all_passed = True

    # Critical checks
    if not check_database_url():
        all_passed = False

    if not check_port():
        all_passed = False

    if not check_supabase_credentials():
        all_passed = False

    # Informational checks
    check_dragonfly_env()

    if not check_python_imports():
        all_passed = False

    # Summary
    print("\n" + "=" * 72)
    if all_passed:
        print("  ✅ BOOT DIAGNOSTICS: PASSED")
        print("  Application environment is correctly configured.")
    else:
        print("  ❌ BOOT DIAGNOSTICS: FAILED")
        print("  Fix the errors above before starting the application.")
    print("=" * 72 + "\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
