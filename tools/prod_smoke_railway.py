#!/usr/bin/env python3
"""
Dragonfly Engine - Production Smoke Test for Railway

Minimal smoke test to verify the backend is running correctly on Railway.
Reads API_BASE_URL from environment and checks /health endpoint.

Usage:
    # Set the Railway URL
    export API_BASE_URL=https://your-app.railway.app

    # Run smoke test
    python -m tools.prod_smoke_railway

    # Or with explicit URL
    python -m tools.prod_smoke_railway --url https://your-app.railway.app

Exit codes:
    0 - All checks passed
    1 - Health check failed
    2 - Connection error
"""

import argparse
import os
import sys
from datetime import datetime

import httpx


def smoke_test(base_url: str) -> bool:
    """
    Run smoke test against the production backend.

    Args:
        base_url: The base URL of the Railway deployment

    Returns:
        True if all checks pass, False otherwise
    """
    print("🔍 Dragonfly Production Smoke Test")
    print(f"   Target: {base_url}")
    print(f"   Time:   {datetime.utcnow().isoformat()}Z")
    print()

    checks_passed = 0
    checks_failed = 0

    # Normalize URL
    base_url = base_url.rstrip("/")

    # Create client with reasonable timeout
    client = httpx.Client(timeout=30.0)

    # Check 1: Root endpoint
    print("1️⃣  Checking GET / ...")
    try:
        resp = client.get(f"{base_url}/")
        if resp.status_code == 200:
            data = resp.json()
            if data.get("service") == "Dragonfly Engine":
                print(f"   ✅ Root endpoint OK: {data.get('version', 'unknown')}")
                checks_passed += 1
            else:
                print(f"   ❌ Unexpected response: {data}")
                checks_failed += 1
        else:
            print(f"   ❌ HTTP {resp.status_code}")
            checks_failed += 1
    except Exception as e:
        print(f"   ❌ Error: {e}")
        checks_failed += 1

    # Check 2: Health endpoint
    print("2️⃣  Checking GET /health ...")
    try:
        resp = client.get(f"{base_url}/health")
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "ok":
                print("   ✅ Health endpoint OK")
                checks_passed += 1
            else:
                print(f"   ❌ Unexpected status: {data}")
                checks_failed += 1
        else:
            print(f"   ❌ HTTP {resp.status_code}")
            checks_failed += 1
    except Exception as e:
        print(f"   ❌ Error: {e}")
        checks_failed += 1

    # Check 3: API Health endpoint
    print("3️⃣  Checking GET /api/health ...")
    try:
        resp = client.get(f"{base_url}/api/health")
        if resp.status_code == 200:
            data = resp.json()
            print(f"   ✅ API health OK: env={data.get('environment', 'unknown')}")
            checks_passed += 1
        else:
            print(f"   ❌ HTTP {resp.status_code}")
            checks_failed += 1
    except Exception as e:
        print(f"   ❌ Error: {e}")
        checks_failed += 1

    # Check 4: Intake health endpoint (requires API key)
    print("4️⃣  Checking GET /api/v1/intake/health ...")
    api_key = os.environ.get("DRAGONFLY_API_KEY")
    try:
        headers = {"X-API-Key": api_key} if api_key else {}
        resp = client.get(f"{base_url}/api/v1/intake/health", headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            print(f"   ✅ Intake subsystem OK: {data.get('subsystem', 'unknown')}")
            checks_passed += 1
        elif resp.status_code == 401 and not api_key:
            print("   ⚠️  HTTP 401 (set DRAGONFLY_API_KEY to test authenticated endpoints)")
        else:
            print(f"   ⚠️  HTTP {resp.status_code} (intake may not be deployed)")
            # Don't fail on intake - it might not be enabled
    except Exception as e:
        print(f"   ⚠️  Error: {e} (intake may not be deployed)")

    # Summary
    print()
    print("=" * 50)
    total = checks_passed + checks_failed
    if checks_failed == 0:
        print(f"✅ ALL {checks_passed} CHECKS PASSED")
        return True
    else:
        print(f"❌ {checks_failed}/{total} CHECKS FAILED")
        return False


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Production smoke test for Dragonfly Engine on Railway"
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("API_BASE_URL"),
        help="Base URL of the Railway deployment (or set API_BASE_URL env var)",
    )

    args = parser.parse_args()

    if not args.url:
        print("❌ Error: No URL provided")
        print("   Set API_BASE_URL environment variable or use --url flag")
        print()
        print("   Example:")
        print("     export API_BASE_URL=https://your-app.railway.app")
        print("     python -m tools.prod_smoke_railway")
        sys.exit(2)

    try:
        success = smoke_test(args.url)
        sys.exit(0 if success else 1)
    except httpx.ConnectError as e:
        print(f"❌ Connection error: {e}")
        print("   Is the Railway deployment running?")
        sys.exit(2)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
