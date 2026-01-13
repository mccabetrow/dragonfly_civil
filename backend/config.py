"""
Dragonfly Engine - Configuration (Backend Layer)

This module re-exports from src.core_config for backward compatibility.
The canonical configuration module is src/core_config.py.

================================================================================
SINGLE SOURCE OF TRUTH – See src/core_config.py for full documentation
================================================================================

REQUIRED for application startup:
  SUPABASE_URL             – Supabase project REST URL (https://xxx.supabase.co)
  SUPABASE_SERVICE_ROLE_KEY– Service role JWT (server-side only, 100+ chars)
  SUPABASE_DB_URL          – Postgres connection string (pooler recommended)

REQUIRED for Railway production behavior:
  ENVIRONMENT=prod         – Enables rate limiting, stricter logging
  SUPABASE_MODE=prod       – Used by Python scripts/tools for DSN resolution
  PORT                     – Injected by Railway; default fallback is 8888

REQUIRED for API key authentication (X-API-Key header):
  DRAGONFLY_API_KEY        – Read from os.environ ONLY (not file secrets)
                             If missing in prod, logs warning but does not crash

FORBIDDEN in Railway runtime services:
  SUPABASE_MIGRATE_DB_URL  – Direct Postgres access (port 5432), migration-only
                             See docs/POLICY_MIGRATE_DB_URL.md

SAFE MODE:
  For diagnostic/preflight scenarios where full Settings validation would fail,
  use load_settings_safe() from backend.core.preflight to get a dict of env
  values without triggering Pydantic validation errors.

See src/core_config.py for complete environment variable documentation.
"""

import logging

# Re-export runtime credential guard from config_guard
from backend.core.config_guard import validate_runtime_config as validate_runtime_credentials

# Re-export preflight utilities for worker startup validation
from backend.preflight import (
    load_settings_safe,
    print_diagnostic_env,
    run_preflight_checks,
    validate_worker_env,
)

# Re-export everything from the canonical config module
from src.core_config import (
    RECOMMENDED_PROD_VARS,
    REQUIRED_ENV_VARS,
    REQUIRED_FOR_DB,
    Settings,
    configure_logging,
    ensure_parent_dir,
    get_deprecated_keys_used,
    get_settings,
    is_demo_env,
    log_startup_diagnostics,
    print_effective_config,
    reset_settings,
    validate_required_env,
)

__all__ = [
    # Core config
    "Settings",
    "get_settings",
    "configure_logging",
    "ensure_parent_dir",
    "is_demo_env",
    "get_deprecated_keys_used",
    "log_startup_diagnostics",
    "print_effective_config",
    "reset_settings",
    "validate_required_env",
    "REQUIRED_ENV_VARS",
    "REQUIRED_FOR_DB",
    "RECOMMENDED_PROD_VARS",
    # Preflight utilities
    "validate_worker_env",
    "run_preflight_checks",
    "load_settings_safe",
    "print_diagnostic_env",
    # Runtime security (re-exported from config_guard)
    "validate_runtime_credentials",
]


# NOTE: Do NOT instantiate settings at module level!
# Use get_settings() for lazy loading to avoid import-time crashes.
# Modules that need settings should call get_settings() inside functions.
