"""
Dragonfly Config Check - Canonical Keys Edition

Validates environment configuration using canonical (unsuffixed) keys.
Designed for one-file-per-environment pattern (.env.dev / .env.prod).

Blockers (Required):
    - SUPABASE_URL
    - SUPABASE_SERVICE_ROLE_KEY
    - SUPABASE_DB_URL
    - SUPABASE_MIGRATE_DB_URL

Warnings (Optional):
    - OPENAI_API_KEY (AI features disabled if missing)
    - DISCORD_WEBHOOK_URL (Alerts disabled if missing)

Derivation:
    - SUPABASE_PROJECT_REF: Auto-derived from SUPABASE_URL if missing

Exit Codes:
    0 = System bootable (required keys present, warnings OK)
    1 = System NOT bootable (missing required keys)
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable, List, Mapping

# Optional: Try loading .env if not already loaded by shell
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@dataclass
class CheckResult:
    """Result of a configuration check."""

    name: str
    status: str  # OK, WARN, FAIL
    detail: str


# =============================================================================
# CANONICAL KEY DEFINITIONS
# =============================================================================

# Required keys - missing any of these = Exit 1 (System cannot boot)
REQUIRED_KEYS: tuple[tuple[str, str], ...] = (
    ("SUPABASE_URL", "Supabase REST URL"),
    ("SUPABASE_SERVICE_ROLE_KEY", "Supabase service role key"),
    ("SUPABASE_DB_URL", "Supabase database URL (runtime)"),
    ("SUPABASE_MIGRATE_DB_URL", "Supabase database URL (migrations)"),
)

# Optional keys - missing any of these = WARN only, Exit 0
OPTIONAL_KEYS: tuple[tuple[str, str], ...] = (
    ("OPENAI_API_KEY", "OpenAI API key (AI features)"),
    ("DISCORD_WEBHOOK_URL", "Discord webhook (alerting)"),
)

# Keys that are always required even in tolerant mode
CRITICAL_KEYS = {
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_DB_URL",
    "SUPABASE_MIGRATE_DB_URL",
}


# =============================================================================
# CHECK FUNCTIONS
# =============================================================================


def check_config() -> None:
    """
    Validates environment variables against the Canonical Keys policy.
    Blockers: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, DB_URL (Pooler/Direct)
    Warnings: OPENAI_API_KEY, DISCORD_WEBHOOK_URL
    """
    missing_required: List[str] = []
    missing_optional: List[str] = []

    print("🔍 Checking Configuration (Canonical Keys)...")

    # 1. Check Required (Fatal)
    for key, _label in REQUIRED_KEYS:
        val = os.getenv(key)
        if not val or not val.strip():
            print(f"❌ MISSING BLOCKER: {key}")
            missing_required.append(key)
        else:
            print(f"✅ {key}")

    # 2. Check Optional (Warning)
    for key, _label in OPTIONAL_KEYS:
        val = os.getenv(key)
        if not val or not val.strip():
            print(f"⚠️  MISSING OPTIONAL: {key} (AI/Alerts features will be disabled)")
            missing_optional.append(key)
        else:
            print(f"✅ {key}")

    # 3. Smart Derivation (Project Ref)
    project_ref = os.getenv("SUPABASE_PROJECT_REF")
    if not project_ref:
        sb_url = os.getenv("SUPABASE_URL", "")
        match = re.search(r"https://([a-z0-9-]+)\.supabase\.co", sb_url)
        if match:
            derived_ref = match.group(1)
            os.environ["SUPABASE_PROJECT_REF"] = derived_ref
            print(f"ℹ️  Derived SUPABASE_PROJECT_REF: {derived_ref}")
        else:
            # Not fatal strictly, but good to know
            print("⚠️  Could not derive SUPABASE_PROJECT_REF from URL")
    else:
        print("✅ SUPABASE_PROJECT_REF")

    print("-" * 30)

    # 4. Exit Code Logic
    if missing_required:
        print(f"❌ FATAL: {len(missing_required)} critical configuration keys are missing.")
        sys.exit(1)

    if missing_optional:
        print(f"✅ PASSED (With {len(missing_optional)} Warnings). System is bootable.")
        sys.exit(0)  # IMPORTANT: Exit 0 means "Bootable"

    print("✅ PASSED. Configuration is perfect.")
    sys.exit(0)


# =============================================================================
# COMPATIBILITY LAYER (for doctor_all.py integration)
# =============================================================================


def _check_required_keys(env_values: Mapping[str, str]) -> list[CheckResult]:
    """Check all required keys are present."""
    results: list[CheckResult] = []

    for key, label in REQUIRED_KEYS:
        raw_value = env_values.get(key)
        value = raw_value.strip() if isinstance(raw_value, str) else None

        if not value:
            results.append(CheckResult(key, "FAIL", f"{label} is missing"))
        else:
            results.append(CheckResult(key, "OK", label))

    return results


def _check_optional_keys(env_values: Mapping[str, str]) -> list[CheckResult]:
    """Check optional keys - WARN if missing, never FAIL."""
    results: list[CheckResult] = []

    for key, label in OPTIONAL_KEYS:
        raw_value = env_values.get(key)
        value = raw_value.strip() if isinstance(raw_value, str) else None

        if not value:
            results.append(CheckResult(key, "WARN", f"{label} is missing"))
        else:
            results.append(CheckResult(key, "OK", label))

    return results


def check_environment(
    requested_env: str | None = None,
    env_values: Mapping[str, str] | None = None,
) -> list[CheckResult]:
    """
    Main entry point for config checking (used by doctor_all.py).

    Returns list of CheckResult for compatibility with existing callers.
    """
    values = env_values if env_values is not None else dict(os.environ)

    # Set SUPABASE_MODE if requested
    if requested_env:
        os.environ["SUPABASE_MODE"] = requested_env

    results: list[CheckResult] = []
    results.extend(_check_required_keys(values))
    results.extend(_check_optional_keys(values))

    # Derive project ref
    project_ref = values.get("SUPABASE_PROJECT_REF")
    if not project_ref:
        sb_url = values.get("SUPABASE_URL", "")
        match = re.search(r"https://([a-z0-9-]+)\.supabase\.co", sb_url)
        if match:
            derived_ref = match.group(1)
            os.environ["SUPABASE_PROJECT_REF"] = derived_ref
            results.append(CheckResult("SUPABASE_PROJECT_REF", "OK", f"Derived: {derived_ref}"))
        else:
            results.append(CheckResult("SUPABASE_PROJECT_REF", "WARN", "Could not derive from URL"))
    else:
        results.append(CheckResult("SUPABASE_PROJECT_REF", "OK", "Explicitly set"))

    # Print table
    print("[config_check] Environment validation summary:")
    for result in results:
        status_icon = "✅" if result.status == "OK" else ("⚠️" if result.status == "WARN" else "❌")
        print(f"  {status_icon} {result.name}: {result.detail}")

    return results


def has_failures(results: Iterable[CheckResult], tolerant: bool = False) -> bool:
    """
    Check if any results are blocking failures.

    In tolerant mode, only CRITICAL_KEYS failures are treated as fatal.
    """
    for result in results:
        if result.status != "FAIL":
            continue

        if tolerant:
            # In tolerant mode, only critical keys cause failure
            if result.name in CRITICAL_KEYS:
                return True
            # Log warning for non-critical failures
            print(f"[WARN] {result.name}: {result.detail} (Allowed for Demo/Initial Deploy)")
        else:
            return True
    return False


# =============================================================================
# CLI ENTRY POINT
# =============================================================================


if __name__ == "__main__":
    check_config()
