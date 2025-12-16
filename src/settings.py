"""
Dragonfly Engine - Settings (Backward Compatibility Layer)

This module re-exports from src.core_config for backward compatibility.
New code should import directly from src.core_config.

NOTE: This module is maintained for backward compatibility.
      Import from src.core_config for new code.
"""

from __future__ import annotations

# Re-export everything from the canonical config module
from .core_config import (
    Settings,
    configure_logging,
    ensure_parent_dir,
    get_deprecated_keys_used,
    get_settings,
    is_demo_env,
    print_effective_config,
    reset_settings,
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
]
