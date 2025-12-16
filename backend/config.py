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

See src/core_config.py for complete environment variable documentation.
"""

import logging

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
    print_effective_config,
    reset_settings,
    validate_required_env,
)

__all__ = [
    "Settings",
    "get_settings",
    "configure_logging",
    "ensure_parent_dir",
    "is_demo_env",
    "get_deprecated_keys_used",
    "print_effective_config",
    "reset_settings",
    "validate_required_env",
    "REQUIRED_ENV_VARS",
    "REQUIRED_FOR_DB",
    "RECOMMENDED_PROD_VARS",
    "settings",
]

# Export settings instance for convenience
settings = get_settings()
