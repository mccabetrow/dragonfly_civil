#!/usr/bin/env python3
"""
Deployment Smoke Test - World-Class Certification Verifier
===========================================================

Verifies that a deployment meets all "World-Class" invariants:
1. Liveness: GET /health -> 200 OK
2. Readiness: GET /readyz -> 200 OK (DB connected)
3. Traceability: X-Dragonfly-SHA header exists and is not "unknown"
4. Security: CORS headers are correctly configured
5. Latency: Health checks respond in < 500ms

Usage:
    python -m tools.smoke_deploy --url https://api.example.com
    python -m tools.smoke_deploy --url https://api.example.com --prefix /api
    python -m tools.smoke_deploy --url https://api.example.com --origin https://dashboard.example.com
    python -m tools.smoke_deploy --url https://api.example.com --verbose

Exit Codes:
    0 - All checks passed
    1 - One or more checks failed
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

# =============================================================================
# Constants
# =============================================================================

DEFAULT_TIMEOUT = 10.0  # seconds
LATENCY_THRESHOLD_MS = 500  # milliseconds
REQUIRED_HEADERS = ["X-Dragonfly-SHA"]


class CheckStatus(str, Enum):
    """Status of an individual check."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class CheckResult:
    """Result of a single verification check."""

    name: str
    status: CheckStatus
    message: str
    latency_ms: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SmokeTestResult:
    """Aggregate result of all smoke tests."""

    url: str
    sha: str | None = None
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True if all checks passed (skipped checks don't count as failures)."""
        return all(c.status != CheckStatus.FAIL for c in self.checks)

    @property
    def failed_checks(self) -> list[CheckResult]:
        """List of failed checks."""
        return [c for c in self.checks if c.status == CheckStatus.FAIL]

    def summary(self) -> str:
        """Generate a summary string."""
        passed = sum(1 for c in self.checks if c.status == CheckStatus.PASS)
        failed = sum(1 for c in self.checks if c.status == CheckStatus.FAIL)
        skipped = sum(1 for c in self.checks if c.status == CheckStatus.SKIP)
        return f"{passed} passed, {failed} failed, {skipped} skipped"


# =============================================================================
# Check Functions
# =============================================================================


def check_liveness(client: httpx.Client, base_url: str, prefix: str = "") -> CheckResult:
    """
    Check 1: Liveness Probe
    GET /health -> 200 OK
    """
    url = f"{base_url.rstrip('/')}{prefix}/health"

    try:
        start = time.perf_counter()
        response = client.get(url)
        latency_ms = (time.perf_counter() - start) * 1000

        if response.status_code == 200:
            return CheckResult(
                name="Liveness",
                status=CheckStatus.PASS,
                message=f"GET /health -> 200 OK ({latency_ms:.0f}ms)",
                latency_ms=latency_ms,
                details={"status_code": 200, "body": response.text[:200]},
            )
        else:
            return CheckResult(
                name="Liveness",
                status=CheckStatus.FAIL,
                message=f"GET /health -> {response.status_code} (expected 200)",
                latency_ms=latency_ms,
                details={"status_code": response.status_code, "body": response.text[:500]},
            )

    except httpx.RequestError as e:
        return CheckResult(
            name="Liveness",
            status=CheckStatus.FAIL,
            message=f"Connection failed: {e}",
            details={"error": str(e)},
        )


def check_readiness(client: httpx.Client, base_url: str, prefix: str = "") -> CheckResult:
    """
    Check 2: Readiness Probe
    GET /readyz -> 200 OK (with DB connected)
    """
    url = f"{base_url.rstrip('/')}{prefix}/readyz"

    try:
        start = time.perf_counter()
        response = client.get(url)
        latency_ms = (time.perf_counter() - start) * 1000

        if response.status_code == 200:
            try:
                data = response.json()
                db_status = data.get("services", {}).get("database", "unknown")
            except Exception:
                db_status = "unknown"

            return CheckResult(
                name="Readiness",
                status=CheckStatus.PASS,
                message=f"GET /readyz -> 200 OK, DB: {db_status} ({latency_ms:.0f}ms)",
                latency_ms=latency_ms,
                details={"status_code": 200, "database": db_status},
            )
        elif response.status_code == 503:
            try:
                data = response.json()
                reason = data.get("reason", "unknown")
            except Exception:
                reason = "unknown"

            return CheckResult(
                name="Readiness",
                status=CheckStatus.FAIL,
                message=f"Service not ready: {reason}",
                latency_ms=latency_ms,
                details={"status_code": 503, "reason": reason},
            )
        else:
            return CheckResult(
                name="Readiness",
                status=CheckStatus.FAIL,
                message=f"GET /readyz -> {response.status_code} (expected 200)",
                latency_ms=latency_ms,
                details={"status_code": response.status_code, "body": response.text[:500]},
            )

    except httpx.RequestError as e:
        return CheckResult(
            name="Readiness",
            status=CheckStatus.FAIL,
            message=f"Connection failed: {e}",
            details={"error": str(e)},
        )


def check_traceability(
    client: httpx.Client, base_url: str, prefix: str = ""
) -> tuple[CheckResult, str | None]:
    """
    Check 3: Traceability
    Assert X-Dragonfly-SHA header exists and is not "unknown"
    """
    url = f"{base_url.rstrip('/')}{prefix}/health"

    try:
        response = client.get(url)

        sha = response.headers.get("X-Dragonfly-SHA")

        if sha is None:
            return (
                CheckResult(
                    name="Traceability",
                    status=CheckStatus.FAIL,
                    message="Missing X-Dragonfly-SHA header",
                    details={"headers": dict(response.headers)},
                ),
                None,
            )

        if sha.lower() == "unknown":
            return (
                CheckResult(
                    name="Traceability",
                    status=CheckStatus.FAIL,
                    message="X-Dragonfly-SHA is 'unknown' (version not resolved)",
                    details={"sha": sha},
                ),
                sha,
            )

        if len(sha) < 7:
            return (
                CheckResult(
                    name="Traceability",
                    status=CheckStatus.FAIL,
                    message=f"X-Dragonfly-SHA too short: '{sha}' (expected 7+ chars)",
                    details={"sha": sha},
                ),
                sha,
            )

        return (
            CheckResult(
                name="Traceability",
                status=CheckStatus.PASS,
                message=f"X-Dragonfly-SHA: {sha}",
                details={"sha": sha},
            ),
            sha,
        )

    except httpx.RequestError as e:
        return (
            CheckResult(
                name="Traceability",
                status=CheckStatus.FAIL,
                message=f"Connection failed: {e}",
                details={"error": str(e)},
            ),
            None,
        )


def check_cors(
    client: httpx.Client, base_url: str, origin: str | None = None, prefix: str = ""
) -> CheckResult:
    """
    Check 4: CORS Security
    If origin is provided, verify Access-Control-Allow-Origin is correctly configured.
    """
    if origin is None:
        return CheckResult(
            name="CORS Security",
            status=CheckStatus.SKIP,
            message="No --origin provided, skipping CORS check",
        )

    url = f"{base_url.rstrip('/')}{prefix}/health"

    try:
        # Send preflight OPTIONS request
        response = client.options(
            url,
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )

        allow_origin = response.headers.get("Access-Control-Allow-Origin")

        # Also check a regular GET with Origin header
        get_response = client.get(url, headers={"Origin": origin})
        get_allow_origin = get_response.headers.get("Access-Control-Allow-Origin")

        # CORS should either:
        # 1. Return the exact origin (strict)
        # 2. Return * (permissive - not recommended for prod)
        # 3. Not return the header (blocked)

        if allow_origin == origin or get_allow_origin == origin:
            return CheckResult(
                name="CORS Security",
                status=CheckStatus.PASS,
                message=f"Origin '{origin}' is allowed",
                details={
                    "origin": origin,
                    "allow_origin_preflight": allow_origin,
                    "allow_origin_get": get_allow_origin,
                },
            )
        elif allow_origin == "*" or get_allow_origin == "*":
            return CheckResult(
                name="CORS Security",
                status=CheckStatus.PASS,
                message="CORS allows all origins (*) - verify this is intended",
                details={
                    "origin": origin,
                    "allow_origin_preflight": allow_origin,
                    "allow_origin_get": get_allow_origin,
                    "warning": "Wildcard CORS is not recommended for production",
                },
            )
        elif allow_origin is None and get_allow_origin is None:
            return CheckResult(
                name="CORS Security",
                status=CheckStatus.FAIL,
                message=f"Origin '{origin}' is NOT allowed (no CORS header returned)",
                details={
                    "origin": origin,
                    "allow_origin_preflight": allow_origin,
                    "allow_origin_get": get_allow_origin,
                },
            )
        else:
            return CheckResult(
                name="CORS Security",
                status=CheckStatus.FAIL,
                message=f"CORS mismatch: expected '{origin}', got '{allow_origin or get_allow_origin}'",
                details={
                    "origin": origin,
                    "allow_origin_preflight": allow_origin,
                    "allow_origin_get": get_allow_origin,
                },
            )

    except httpx.RequestError as e:
        return CheckResult(
            name="CORS Security",
            status=CheckStatus.FAIL,
            message=f"Connection failed: {e}",
            details={"error": str(e)},
        )


def check_latency(checks: list[CheckResult]) -> CheckResult:
    """
    Check 5: Latency
    Assert health check response times are < 500ms
    """
    latency_checks = [c for c in checks if c.latency_ms is not None]

    if not latency_checks:
        return CheckResult(
            name="Latency",
            status=CheckStatus.SKIP,
            message="No latency data available",
        )

    slow_checks = [c for c in latency_checks if c.latency_ms > LATENCY_THRESHOLD_MS]

    if slow_checks:
        slow_names = [f"{c.name} ({c.latency_ms:.0f}ms)" for c in slow_checks]
        return CheckResult(
            name="Latency",
            status=CheckStatus.FAIL,
            message=f"Slow responses (>{LATENCY_THRESHOLD_MS}ms): {', '.join(slow_names)}",
            details={"threshold_ms": LATENCY_THRESHOLD_MS, "slow_checks": slow_names},
        )

    max_latency = max(c.latency_ms for c in latency_checks)
    return CheckResult(
        name="Latency",
        status=CheckStatus.PASS,
        message=f"All responses < {LATENCY_THRESHOLD_MS}ms (max: {max_latency:.0f}ms)",
        latency_ms=max_latency,
        details={"threshold_ms": LATENCY_THRESHOLD_MS, "max_latency_ms": max_latency},
    )


# =============================================================================
# Main Smoke Test Runner
# =============================================================================


def run_smoke_test(
    url: str,
    origin: str | None = None,
    prefix: str = "",
    timeout: float = DEFAULT_TIMEOUT,
    verbose: bool = False,
) -> SmokeTestResult:
    """
    Run all smoke test checks against the target URL.

    Args:
        url: Target API base URL
        origin: Optional origin header for CORS testing
        prefix: API prefix (e.g., "/api" if health is at /api/health)
        timeout: Request timeout in seconds
        verbose: Print detailed output

    Returns:
        SmokeTestResult with all check results
    """
    result = SmokeTestResult(url=url)

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        # Check 1: Liveness
        liveness = check_liveness(client, url, prefix)
        result.checks.append(liveness)
        if verbose:
            print(f"  [{liveness.status.value.upper()}] {liveness.name}: {liveness.message}")

        # Check 2: Readiness
        readiness = check_readiness(client, url, prefix)
        result.checks.append(readiness)
        if verbose:
            print(f"  [{readiness.status.value.upper()}] {readiness.name}: {readiness.message}")

        # Check 3: Traceability
        traceability, sha = check_traceability(client, url, prefix)
        result.checks.append(traceability)
        result.sha = sha
        if verbose:
            print(
                f"  [{traceability.status.value.upper()}] {traceability.name}: {traceability.message}"
            )

        # Check 4: CORS
        cors = check_cors(client, url, origin, prefix)
        result.checks.append(cors)
        if verbose:
            print(f"  [{cors.status.value.upper()}] {cors.name}: {cors.message}")

        # Check 5: Latency (aggregates from previous checks)
        latency = check_latency(result.checks)
        result.checks.append(latency)
        if verbose:
            print(f"  [{latency.status.value.upper()}] {latency.name}: {latency.message}")

    return result


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Deployment Smoke Test - Verify World-Class Invariants",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m tools.smoke_deploy --url https://api.dragonfly.example.com
    python -m tools.smoke_deploy --url https://api.example.com --origin https://dashboard.example.com
    python -m tools.smoke_deploy --url http://localhost:8000 --verbose
        """,
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Target API base URL (e.g., https://api.example.com)",
    )
    parser.add_argument(
        "--prefix",
        default="",
        help="API prefix for health endpoints (e.g., '/api' if health is at /api/health)",
    )
    parser.add_argument(
        "--origin",
        help="Origin header to test CORS configuration (e.g., https://dashboard.example.com)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print detailed output for each check",
    )

    args = parser.parse_args()

    # Normalize prefix
    prefix = args.prefix.rstrip("/") if args.prefix else ""

    print("=" * 60)
    print("  🐉 DRAGONFLY DEPLOYMENT SMOKE TEST")
    print("=" * 60)
    print(f"  Target: {args.url}")
    if prefix:
        print(f"  Prefix: {prefix}")
    if args.origin:
        print(f"  Origin: {args.origin}")
    print("=" * 60)
    print()

    # Run smoke tests
    result = run_smoke_test(
        url=args.url,
        origin=args.origin,
        prefix=prefix,
        timeout=args.timeout,
        verbose=args.verbose,
    )

    print()
    print("=" * 60)

    if result.passed:
        sha_display = result.sha or "unknown"
        print(f"  ✅ DEPLOYMENT VERIFIED (SHA: {sha_display})")
        print(f"     {result.summary()}")
        print("=" * 60)
        return 0
    else:
        print("  ❌ SMOKE TEST FAILED")
        print()
        for check in result.failed_checks:
            print(f"     • {check.name}: {check.message}")
        print()
        print(f"     {result.summary()}")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
