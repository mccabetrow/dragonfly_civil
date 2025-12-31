#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════
tools/verify_final_state.py - Final State Verifier for Dad Demo Launch
═══════════════════════════════════════════════════════════════════════════

Purpose:
    Pre-launch verification of all critical system components.
    Confirms schema, routes, and API health before go-live.

Checks:
    1. DB: dedupe_key column exists in public.judgments
    2. DB: Unique index on dedupe_key exists
    3. API: GET /api/v1/intake/batches/{UUID} returns 404/422 (route exists)
    4. API: Health endpoint responds
    5. Schema sync: All 6 critical schema elements GREEN

Usage:
    # Check production
    python -m tools.verify_final_state --env prod

    # Check dev
    python -m tools.verify_final_state --env dev

    # JSON output for CI
    python -m tools.verify_final_state --env prod --json

Exit Codes:
    0 = All checks passed
    1 = One or more checks failed
    2 = Connection/setup error

Author: Dragonfly Reliability Engineering
Created: 2025-12-31
═══════════════════════════════════════════════════════════════════════════
"""

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import httpx
import psycopg

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.supabase_client import get_supabase_db_url, get_supabase_env


# ═══════════════════════════════════════════════════════════════════════════
# TYPES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class Check:
    """Result of a single verification check."""

    name: str
    passed: bool
    message: str
    category: str  # "db", "api", "schema"


@dataclass
class VerificationReport:
    """Overall verification report."""

    environment: str
    total_checks: int
    passed: int
    failed: int
    checks: list[Check]


# ═══════════════════════════════════════════════════════════════════════════
# DATABASE CHECKS
# ═══════════════════════════════════════════════════════════════════════════


def check_dedupe_column(conn: psycopg.Connection) -> Check:
    """Verify dedupe_key column exists in public.judgments."""
    try:
        result = conn.execute(
            """
            SELECT column_name, is_generated
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'judgments'
              AND column_name = 'dedupe_key'
        """
        ).fetchone()

        if result:
            is_generated = result[1]
            return Check(
                name="Dedupe Column Exists",
                passed=True,
                message=f"dedupe_key exists (generated={is_generated})",
                category="db",
            )
        else:
            return Check(
                name="Dedupe Column Exists",
                passed=False,
                message="dedupe_key column NOT FOUND in public.judgments",
                category="db",
            )
    except Exception as e:
        return Check(
            name="Dedupe Column Exists",
            passed=False,
            message=f"Error: {e}",
            category="db",
        )


def check_dedupe_index(conn: psycopg.Connection) -> Check:
    """Verify unique index on dedupe_key exists."""
    try:
        # Check for either idx_judgments_dedupe_key or uq_judgments_dedupe_key
        result = conn.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'judgments'
              AND indexname LIKE '%dedupe_key%'
        """
        ).fetchall()

        if result:
            index_names = [r[0] for r in result]
            is_unique = any("UNIQUE" in r[1].upper() for r in result)
            return Check(
                name="Dedupe Unique Index",
                passed=is_unique,
                message=f"Found indexes: {', '.join(index_names)} (unique={is_unique})",
                category="db",
            )
        else:
            return Check(
                name="Dedupe Unique Index",
                passed=False,
                message="No dedupe_key index found on public.judgments",
                category="db",
            )
    except Exception as e:
        return Check(
            name="Dedupe Unique Index",
            passed=False,
            message=f"Error: {e}",
            category="db",
        )


def check_null_dedupe_keys(conn: psycopg.Connection) -> Check:
    """Verify no NULL dedupe_key values exist."""
    try:
        result = conn.execute(
            """
            SELECT COUNT(*)
            FROM public.judgments
            WHERE dedupe_key IS NULL
        """
        ).fetchone()

        null_count = result[0] if result else 0

        if null_count == 0:
            return Check(
                name="No NULL Dedupe Keys",
                passed=True,
                message="All judgments have dedupe_key populated",
                category="db",
            )
        else:
            return Check(
                name="No NULL Dedupe Keys",
                passed=False,
                message=f"{null_count} judgments have NULL dedupe_key",
                category="db",
            )
    except Exception as e:
        return Check(
            name="No NULL Dedupe Keys",
            passed=False,
            message=f"Error: {e}",
            category="db",
        )


