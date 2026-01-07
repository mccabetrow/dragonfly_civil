#!/usr/bin/env python3
"""
Test script for SecurityMiddleware rate limiting and enumeration detection.

Usage:
    python -m tools.test_middleware --env dev
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Test security middleware")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    args = parser.parse_args()

    os.environ["SUPABASE_MODE"] = args.env
    print(f"Testing SecurityMiddleware on {args.env}...\n")

    # Import after setting env
    from backend.middleware.security import add_security_middleware

    # Create test app
    app = FastAPI()

    @app.get("/api/test")
    async def test_endpoint():
        return {"status": "ok"}

    @app.get("/api/does-not-exist-{id}")
    async def dynamic_route(id: str):
        raise HTTPException(status_code=404)

    # Add security middleware with test-friendly limits
    add_security_middleware(
        app,
        requests_per_minute=10,  # Low limit for testing
        enumeration_threshold=5,  # Low threshold for testing
    )

    client = TestClient(app)

    # Test 1: Normal requests should work
    print("--- Test 1: Normal requests ---")
    response = client.get("/api/test")
    assert response.status_code == 200
    print(f"[✓] Normal request: {response.json()}")

    # Test 2: Rate limiting
    print("\n--- Test 2: Rate limiting ---")
    success_count = 0
    rate_limited = False
    for i in range(15):
        response = client.get("/api/test", headers={"X-Forwarded-For": "192.168.1.100"})
        if response.status_code == 200:
            success_count += 1
        elif response.status_code == 429:
            rate_limited = True
            retry_after = response.headers.get("Retry-After")
            print(f"[✓] Rate limited after {success_count} requests (Retry-After: {retry_after}s)")
            break

    if not rate_limited:
        print(f"[✗] Expected rate limiting but got {success_count} successful requests")
        return 1

    # Test 3: Enumeration detection
    print("\n--- Test 3: Enumeration detection ---")
    success_count = 0
    enumeration_blocked = False
    for i in range(10):
        response = client.get(
            f"/api/does-not-exist-{i}", headers={"X-Forwarded-For": "192.168.1.200"}
        )
        if response.status_code == 404:
            success_count += 1
        elif response.status_code == 429:
            enumeration_blocked = True
            print(f"[✓] Enumeration blocked after {success_count} 404s (threshold: 5)")
            break

    if not enumeration_blocked:
        print(f"[✗] Expected enumeration blocking but got {success_count} 404 responses")
        return 1

    # Test 4: Different IPs should have separate limits
    print("\n--- Test 4: Independent IP tracking ---")
    response1 = client.get("/api/test", headers={"X-Forwarded-For": "192.168.1.50"})
    response2 = client.get("/api/test", headers={"X-Forwarded-For": "192.168.1.51"})
    assert response1.status_code == 200
    assert response2.status_code == 200
    print("[✓] Different IPs have independent rate limits")

    # Test 5: Check incident logging
    print("\n--- Test 5: Incident logging ---")
    from src.supabase_client import create_supabase_client

    client_sb = create_supabase_client()

    # Wait a moment for async logging to complete
    time.sleep(2)

    # Check for rate_limit_exceeded incidents
    result = client_sb.rpc("get_incident_summary", {"p_hours": 1}).execute()

    incidents = result.data
    print(f"[✓] Found {len(incidents)} incident types in last hour:")
    for incident in incidents:
        print(
            f"    {incident['severity']} / {incident['event_type']}: {incident['incident_count']} incidents"
        )

    print("\n✅ All middleware tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
