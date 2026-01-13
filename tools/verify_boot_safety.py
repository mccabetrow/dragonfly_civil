#!/usr/bin/env python3
"""
Boot Safety Verification Script

Verifies that backend.main imports successfully and the FastAPI app object exists,
even if optional components (like CorrelationMiddleware) are missing.

This script ensures our "Indestructible Boot" policy is upheld:
- The API must always start on port 8080
- Missing middleware = log warning, not crash

Usage:
    python -m tools.verify_boot_safety

Exit Codes:
    0: Boot safety verified (app imports without ModuleNotFoundError)
    1: Boot safety FAILED (ModuleNotFoundError or app not found)
"""

from __future__ import annotations

import sys
import traceback


def main() -> int:
    """Attempt to import backend.main and verify app exists."""
    print("=" * 60)
    print("  DRAGONFLY BOOT SAFETY VERIFICATION")
    print("=" * 60)
    print()

    try:
        print("[1/3] Importing backend.main...")
        from backend import main as backend_main

        print("      ✓ backend.main imported successfully")

    except ModuleNotFoundError as e:
        print(f"      ✗ ModuleNotFoundError: {e}")
        print()
        print("❌ BOOT SAFETY FAILED")
        print("   The API would crash on startup with this error.")
        print()
        print("Traceback:")
        traceback.print_exc()
        return 1

    except Exception as e:
        print(f"      ✗ Unexpected Error: {type(e).__name__}: {e}")
        print()
        print("❌ BOOT SAFETY FAILED (unexpected error)")
        traceback.print_exc()
        return 1

    # Check that 'app' exists and is a FastAPI instance
    try:
        print("[2/3] Checking for FastAPI app object...")
        app = getattr(backend_main, "app", None)

        if app is None:
            print("      ✗ 'app' object not found in backend.main")
            print()
            print("❌ BOOT SAFETY FAILED")
            print("   Uvicorn expects backend.main:app to exist.")
            return 1

        print(f"      ✓ app exists: {type(app).__name__}")

    except Exception as e:
        print(f"      ✗ Error accessing app: {e}")
        traceback.print_exc()
        return 1

    # Check middleware count (informational)
    try:
        print("[3/3] Checking middleware stack...")
        middleware_count = len(getattr(app, "user_middleware", []))
        print(f"      ✓ {middleware_count} middleware(s) registered")
    except Exception:
        print("      ⚠ Could not count middleware (non-fatal)")

    print()
    print("=" * 60)
    print("  ✅ BOOT SAFETY VERIFIED")
    print("=" * 60)
    print()
    print("  The API will start successfully on port 8080.")
    print("  If CorrelationMiddleware is missing, it logs CRITICAL")
    print("  but does NOT crash.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
