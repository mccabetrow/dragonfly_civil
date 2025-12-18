#!/usr/bin/env python3
"""
Railway Environment Audit Script

Validates environment variable configuration for Railway deployments.
Ensures deterministic, drift-proof deployments by enforcing the env contract.

Features:
- Prints canonical env contract (required keys per service)
- Detects deprecated/lowercase keys and fails with clear message
- Detects conflicting keys (e.g., LOG_LEVEL vs log_level on Linux)
- Validates required variables are present

Usage:
    python scripts/railway_env_audit.py [--service SERVICE] [--strict]

Options:
    --service SERVICE   Check requirements for specific service (api, ingest, enforcement, simplicity)
    --check             CI mode: fail on errors or collisions, warn on deprecated keys
    --strict            Fail on any deprecated key usage (default: warn only)
    --check-conflicts   Check for case-sensitive key conflicts (Linux behavior)
    --print-contract    Print the canonical env contract and exit

Exit Codes:
    0 - All checks passed
    1 - Missing required variables
    2 - Deprecated key collision detected
    3 - Case-sensitive conflict detected
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Literal

# ==============================================================================
# ENV CONTRACT DEFINITION
# ==============================================================================

# Canonical environment variables - UPPERCASE only
CANONICAL_ENV_CONTRACT = {
    # Required for ALL services
    "shared_required": [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_DB_URL",
        "ENVIRONMENT",
        "SUPABASE_MODE",
    ],
    # API-specific
    "api_required": [
        "PORT",  # Injected by Railway
    ],
    "api_recommended": [
        "DRAGONFLY_API_KEY",
        "DRAGONFLY_CORS_ORIGINS",
        "LOG_LEVEL",
    ],
    # Ingest worker
    "ingest_required": [],
    "ingest_recommended": [
        "LOG_LEVEL",
    ],
    # Enforcement worker
    "enforcement_required": [],
    "enforcement_recommended": [
        "OPENAI_API_KEY",
        "LOG_LEVEL",
    ],
    # Simplicity ingest worker
    "simplicity_required": [],
    "simplicity_recommended": [
        "LOG_LEVEL",
    ],
}

# Deprecated keys that should be removed
DEPRECATED_KEYS = {
    # Lowercase variants (case matters on Linux!)
    "supabase_url": "SUPABASE_URL",
    "supabase_service_role_key": "SUPABASE_SERVICE_ROLE_KEY",
    "supabase_db_url": "SUPABASE_DB_URL",
    "supabase_mode": "SUPABASE_MODE",
    "environment": "ENVIRONMENT",
    "log_level": "LOG_LEVEL",
    "dragonfly_api_key": "DRAGONFLY_API_KEY",
    "dragonfly_cors_origins": "DRAGONFLY_CORS_ORIGINS",
    "openai_api_key": "OPENAI_API_KEY",
    # _PROD suffix variants (use SUPABASE_MODE=prod instead)
    "SUPABASE_URL_PROD": "SUPABASE_URL (set SUPABASE_MODE=prod)",
    "SUPABASE_SERVICE_ROLE_KEY_PROD": "SUPABASE_SERVICE_ROLE_KEY (set SUPABASE_MODE=prod)",
    "SUPABASE_DB_URL_PROD": "SUPABASE_DB_URL (set SUPABASE_MODE=prod)",
    "SUPABASE_DB_URL_DIRECT_PROD": "SUPABASE_DB_URL (set SUPABASE_MODE=prod)",
    # _DEV suffix variants
    "SUPABASE_URL_DEV": "SUPABASE_URL (set SUPABASE_MODE=dev)",
    "SUPABASE_SERVICE_ROLE_KEY_DEV": "SUPABASE_SERVICE_ROLE_KEY (set SUPABASE_MODE=dev)",
    "SUPABASE_DB_URL_DEV": "SUPABASE_DB_URL (set SUPABASE_MODE=dev)",
}

# Keys that could collide (lowercase -> uppercase pairs)
CASE_CONFLICT_PAIRS = [
    ("supabase_url", "SUPABASE_URL"),
    ("supabase_service_role_key", "SUPABASE_SERVICE_ROLE_KEY"),
    ("supabase_db_url", "SUPABASE_DB_URL"),
    ("supabase_mode", "SUPABASE_MODE"),
    ("environment", "ENVIRONMENT"),
    ("log_level", "LOG_LEVEL"),
    ("dragonfly_api_key", "DRAGONFLY_API_KEY"),
    ("dragonfly_cors_origins", "DRAGONFLY_CORS_ORIGINS"),
    ("openai_api_key", "OPENAI_API_KEY"),
]


# ==============================================================================
# RESULT TYPES
# ==============================================================================


@dataclass
class AuditResult:
    """Result of environment audit."""

    success: bool
    missing_required: list[str] = field(default_factory=list)
    deprecated_found: dict[str, str] = field(default_factory=dict)  # deprecated -> canonical
    conflicts_found: list[tuple[str, str]] = field(default_factory=list)  # (lower, upper) pairs
    warnings: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if self.missing_required:
            return 1
        if self.conflicts_found:
            return 3
        if self.deprecated_found:
            return 2
        return 0


# ==============================================================================
# AUDIT FUNCTIONS
# ==============================================================================


def get_service_required_vars(service: str) -> list[str]:
    """Get required env vars for a specific service."""
    shared = CANONICAL_ENV_CONTRACT["shared_required"]
    service_key = f"{service}_required"
    service_specific = CANONICAL_ENV_CONTRACT.get(service_key, [])
    return shared + service_specific


def get_service_recommended_vars(service: str) -> list[str]:
    """Get recommended (conditionally required) vars for a service."""
    service_key = f"{service}_recommended"
    return CANONICAL_ENV_CONTRACT.get(service_key, [])


def check_missing_required(service: str, env: dict[str, str]) -> list[str]:
    """Check for missing required environment variables."""
    required = get_service_required_vars(service)
    missing = []
    for var in required:
        if var not in env:
            # Special case: PORT is injected by Railway, may not exist locally
            if var == "PORT" and os.getenv("RAILWAY_ENVIRONMENT") is None:
                continue
            missing.append(var)
    return missing


def check_deprecated_keys(env: dict[str, str]) -> dict[str, str]:
    """Check for deprecated environment variables."""
    found = {}
    for deprecated, canonical in DEPRECATED_KEYS.items():
        if deprecated in env:
            found[deprecated] = canonical
    return found


def check_case_conflicts(env: dict[str, str]) -> list[tuple[str, str]]:
    """
    Check for case-sensitive conflicts (Linux behavior).

    On Linux, `LOG_LEVEL` and `log_level` are DIFFERENT variables.
    If both exist with different values, behavior is undefined.
    """
    conflicts = []
    for lower, upper in CASE_CONFLICT_PAIRS:
        if lower in env and upper in env:
            lower_val = env[lower]
            upper_val = env[upper]
            if lower_val != upper_val:
                conflicts.append((lower, upper))
    return conflicts


def run_audit(
    service: str = "api",
    strict: bool = False,
    check_conflicts: bool = True,
) -> AuditResult:
    """Run full environment audit."""
    env = dict(os.environ)

    result = AuditResult(success=True)

    # Check missing required
    result.missing_required = check_missing_required(service, env)
    if result.missing_required:
        result.success = False

    # Check deprecated keys
    result.deprecated_found = check_deprecated_keys(env)
    if result.deprecated_found and strict:
        result.success = False

    # Check case conflicts (Linux-specific issue)
    if check_conflicts:
        result.conflicts_found = check_case_conflicts(env)
        if result.conflicts_found:
            result.success = False

    # Add warnings for recommended vars
    recommended = get_service_recommended_vars(service)
    for var in recommended:
        if var not in env:
            result.warnings.append(f"Recommended variable not set: {var}")

    return result


# ==============================================================================
# OUTPUT FORMATTING
# ==============================================================================


def print_contract() -> None:
    """Print the canonical env contract."""
    print("=" * 70)
    print("DRAGONFLY CIVIL - CANONICAL ENVIRONMENT CONTRACT")
    print("=" * 70)
    print()
    print("SHARED REQUIRED (all services):")
    print("-" * 40)
    for var in CANONICAL_ENV_CONTRACT["shared_required"]:
        print(f"  [REQ] {var}")
    print()

    for service in ["api", "ingest", "enforcement", "simplicity"]:
        print(f"{service.upper()} SERVICE:")
        print("-" * 40)
        req = CANONICAL_ENV_CONTRACT.get(f"{service}_required", [])
        rec = CANONICAL_ENV_CONTRACT.get(f"{service}_recommended", [])
        if req:
            for var in req:
                print(f"  [REQ] {var}")
        if rec:
            for var in rec:
                print(f"  [REC] {var}")
        if not req and not rec:
            print("  (no additional requirements)")
        print()

    print("DEPRECATED KEYS (delete these):")
    print("-" * 40)
    for deprecated, canonical in sorted(DEPRECATED_KEYS.items()):
        print(f"  [DEL] {deprecated} -> {canonical}")
    print()


def print_result(result: AuditResult, service: str) -> None:
    """Print audit result with formatting."""
    print()
    print("=" * 70)
    print(f"ENVIRONMENT AUDIT: {service.upper()} SERVICE")
    print("=" * 70)
    print()

    if result.missing_required:
        print("[ERROR] MISSING REQUIRED VARIABLES:")
        for var in result.missing_required:
            print(f"   * {var}")
        print()

    if result.conflicts_found:
        print("[ERROR] CASE-SENSITIVE CONFLICTS (Linux will use both with different values!):")
        for lower, upper in result.conflicts_found:
            print(f"   * {lower} vs {upper}")
            print(f"     DELETE the lowercase version: {lower}")
        print()

    if result.deprecated_found:
        print("[WARN]  DEPRECATED KEYS FOUND (delete these):")
        for deprecated, canonical in result.deprecated_found.items():
            print(f"   * {deprecated} -> use {canonical}")
        print()

    if result.warnings:
        print("[INFO]  WARNINGS:")
        for warning in result.warnings:
            print(f"   * {warning}")
        print()

    if result.success:
        print("[OK] AUDIT PASSED")
    else:
        print("[FAIL] AUDIT FAILED")
        print(f"   Exit code: {result.exit_code}")

    print()


# ==============================================================================
# MAIN
# ==============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Railway environment audit for deterministic deployments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--service",
        choices=["api", "ingest", "enforcement", "simplicity"],
        default="api",
        help="Service to check requirements for (default: api)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI mode: fail on errors/collisions, return nonzero on warnings",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on any deprecated key usage",
    )
    parser.add_argument(
        "--check-conflicts",
        action="store_true",
        default=True,
        help="Check for case-sensitive key conflicts (default: True)",
    )
    parser.add_argument(
        "--print-contract",
        action="store_true",
        help="Print the canonical env contract and exit",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print on failure",
    )

    args = parser.parse_args()

    if args.print_contract:
        print_contract()
        return 0

    # --check implies checking all services in sequence
    if args.check:
        all_services = ["api", "ingest", "enforcement", "simplicity"]
        has_missing = False
        has_conflicts = False
        has_warnings = False

        for svc in all_services:
            result = run_audit(
                service=svc,
                strict=False,  # Don't fail on deprecated, just warn
                check_conflicts=True,
            )
            print_result(result, svc)

            # Track issue types separately
            if result.missing_required:
                has_missing = True
            if result.conflicts_found:
                has_conflicts = True
            if result.deprecated_found or result.warnings:
                has_warnings = True

        # In CI mode:
        # - Exit 3 on case conflicts (critical)
        # - Exit 1 on missing required vars (error)
        # - Exit 1 on warnings only (deprecated keys, missing recommended)
        # - Exit 0 on clean
        if has_conflicts:
            print("[CI] FAILED: Case-sensitive conflicts detected (exit 3)")
            return 3
        elif has_missing:
            print("[CI] FAILED: Missing required variables (exit 1)")
            return 1
        elif has_warnings:
            print("[CI] PASSED with warnings (deprecated keys or missing recommended vars)")
            return 1
        else:
            print("[CI] PASSED: All checks clean")
            return 0

    result = run_audit(
        service=args.service,
        strict=args.strict,
        check_conflicts=args.check_conflicts,
    )

    if not args.quiet or not result.success:
        print_result(result, args.service)

    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
