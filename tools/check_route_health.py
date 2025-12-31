#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════
tools/check_route_health.py - API Route Health Verifier
═══════════════════════════════════════════════════════════════════════════

Purpose:
    Verify that critical API routes exist and respond correctly.
    Detects route mismatches between frontend expectations and backend reality.

Logic:
    - Request GET /api/v1/intake/batches/{dummy_uuid}
    - 404 (Not Found) → PASS (Route exists, ID doesn't)
    - 200 (OK) → PASS (Route exists and responded)
    - 405 (Method Not Allowed) → FAIL (Route mismatch)
    - 307 (Redirect) → FAIL (Route mismatch / trailing slash issue)
    - Other → WARN (Unexpected status)

Usage:
    # Check against local dev server
    python -m tools.check_route_health --base-url http://localhost:8000

    # Check against production
    python -m tools.check_route_health --env prod

    # Verbose output
    python -m tools.check_route_health --verbose

Exit Codes:
    0 = All routes healthy
    1 = One or more routes failed
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

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════════════════════
# TYPES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class RouteCheck:
    """Result of a single route health check."""

    route: str
    method: str
    status_code: int
    passed: bool
    message: str


@dataclass
class RouteHealthReport:
    """Overall route health report."""

    base_url: str
    total_routes: int
    passed: int
    failed: int
    checks: list[RouteCheck]


# ═══════════════════════════════════════════════════════════════════════════
# ROUTE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════

# Routes to verify: (method, path, expected_status_codes_for_pass)
CRITICAL_ROUTES = [
    ("GET", "/api/v1/intake/batches/00000000-0000-0000-0000-000000000000", [404, 200, 401, 403]),
    ("GET", "/api/v1/intake/batches", [200, 401, 403]),
    ("GET", "/api/v1/intake/health", [200]),
    ("GET", "/api/v1/intake/state", [200, 401, 403]),
]


# ═══════════════════════════════════════════════════════════════════════════
# HEALTH CHECK LOGIC
# ═══════════════════════════════════════════════════════════════════════════


def check_route(
    base_url: str, method: str, path: str, expected_codes: list[int], headers: dict
) -> RouteCheck:
    """
    Check if a route exists and responds correctly.

    Args:
        base_url: API base URL
        method: HTTP method
        path: Route path
        expected_codes: Status codes that indicate success
        headers: Request headers (for auth)

    Returns:
        RouteCheck result
    """
    import httpx

    url = f"{base_url.rstrip('/')}{path}"

    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            response = client.request(method, url, headers=headers)
            status = response.status_code

            # Determine pass/fail
            if status in expected_codes:
                return RouteCheck(
                    route=path,
                    method=method,
                    status_code=status,
                    passed=True,
                    message=f"OK - Route exists (status {status})",
                )
            elif status == 405:
                return RouteCheck(
                    route=path,
                    method=method,
                    status_code=status,
                    passed=False,
                    message="FAIL - Method Not Allowed (route mismatch)",
                )
            elif status == 307 or status == 308:
                location = response.headers.get("location", "unknown")
                return RouteCheck(
                    route=path,
                    method=method,
                    status_code=status,
                    passed=False,
                    message=f"FAIL - Redirect to {location} (trailing slash issue?)",
                )
            else:
                return RouteCheck(
                    route=path,
                    method=method,
                    status_code=status,
                    passed=True,  # Unexpected but route exists
                    message=f"WARN - Unexpected status {status}",
                )

    except httpx.ConnectError as e:
        return RouteCheck(
            route=path,
            method=method,
            status_code=0,
            passed=False,
            message=f"FAIL - Connection refused: {e}",
        )
    except Exception as e:
        return RouteCheck(
            route=path,
            method=method,
            status_code=0,
            passed=False,
            message=f"FAIL - Error: {e}",
        )


def run_route_health_check(base_url: str, api_key: str | None = None) -> RouteHealthReport:
    """
    Run health checks on all critical routes.

    Args:
        base_url: API base URL
        api_key: Optional API key for authentication

    Returns:
        RouteHealthReport with all check results
    """
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["apikey"] = api_key

    checks: list[RouteCheck] = []

    for method, path, expected_codes in CRITICAL_ROUTES:
        check = check_route(base_url, method, path, expected_codes, headers)
        checks.append(check)

    passed = sum(1 for c in checks if c.passed)
    failed = sum(1 for c in checks if not c.passed)

    return RouteHealthReport(
        base_url=base_url,
        total_routes=len(checks),
        passed=passed,
        failed=failed,
        checks=checks,
    )


def print_report(report: RouteHealthReport, json_output: bool = False) -> None:
    """Print the health check report."""
    if json_output:
        output = {
            "base_url": report.base_url,
            "total_routes": report.total_routes,
            "passed": report.passed,
            "failed": report.failed,
            "checks": [asdict(c) for c in report.checks],
        }
        print(json.dumps(output, indent=2))
        return

    # Human-readable output
    print()
    print("═" * 72)
    print(f" ROUTE HEALTH CHECK: {report.base_url}")
    print("═" * 72)
    print()

    for check in report.checks:
        if check.passed:
            status = "✅"
        else:
            status = "❌"
        print(f"  {status} {check.method:6} {check.route}")
        print(f"       {check.message}")
    print()

    # Summary
    print("─" * 72)
    if report.failed == 0:
        print(f" ✅ ALL ROUTES HEALTHY: {report.passed}/{report.total_routes}")
    else:
        print(f" ❌ ROUTE ISSUES DETECTED: {report.failed}/{report.total_routes} failed")
    print("─" * 72)
    print()


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check API route health and detect route mismatches"
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="API base URL (default: from environment)",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=None,
        help="Environment (overrides --base-url with Supabase URL)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output",
    )
    args = parser.parse_args()

    # Determine base URL
    if args.env:
        from src.supabase_client import get_supabase_env

        env = args.env
        if env == "dev":
            base_url = os.environ.get("SUPABASE_URL", "https://ejiddanxtqcleyswqvkc.supabase.co")
        else:
            base_url = os.environ.get("SUPABASE_URL", "https://iaketsyhmqbwaabgykux.supabase.co")
    elif args.base_url:
        base_url = args.base_url
    else:
        base_url = os.environ.get("API_BASE_URL", "http://localhost:8000")

    # Get API key from environment
    api_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("DRAGONFLY_API_KEY")

    if args.verbose:
        print(f"Checking routes at: {base_url}")
        if api_key:
            print(f"Using API key: {api_key[:20]}...")

    try:
        report = run_route_health_check(base_url, api_key)
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