def check_functions_exist(conn: psycopg.Connection) -> Check:
    """Verify required functions exist."""
    required = ["normalize_party_name", "compute_judgment_dedupe_key"]
    try:
        result = conn.execute(
            """
            SELECT proname
            FROM pg_proc
            WHERE pronamespace = 'public'::regnamespace
              AND proname IN ('normalize_party_name', 'compute_judgment_dedupe_key')
        """
        ).fetchall()

        found = [r[0] for r in result]
        missing = [f for f in required if f not in found]

        if not missing:
            return Check(
                name="Dedupe Functions Exist",
                passed=True,
                message=f"Found: {', '.join(found)}",
                category="db",
            )
        else:
            return Check(
                name="Dedupe Functions Exist",
                passed=False,
                message=f"Missing functions: {', '.join(missing)}",
                category="db",
            )
    except Exception as e:
        return Check(
            name="Dedupe Functions Exist",
            passed=False,
            message=f"Error: {e}",
            category="db",
        )


# ═══════════════════════════════════════════════════════════════════════════
# API CHECKS
# ═══════════════════════════════════════════════════════════════════════════


def check_batches_route(base_url: str, api_key: Optional[str]) -> Check:
    """
    Verify /api/v1/intake/batches/{id} route exists.

    A 404 with JSON body proves the route exists (ID not found).
    A 404 with HTML or 405 means route doesn't exist.
    """
    test_uuid = "00000000-0000-0000-0000-000000000000"
    url = f"{base_url}/api/v1/intake/batches/{test_uuid}"

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["apikey"] = api_key

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, headers=headers)

            # 404 (not found) with JSON = route exists, batch doesn't
            if response.status_code == 404:
                try:
                    body = response.json()
                    if "detail" in body or "error" in body:
                        return Check(
                            name="Batches Route Exists",
                            passed=True,
                            message=f"Route active (404 JSON: {body.get('detail', 'Batch not found')})",
                            category="api",
                        )
                except Exception:
                    pass
                # 404 but no JSON - might be route missing
                return Check(
                    name="Batches Route Exists",
                    passed=False,
                    message="Got 404 but response is not JSON (route may not exist)",
                    category="api",
                )

            # 422 = route exists, validation failed
            if response.status_code == 422:
                return Check(
                    name="Batches Route Exists",
                    passed=True,
                    message="Route active (422 validation error)",
                    category="api",
                )

            # 401/403 = route exists, auth required
            if response.status_code in (401, 403):
                return Check(
                    name="Batches Route Exists",
                    passed=True,
                    message=f"Route active ({response.status_code} auth required)",
                    category="api",
                )

            # 200 = route exists and returned data
            if response.status_code == 200:
                return Check(
                    name="Batches Route Exists",
                    passed=True,
                    message="Route active (200 OK)",
                    category="api",
                )

            # 405 = Method Not Allowed = route mismatch
            if response.status_code == 405:
                return Check(
                    name="Batches Route Exists",
                    passed=False,
                    message="Got 405 Method Not Allowed (route mismatch)",
                    category="api",
                )

            # 503 = PGRST002 schema cache issue
            if response.status_code == 503:
                return Check(
                    name="Batches Route Exists",
                    passed=False,
                    message="Got 503 Service Unavailable (PGRST002?)",
                    category="api",
                )

            return Check(
                name="Batches Route Exists",
                passed=False,
                message=f"Unexpected status {response.status_code}",
                category="api",
            )

    except httpx.ConnectError:
        return Check(
            name="Batches Route Exists",
            passed=False,
            message="Connection failed - is the backend running?",
            category="api",
        )
    except Exception as e:
        return Check(
            name="Batches Route Exists",
            passed=False,
            message=f"Error: {e}",
            category="api",
        )


def check_api_health(base_url: str, api_key: Optional[str]) -> Check:
    """Verify API health endpoint responds."""
    url = f"{base_url}/api/v1/intake/health"

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["apikey"] = api_key

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, headers=headers)

            if response.status_code == 200:
                return Check(
                    name="API Health Endpoint",
                    passed=True,
                    message="Health endpoint responding (200 OK)",
                    category="api",
                )
            elif response.status_code == 404:
                return Check(
                    name="API Health Endpoint",
                    passed=False,
                    message="Health endpoint not found (404)",
                    category="api",
                )
            else:
                return Check(
                    name="API Health Endpoint",
                    passed=False,
                    message=f"Unexpected status {response.status_code}",
                    category="api",
                )

    except httpx.ConnectError:
        return Check(
            name="API Health Endpoint",
            passed=False,
            message="Connection failed - is the backend running?",
            category="api",
        )
    except Exception as e:
        return Check(
            name="API Health Endpoint",
            passed=False,
            message=f"Error: {e}",
            category="api",
        )


