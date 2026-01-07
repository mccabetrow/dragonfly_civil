"""
Dragonfly Civil - Platform Monitors

This package contains monitoring services that enforce platform SLOs
and ensure system health.

Components:
  - watchdog: Main health monitor with 60s control loop
"""

from backend.monitors.watchdog import (
    CheckResult,
    CheckStatus,
    WatchdogReport,
    run_watchdog_iteration,
)

__all__ = [
    "CheckResult",
    "CheckStatus",
    "WatchdogReport",
    "run_watchdog_iteration",
]
