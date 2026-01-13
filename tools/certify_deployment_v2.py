#!/usr/bin/env python3
"""
Dragonfly Engine - Deployment Certification (Simplified)

Final authority verification script for production readiness.

Checks:
  1. GET /health => 200
  2. GET /readyz => 200
  3. X-Dragonfly-SHA header present

Usage:
    python -m tools.certify_deployment_v2 --url https://dragonfly-api-production.up.railway.app

Exit codes:
    0 = ✅ GO FOR PLAINTIFFS
    1 = 🛑 STOP - Fix required
"""

from __future__ import annotations

import argparse
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def check_endpoint(
    base_url: str, path: str, expected_status: int = 200
) -> tuple[bool, str, dict[str, str]]:
    """
    Check an endpoint and return (success, detail, headers).

    Uses stdlib only - no external dependencies.
    """
    url = f"{base_url.rstrip('/')}{path}"
    headers: dict[str, str] = {}

    try:
        req = Request(url, headers={"User-Agent": "Dragonfly-Certifier/1.0"})
        with urlopen(req, timeout=15) as response:
            status = response.status
            # Convert headers to dict
            for key, value in response.getheaders():
                headers[key] = value

            if status == expected_status:
                return True, f"HTTP {status}", headers
            else:
                return False, f"Expected {expected_status}, got {status}", headers

    except HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}", {}
    except URLError as e:
        return False, f"Connection failed: {e.reason}", {}
    except Exception as e:
        return False, f"Error: {e}", {}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dragonfly Deployment Certification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Base URL of the API (e.g., https://dragonfly-api-production.up.railway.app)",
    )
    args = parser.parse_args()

    base_url = args.url.rstrip("/")

    print("=" * 60)
    print("  DRAGONFLY DEPLOYMENT CERTIFICATION")
    print("=" * 60)
    print(f"\n  Target: {base_url}\n")

    all_passed = True
    sha_header = None

    # Check 1: /health
    print("[1/3] Checking /health endpoint...")
    ok, detail, headers = check_endpoint(base_url, "/health")
    if ok:
        print(f"      ✅ PASS - {detail}")
    else:
        print(f"      ❌ FAIL - {detail}")
        all_passed = False

    # Check 2: /readyz
    print("[2/3] Checking /readyz endpoint...")
    ok, detail, headers = check_endpoint(base_url, "/readyz")
    if ok:
        print(f"      ✅ PASS - {detail}")
    else:
        print(f"      ❌ FAIL - {detail}")
        all_passed = False

    # Capture SHA header from last response
    sha_header = headers.get("X-Dragonfly-SHA-Short") or headers.get("X-Dragonfly-SHA")

    # Check 3: SHA Header
    print("[3/3] Checking X-Dragonfly-SHA header...")
    if sha_header:
        print(f"      ✅ PASS - SHA: {sha_header}")
    else:
        # Try /health again specifically for headers
        _, _, health_headers = check_endpoint(base_url, "/health")
        sha_header = health_headers.get("X-Dragonfly-SHA-Short") or health_headers.get(
            "X-Dragonfly-SHA"
        )
        if sha_header:
            print(f"      ✅ PASS - SHA: {sha_header}")
        else:
            print("      ❌ FAIL - X-Dragonfly-SHA header missing")
            all_passed = False

    # Final verdict
    print("\n" + "=" * 60)
    if all_passed:
        print("  ✅ GO FOR PLAINTIFFS")
        print("=" * 60)
        return 0
    else:
        print("  🛑 STOP - FIX REQUIRED")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
