#!/usr/bin/env python3
"""
Simple test of SecurityMiddleware integration.
"""
import os

# MUST set env vars BEFORE importing the middleware
os.environ["SUPABASE_MODE"] = "dev"
os.environ["RATE_LIMIT_REQUESTS_PER_MINUTE"] = "5"
os.environ["RATE_LIMIT_BURST_SIZE"] = "5"  # Also set burst to match
os.environ["ENUMERATION_THRESHOLD"] = "3"

from fastapi import FastAPI

from backend.middleware.security import _security_store, add_security_middleware

app = FastAPI()


@app.get("/test")
async def test():
    return {"status": "ok"}


add_security_middleware(app)

print("✅ Middleware loaded successfully")
print("Testing basic functionality...")

from fastapi.testclient import TestClient

client = TestClient(app, raise_server_exceptions=False)

# Test 1
print("\n1. Normal request...")
resp = client.get("/test")
print(f"   Status: {resp.status_code}")

# Test 2 - Rate limiting
print("\n2. Rate limiting (5 req/min limit)...")
# Clear the store between tests
_security_store._rate_limits.clear()

rate_limited = False
for i in range(10):
    resp = client.get("/test", headers={"X-Forwarded-For": "10.0.0.1"})
    print(f"   Request {i+1}: {resp.status_code}")
    if resp.status_code == 429:
        print(f"   ✓ Rate limited after {i+1} requests")
        rate_limited = True
        break

if not rate_limited:
    print(f"   WARNING: Not rate limited after 10 requests")

print("\n✅ Basic tests complete")
