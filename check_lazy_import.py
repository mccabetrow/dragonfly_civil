#!/usr/bin/env python3
"""
Verification script for lazy configuration loading.

Tests that importing backend modules does NOT trigger Pydantic validation
or access secrets from os.environ at import time.

Usage:
    # Clear env vars first (Windows PowerShell):
    $env:SUPABASE_URL = $null
    $env:SUPABASE_SERVICE_ROLE_KEY = $null
    $env:SUPABASE_DB_URL = $null
    python check_lazy_import.py

Expected output on success:
    ✅ PASS: All imports succeeded without settings validation

Expected output on failure:
    ❌ FAIL: Import triggered settings validation
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

# Secret environment variable keys that should NOT be accessed at import time
SECRET_KEYS = [
    "SUPABASE_URL",
    "SUPABASE_URL_DEV",
    "SUPABASE_URL_PROD",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_SERVICE_ROLE_KEY_DEV",
    "SUPABASE_SERVICE_ROLE_KEY_PROD",
    "SUPABASE_DB_URL",
    "SUPABASE_DB_URL_DEV",
    "SUPABASE_DB_URL_PROD",
    "SUPABASE_ANON_KEY",
    "SUPABASE_ANON_KEY_DEV",
    "SUPABASE_ANON_KEY_PROD",
]

# Track which secret keys were accessed during import
_accessed_secrets: list[str] = []

# Store original os.environ.get and __getitem__
_original_environ_get = os.environ.get
_original_environ_getitem = os.environ.__class__.__getitem__


def _tracking_get(key: str, default: str | None = None) -> str | None:
    """Track access to secret environment variables via .get()."""
    if key in SECRET_KEYS:
        _accessed_secrets.append(key)
    return _original_environ_get(key, default)


def _tracking_getitem(self, key: str) -> str:
    """Track access to secret environment variables via []."""
    if key in SECRET_KEYS:
        _accessed_secrets.append(key)
    return _original_environ_getitem(self, key)


# Remove env vars that would allow Settings to validate
# (Only if they exist - don't error if missing)
for key in SECRET_KEYS:
    os.environ.pop(key, None)

# Also clear ENV_FILE to prevent loading from .env files
os.environ.pop("ENV_FILE", None)
os.environ["ENV_FILE"] = "/nonexistent/.env.fake"  # Point to nonexistent file

print("=" * 60)
print("LAZY IMPORT VERIFICATION")
print("=" * 60)
print()
print("Testing imports without valid environment variables...")
print("Also verifying os.environ was NOT accessed for secrets...")
print()

modules_to_test = [
    ("backend.db", "Database layer"),
    ("backend.config", "Configuration re-exports"),
    ("backend.services.ai_service", "AI service"),
    ("backend.services.enrichment_service", "Enrichment service"),
]

all_passed = True

# Patch os.environ.get and __getitem__ to track secret access
os.environ.get = _tracking_get
os.environ.__class__.__getitem__ = _tracking_getitem

try:
    for module_name, description in modules_to_test:
        _accessed_secrets.clear()
        try:
            print(f"  Importing {module_name}...", end=" ")
            __import__(module_name)
            if _accessed_secrets:
                print(f"✗ FAILED (accessed secrets: {set(_accessed_secrets)})")
                all_passed = False
            else:
                print("✓")
        except Exception as e:
            print("✗ FAILED")
            print(f"    Error: {type(e).__name__}: {e}")
            all_passed = False
finally:
    # Restore original functions
    os.environ.get = _original_environ_get
    os.environ.__class__.__getitem__ = _original_environ_getitem

print()
print("=" * 60)

if all_passed:
    print("✅ PASS: All imports succeeded without settings validation")
    print("✅ PASS: No secret environment variables accessed at import time")
    print()
    print("Lazy configuration loading is working correctly.")
    print("You can now run: python -m tools.prod_gate --help")
    sys.exit(0)
else:
    print("❌ FAIL: Import triggered settings validation or accessed secrets")
    print()
    print("Some modules still have global get_settings() calls or access secrets.")
    print("Check the failed modules above and remove global settings instantiation.")
    sys.exit(1)
