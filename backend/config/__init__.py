# backend/config/__init__.py
"""Backend configuration module.

This module combines:
1. Intake contract validation (local)
2. Core settings re-exported from src.core_config

NOTE: This folder shadows backend/config.py. All exports from that file
must be re-exported here for backward compatibility.
"""

# ----- Intake Contract -----
from backend.config.intake_contract import (
    ALL_COLUMNS,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    IntakeError,
    ValidationError,
    validate_batch_columns,
    validate_row,
)

# ----- Preflight utilities -----
from backend.preflight import (
    load_settings_safe,
    print_diagnostic_env,
    run_preflight_checks,
    validate_worker_env,
)

# ----- Core Config (re-export from src.core_config) -----
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
    # Intake contract
    "REQUIRED_COLUMNS",
    "OPTIONAL_COLUMNS",
    "ALL_COLUMNS",
    "IntakeError",
    "ValidationError",
    "validate_row",
    "validate_batch_columns",
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
]