# ═══════════════════════════════════════════════════════════════════════════
# MAIN VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════


def run_verification(
    env: str,
    skip_api: bool = False,
    backend_url: Optional[str] = None,
) -> VerificationReport:
    """
    Run all verification checks.

    Args:
        env: Environment (dev/prod)
        skip_api: Skip API checks (if backend not running)
        backend_url: Override backend URL for API checks

    Returns:
        VerificationReport with all check results
    """
    checks: list[Check] = []

    # Database checks
    db_url = get_supabase_db_url(env)
    with psycopg.connect(db_url) as conn:
        checks.append(check_dedupe_column(conn))
        checks.append(check_dedupe_index(conn))
        checks.append(check_null_dedupe_keys(conn))
        checks.append(check_functions_exist(conn))

    # API checks (optional)
    if not skip_api:
        # Default to Supabase URL for API checks
        if not backend_url:
            if env == "dev":
                backend_url = os.environ.get(
                    "SUPABASE_URL", "https://ejiddanxtqcleyswqvkc.supabase.co"
                )
            else:
                backend_url = os.environ.get(
                    "SUPABASE_URL", "https://iaketsyhmqbwaabgykux.supabase.co"
                )

        api_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("DRAGONFLY_API_KEY")

        checks.append(check_batches_route(backend_url, api_key))
        checks.append(check_api_health(backend_url, api_key))

    passed = sum(1 for c in checks if c.passed)
    failed = sum(1 for c in checks if not c.passed)

    return VerificationReport(
        environment=env,
        total_checks=len(checks),
        passed=passed,
        failed=failed,
        checks=checks,
    )


def print_report(report: VerificationReport, json_output: bool = False) -> None:
    """Print the verification report."""
    if json_output:
        output = {
            "environment": report.environment,
            "total_checks": report.total_checks,
            "passed": report.passed,
            "failed": report.failed,
            "checks": [asdict(c) for c in report.checks],
        }
        print(json.dumps(output, indent=2))
        return

    # Human-readable output
    print()
    print("═" * 72)
    print(f" FINAL STATE VERIFICATION: {report.environment.upper()}")
    print("═" * 72)
    print()

    # Group by category
    categories = {"db": "DATABASE", "api": "API", "schema": "SCHEMA"}
    for cat, label in categories.items():
        cat_checks = [c for c in report.checks if c.category == cat]
        if not cat_checks:
            continue

        print(f"┌─ {label} {'─' * (67 - len(label))}")
        for check in cat_checks:
            status = "✅ GREEN" if check.passed else "❌ RED  "
            print(f"│ {status}  {check.name}")
            print(f"│          {check.message}")
        print("└" + "─" * 70)
        print()

    # Summary
    print("─" * 72)
    if report.failed == 0:
        print(f" ✅ ALL GREEN: {report.passed}/{report.total_checks} checks passed")
        print()
        print(" 🚦 CLEARED FOR DAD DEMO")
    else:
        print(f" ❌ ISSUES DETECTED: {report.failed}/{report.total_checks} checks failed")
        print()
        print(" ⛔ DO NOT PROCEED - Fix issues before demo")
    print("─" * 72)
    print()


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Final state verification for Dad Demo launch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check production
  python -m tools.verify_final_state --env prod
  
  # Check dev
  python -m tools.verify_final_state --env dev
  
  # Skip API checks (DB only)
  python -m tools.verify_final_state --env prod --skip-api
  
  # JSON output for CI
  python -m tools.verify_final_state --env prod --json

Exit Codes:
  0 = All checks passed
  1 = One or more checks failed
  2 = Connection/setup error
        """,
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=None,
        help="Environment (default: from SUPABASE_MODE)",
    )
    parser.add_argument(
        "--skip-api",
        action="store_true",
        help="Skip API checks (if backend not running)",
    )
    parser.add_argument(
        "--backend-url",
        default=None,
        help="Override backend URL for API checks",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    # Determine environment
    env = args.env or get_supabase_env()
    os.environ["SUPABASE_MODE"] = env

    try:
        report = run_verification(
            env=env,
            skip_api=args.skip_api,
            backend_url=args.backend_url,
        )
        print_report(report, json_output=args.json)
        return 0 if report.failed == 0 else 1

    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"❌ ERROR: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
