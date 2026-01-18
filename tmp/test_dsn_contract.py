"""Test Single DSN Contract: DATABASE_URL canonical, SUPABASE_DB_URL fallback."""

import os

# Clear any existing DB URLs
for k in ["DATABASE_URL", "SUPABASE_DB_URL", "supabase_db_url"]:
    os.environ.pop(k, None)

# Set required config
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "eyJ" + "x" * 100

print("=" * 60)
print("TEST 1: No DB URL configured (should enter degraded mode)")
print("=" * 60)

from importlib import reload

import src.core_config

reload(src.core_config)
src.core_config.get_settings.cache_clear()

s = src.core_config.get_settings()
assert s.SUPABASE_DB_URL == "", f"Expected empty, got {s.SUPABASE_DB_URL}"
print("✓ PASS: Empty SUPABASE_DB_URL, degraded mode")

print("\n" + "=" * 60)
print("TEST 2: DATABASE_URL canonical takes precedence")
print("=" * 60)

os.environ["DATABASE_URL"] = "postgresql://canonical@host:5432/db"
os.environ["SUPABASE_DB_URL"] = "postgresql://legacy@old:5432/db"

reload(src.core_config)
src.core_config.get_settings.cache_clear()

s = src.core_config.get_settings()
assert "canonical@host" in s.SUPABASE_DB_URL, f"Expected canonical, got {s.SUPABASE_DB_URL}"
print(f"✓ PASS: SUPABASE_DB_URL = {s.SUPABASE_DB_URL}")

print("\n" + "=" * 60)
print("TEST 3: SUPABASE_DB_URL fallback when no DATABASE_URL")
print("=" * 60)

os.environ.pop("DATABASE_URL", None)
os.environ["SUPABASE_DB_URL"] = "postgresql://legacy@old:5432/db"

reload(src.core_config)
src.core_config.get_settings.cache_clear()

s = src.core_config.get_settings()
assert "legacy@old" in s.SUPABASE_DB_URL, f"Expected legacy, got {s.SUPABASE_DB_URL}"
print(f"✓ PASS: SUPABASE_DB_URL = {s.SUPABASE_DB_URL}")

print("\n" + "=" * 60)
print("ALL TESTS PASSED: Single DSN Contract verified!")
print("=" * 60)
