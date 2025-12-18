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
- Audits Railway service variables via Railway API (--railway mode)

Usage:
    python scripts/railway_env_audit.py [--service SERVICE] [--check]
    python scripts/railway_env_audit.py --railway [--project NAME]

Options:
    --service SERVICE   Check requirements for specific service
    --check             CI mode: fail on errors or collisions
    --railway           Audit Railway service variables via API
    --project NAME      Railway project name (default: dragonfly-civil)
    --dry-run           Show what would be checked without calling API

Exit Codes:
    0 - All checks passed
    1 - Missing required variables
    2 - Deprecated key collision detected
    3 - Case-sensitive conflict detected
    4 - Railway API error

Environment:
    RAILWAY_TOKEN       Required for --railway mode (Railway API token)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Literal

# ==============================================================================
# ENV CONTRACT DEFINITION (Single Source of Truth)
# ==============================================================================

# Service names as used in Railway
RAILWAY_SERVICES = {
    "api": "dragonfly-api",
    "ingest": "dragonfly-worker-ingest",
    "enforcement": "dragonfly-worker-enforcement",
}

# Canonical environment variables - UPPERCASE only
CANONICAL_ENV_CONTRACT: dict[str, list[str]] = {
    # Required for ALL services (should be Railway shared variables)
    "shared_required": [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_DB_URL",
        "ENVIRONMENT",
        "SUPABASE_MODE",
    ],
    # API-specific (service-level in Railway)
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
}

