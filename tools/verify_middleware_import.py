#!/usr/bin/env python3
"""
Verification script to ensure CorrelationMiddleware is importable.

Usage:
    python -m tools.verify_middleware_import

Exit Codes:
    0: Import successful
    1: Import failed
"""

from __future__ import annotations

import sys
import traceback


def main() -> int:
    """Attempt to import CorrelationMiddleware and report status."""
    try:
        from backend.middleware.correlation import CorrelationMiddleware

        # Verify it's actually a class
        if not callable(CorrelationMiddleware):
            print("❌ Import Failed: CorrelationMiddleware is not callable")
            return 1

        # Verify it has the expected dispatch method
        if not hasattr(CorrelationMiddleware, "dispatch"):
            print("❌ Import Failed: CorrelationMiddleware missing dispatch method")
            return 1

        print("✅ Middleware Importable")
        print(f"   Class: {CorrelationMiddleware}")
        print(f"   Module: {CorrelationMiddleware.__module__}")

        # Also verify the helper functions
        from backend.middleware.correlation import get_request_id, reset_request_id, set_request_id

        print("   Helper functions: get_request_id, set_request_id, reset_request_id ✓")

        return 0

    except ImportError as e:
        print("❌ Import Failed")
        print(f"   Error: {e}")
        print()
        print("Traceback:")
        traceback.print_exc()
        return 1

    except Exception as e:
        print(f"❌ Unexpected Error: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
