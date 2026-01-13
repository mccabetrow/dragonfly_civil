"""Dragonfly Engine - Runtime Environment Configuration Auditor.

Usage:
    python -m tools.verify_env_config

The script validates production-safety invariants before traffic is allowed.
Exit codes:
    0 -> all checks pass
    1 -> one or more violations detected (message printed to stderr)
"""

from __future__ import annotations

import os
import sys
from typing import List


def _get_env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _failsafe_print(message: str, *, ok: bool) -> None:
    stream = sys.stdout if ok else sys.stderr
    stream.write(message + "\n")
    stream.flush()


def main() -> int:
    errors: List[str] = []

    environment = _get_env("ENVIRONMENT") or _get_env("DRAGONFLY_ENV")
    migrate_url = _get_env("SUPABASE_MIGRATE_DB_URL")
    if environment.lower() == "prod" and migrate_url:
        errors.append("Migration DSN (SUPABASE_MIGRATE_DB_URL) must not be set in prod")

    cors_origins = _get_env("DRAGONFLY_CORS_ORIGINS")
    if not cors_origins:
        errors.append("DRAGONFLY_CORS_ORIGINS missing or empty")

    redis_url = _get_env("REDIS_URL") or _get_env("RATE_LIMIT_REDIS_URL")
    if not redis_url:
        errors.append("Rate limiting backend URL (REDIS_URL) missing")

    supabase_service_role = _get_env("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_service_role:
        errors.append("SUPABASE_SERVICE_ROLE_KEY missing")

    if errors:
        _failsafe_print("❌ Config Invalid:", ok=False)
        for reason in errors:
            _failsafe_print(f"   - {reason}", ok=False)
        return 1

    _failsafe_print("✅ Config Verified", ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