# Deprecated keys that should be removed
DEPRECATED_KEYS: dict[str, str] = {
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
CASE_CONFLICT_PAIRS: list[tuple[str, str]] = [
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
    service: str = "unknown"
    missing_required: list[str] = field(default_factory=list)
    deprecated_found: dict[str, str] = field(default_factory=dict)
    conflicts_found: list[tuple[str, str]] = field(default_factory=list)
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


@dataclass
class RailwayAuditResult:
    """Result of Railway API environment audit."""

    success: bool
    project: str = ""
    services: dict[str, AuditResult] = field(default_factory=dict)
    api_error: str | None = None

    @property
    def exit_code(self) -> int:
        if self.api_error:
            return 4
        worst = 0
        for result in self.services.values():
            worst = max(worst, result.exit_code)
        return worst


# ==============================================================================
# LOCAL AUDIT FUNCTIONS
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
        if var not in env or not env[var].strip():
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


def run_local_audit(
    service: str = "api",
    strict: bool = False,
    check_conflicts: bool = True,
) -> AuditResult:
    """Run local environment audit."""
    env = dict(os.environ)

    result = AuditResult(success=True, service=service)

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
        if var not in env or not env.get(var, "").strip():
            result.warnings.append(f"Recommended variable not set: {var}")

    return result


# ==============================================================================
# RAILWAY API AUDIT
# ==============================================================================


def fetch_railway_variables(project_name: str, token: str) -> dict[str, dict[str, str]]:
    """
    Fetch environment variables for all services in a Railway project.

    Returns: {service_name: {VAR_NAME: value, ...}}
    """
    import urllib.error
    import urllib.request

    # Railway GraphQL API endpoint
    api_url = "https://backboard.railway.app/graphql/v2"

    # GraphQL query to get project variables
    query = """
    query GetProjectVariables($projectId: String!) {
        project(id: $projectId) {
            id
            name
            services {
                edges {
                    node {
                        id
                        name
                        serviceVariables {
                            id
                            name
                            value
                        }
                    }
                }
            }
            sharedVariables {
                id
                name
                value
            }
        }
    }
    """

    # First, get project ID from name
    project_query = """
    query GetProjects {
        me {
            projects {
                edges {
                    node {
                        id
                        name
                    }
                }
            }
        }
    }
    """

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    # Get projects to find our project ID
    req_data = json.dumps({"query": project_query}).encode("utf-8")
    req = urllib.request.Request(api_url, data=req_data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"Railway API error {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Railway API connection error: {e.reason}") from e

    if "errors" in data:
        raise RuntimeError(f"Railway API error: {data['errors']}")

    # Find project ID
    project_id = None
    projects = data.get("data", {}).get("me", {}).get("projects", {}).get("edges", [])
    for edge in projects:
        node = edge.get("node", {})
        if node.get("name", "").lower() == project_name.lower():
            project_id = node.get("id")
            break

    if not project_id:
        available = [e["node"]["name"] for e in projects]
        raise RuntimeError(f"Project '{project_name}' not found. Available: {available}")

    # Get service variables
    req_data = json.dumps({"query": query, "variables": {"projectId": project_id}}).encode("utf-8")
    req = urllib.request.Request(api_url, data=req_data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"Railway API error {e.code}: {body}") from e

    if "errors" in data:
        raise RuntimeError(f"Railway API error: {data['errors']}")

    project_data = data.get("data", {}).get("project", {})

    # Get shared variables (apply to all services)
    shared_vars: dict[str, str] = {}
    for var in project_data.get("sharedVariables", []):
        name = var.get("name", "")
        value = var.get("value", "")
        if name:
            shared_vars[name] = value

    # Get per-service variables (merged with shared)
    result: dict[str, dict[str, str]] = {}
    services = project_data.get("services", {}).get("edges", [])
    for edge in services:
        node = edge.get("node", {})
        service_name = node.get("name", "")
        if not service_name:
            continue

        # Start with shared vars
        service_vars = dict(shared_vars)

        # Overlay service-specific vars
        for var in node.get("serviceVariables", []):
            name = var.get("name", "")
            value = var.get("value", "")
            if name:
                service_vars[name] = value

        result[service_name] = service_vars

    return result


def audit_railway_service(
    service_key: str,
    env: dict[str, str],
) -> AuditResult:
    """Audit a single Railway service's environment variables."""
    result = AuditResult(success=True, service=service_key)

    # Check missing required
    result.missing_required = check_missing_required(service_key, env)
    if result.missing_required:
        result.success = False

    # Check deprecated keys
    result.deprecated_found = check_deprecated_keys(env)
    if result.deprecated_found:
        result.success = False  # Strict mode for Railway

    # Check case conflicts
    result.conflicts_found = check_case_conflicts(env)
    if result.conflicts_found:
        result.success = False

    # Check recommended vars
    recommended = get_service_recommended_vars(service_key)
    for var in recommended:
        if var not in env or not env.get(var, "").strip():
            result.warnings.append(f"Recommended variable not set: {var}")

    return result


def run_railway_audit(
    project_name: str = "dragonfly-civil",
    dry_run: bool = False,
) -> RailwayAuditResult:
    """Audit Railway project environment variables via API."""
    token = os.getenv("RAILWAY_TOKEN", "").strip()
    if not token:
        return RailwayAuditResult(
            success=False,
            project=project_name,
            api_error="RAILWAY_TOKEN not set. Get a token from Railway Dashboard > Account Settings > Tokens.",
        )

    if dry_run:
        print(f"[DRY RUN] Would audit project: {project_name}")
        print(f"[DRY RUN] Services: {list(RAILWAY_SERVICES.values())}")
        print("[DRY RUN] Required vars per service:")
        for svc_key, svc_name in RAILWAY_SERVICES.items():
            required = get_service_required_vars(svc_key)
            print(f"  {svc_name}: {required}")
        return RailwayAuditResult(success=True, project=project_name)

    try:
        service_vars = fetch_railway_variables(project_name, token)
    except RuntimeError as e:
        return RailwayAuditResult(
            success=False,
            project=project_name,
            api_error=str(e),
        )

    result = RailwayAuditResult(success=True, project=project_name)

    # Map Railway service names to our internal keys
    railway_to_key = {v: k for k, v in RAILWAY_SERVICES.items()}

    for railway_name, env in service_vars.items():
        service_key = railway_to_key.get(railway_name)
        if not service_key:
            # Unknown service, skip
            continue

        service_result = audit_railway_service(service_key, env)
        result.services[railway_name] = service_result

        if not service_result.success:
            result.success = False

    # Check for missing services
    for svc_key, railway_name in RAILWAY_SERVICES.items():
        if railway_name not in result.services:
            result.services[railway_name] = AuditResult(
                success=False,
                service=svc_key,
                missing_required=["SERVICE NOT FOUND IN RAILWAY"],
            )
            result.success = False

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
    print("SHARED REQUIRED (all services - use Railway shared variables):")
    print("-" * 60)
    for var in CANONICAL_ENV_CONTRACT["shared_required"]:
        print(f"  [REQ] {var}")
    print()

    for service, railway_name in RAILWAY_SERVICES.items():
        print(f"{service.upper()} SERVICE ({railway_name}):")
        print("-" * 60)
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

    print("DEPRECATED KEYS (delete from Railway):")
    print("-" * 60)
    for deprecated, canonical in sorted(DEPRECATED_KEYS.items()):
        print(f"  [DEL] {deprecated} -> {canonical}")
    print()


def print_local_result(result: AuditResult) -> None:
    """Print local audit result with formatting."""
    print()
    print("=" * 70)
    print(f"LOCAL ENVIRONMENT AUDIT: {result.service.upper()} SERVICE")
    print("=" * 70)
    print()

    if result.missing_required:
        print("[ERROR] MISSING REQUIRED VARIABLES:")
        for var in result.missing_required:
            print(f"   ✗ {var}")
        print()

    if result.conflicts_found:
        print("[ERROR] CASE-SENSITIVE CONFLICTS (Linux will use both!):")
        for lower, upper in result.conflicts_found:
            print(f"   ✗ {lower} vs {upper}")
            print(f"     DELETE the lowercase version: {lower}")
        print()

    if result.deprecated_found:
        print("[WARN]  DEPRECATED KEYS FOUND (delete these):")
        for deprecated, canonical in result.deprecated_found.items():
            print(f"   ⚠ {deprecated} -> use {canonical}")
        print()

    if result.warnings:
        print("[INFO]  RECOMMENDATIONS:")
        for warning in result.warnings:
            print(f"   ○ {warning}")
        print()

    if result.success:
        print("[OK] AUDIT PASSED")
    else:
        print("[FAIL] AUDIT FAILED")
        print(f"   Exit code: {result.exit_code}")

    print()


def print_railway_result(result: RailwayAuditResult) -> None:
    """Print Railway audit result with formatting."""
    print()
    print("=" * 70)
    print(f"RAILWAY ENVIRONMENT AUDIT: {result.project}")
    print("=" * 70)
    print()

    if result.api_error:
        print("[ERROR] RAILWAY API ERROR:")
        print(f"   {result.api_error}")
        print()
        return

    all_passed = True
    for railway_name, svc_result in result.services.items():
        status = "PASS" if svc_result.success else "FAIL"
        color_status = f"[{status}]"
        print(f"{color_status} {railway_name}")

        if svc_result.missing_required:
            all_passed = False
            for var in svc_result.missing_required:
                print(f"      ✗ Missing: {var}")

        if svc_result.deprecated_found:
            all_passed = False
            for deprecated in svc_result.deprecated_found:
                print(f"      ⚠ Deprecated: {deprecated}")

        if svc_result.conflicts_found:
            all_passed = False
            for lower, upper in svc_result.conflicts_found:
                print(f"      ✗ Conflict: {lower} vs {upper}")

        if svc_result.warnings:
            for warning in svc_result.warnings:
                print(f"      ○ {warning}")

    print()
    if all_passed:
        print("[OK] ALL RAILWAY SERVICES PASSED")
    else:
        print("[FAIL] RAILWAY AUDIT FAILED")
        print("   Fix the issues above before deploying.")
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
        choices=["api", "ingest", "enforcement"],
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
        "--print-contract",
        action="store_true",
        help="Print the canonical env contract and exit",
    )
    parser.add_argument(
        "--railway",
        action="store_true",
        help="Audit Railway service variables via API (requires RAILWAY_TOKEN)",
    )
    parser.add_argument(
        "--project",
        default="dragonfly-civil",
        help="Railway project name (default: dragonfly-civil)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be checked without calling API",
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

    # Railway mode: audit via API
    if args.railway:
        result = run_railway_audit(
            project_name=args.project,
            dry_run=args.dry_run,
        )
        if not args.quiet or not result.success:
            print_railway_result(result)
        return result.exit_code

    # CI mode: check all services locally
    if args.check:
        all_services = ["api", "ingest", "enforcement"]
        has_missing = False
        has_conflicts = False
        has_warnings = False

        for svc in all_services:
            result = run_local_audit(
                service=svc,
                strict=False,
                check_conflicts=True,
            )
            print_local_result(result)

            if result.missing_required:
                has_missing = True
            if result.conflicts_found:
                has_conflicts = True
            if result.deprecated_found or result.warnings:
                has_warnings = True

        # Exit codes:
        # 3 - Case conflicts (critical)
        # 1 - Missing required or warnings
        # 0 - Clean
        if has_conflicts:
            print("[CI] FAILED: Case-sensitive conflicts detected (exit 3)")
            return 3
        elif has_missing:
            print("[CI] FAILED: Missing required variables (exit 1)")
            return 1
        elif has_warnings:
            print("[CI] PASSED with warnings (deprecated keys or missing recommended)")
            return 1
        else:
            print("[CI] PASSED: All checks clean")
            return 0

    # Single service local audit
    result = run_local_audit(
        service=args.service,
        strict=args.strict,
        check_conflicts=True,
    )

    if not args.quiet or not result.success:
        print_local_result(result)

    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
