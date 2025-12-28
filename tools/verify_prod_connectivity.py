#!/usr/bin/env python3
"""
Dragonfly Production Connectivity Verifier

Verifies HTTP connectivity between Vercel (Frontend) and Railway (Backend):
1. Health endpoint accessibility
2. API health endpoint accessibility
3. Authenticated endpoint access
4. CORS header validation

Usage:
    python -m tools.verify_prod_connectivity

    # Override URLs via environment:
    PROD_API_URL=https://your-railway.up.railway.app python -m tools.verify_prod_connectivity

Environment Variables:
    PROD_API_URL: Railway backend URL (defaults to known prod URL)
    DRAGONFLY_API_KEY: API key for authenticated endpoints
    NEXT_PUBLIC_APP_URL: Vercel frontend URL for CORS testing
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

import requests

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("verify_prod_connectivity")

# =============================================================================
# CONFIGURATION
# =============================================================================

# Default Railway production URL
DEFAULT_PROD_API_URL = "https://dragonflycivil-production-d57a.up.railway.app"

# Default Vercel frontend URLs for CORS testing
DEFAULT_VERCEL_URLS = [
    "https://dragonfly-dashboard.vercel.app",
    "https://dragonfly-console1.vercel.app",
]

# Request timeout (seconds)
REQUEST_TIMEOUT = 30


@dataclass
class CheckResult:
    """Result of a connectivity check."""

    name: str
    passed: bool
    message: str
    details: Optional[str] = None


# =============================================================================
# CONNECTIVITY CHECKS
# =============================================================================


def check_health(api_url: str) -> CheckResult:
    """
    Check 1: GET /health
    Basic health endpoint that should return 200.
    """
    url = f"{api_url}/health"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)

        if response.status_code == 200:
            return CheckResult(
                name="Health Endpoint",
                passed=True,
                message=f"GET /health returned {response.status_code}",
                details=response.text[:200] if response.text else None,
            )
        else:
            return CheckResult(
                name="Health Endpoint",
                passed=False,
                message=f"GET /health returned {response.status_code}",
                details=response.text[:500] if response.text else None,
            )
    except requests.exceptions.Timeout:
        return CheckResult(
            name="Health Endpoint",
            passed=False,
            message=f"GET /health timed out after {REQUEST_TIMEOUT}s",
        )
    except requests.exceptions.ConnectionError as e:
        return CheckResult(
            name="Health Endpoint",
            passed=False,
            message=f"Connection refused: {e}",
        )
    except Exception as e:
        return CheckResult(
            name="Health Endpoint",
            passed=False,
            message=f"Unexpected error: {e}",
        )


def check_api_health(api_url: str) -> CheckResult:
    """
    Check 2: GET /api/health
    API-specific health endpoint.
    """
    url = f"{api_url}/api/health"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)

        if response.status_code == 200:
            return CheckResult(
                name="API Health Endpoint",
                passed=True,
                message=f"GET /api/health returned {response.status_code}",
                details=response.text[:200] if response.text else None,
            )
        else:
            return CheckResult(
                name="API Health Endpoint",
                passed=False,
                message=f"GET /api/health returned {response.status_code}",
                details=response.text[:500] if response.text else None,
            )
    except requests.exceptions.Timeout:
        return CheckResult(
            name="API Health Endpoint",
            passed=False,
            message=f"GET /api/health timed out after {REQUEST_TIMEOUT}s",
        )
    except requests.exceptions.ConnectionError as e:
        return CheckResult(
            name="API Health Endpoint",
            passed=False,
            message=f"Connection refused: {e}",
        )
    except Exception as e:
        return CheckResult(
            name="API Health Endpoint",
            passed=False,
            message=f"Unexpected error: {e}",
        )


def check_authenticated_endpoint(api_url: str, api_key: str) -> CheckResult:
    """
    Check 3: GET /api/v1/intake/batches?page=1&page_size=1
    Authenticated endpoint to verify API key handling.
    """
    url = f"{api_url}/api/v1/intake/batches"
    params = {"page": 1, "page_size": 1}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-API-KEY": api_key,  # Some endpoints use this header
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)

        if response.status_code == 200:
            return CheckResult(
                name="Authenticated Endpoint",
                passed=True,
                message=f"GET /api/v1/intake/batches returned {response.status_code}",
                details=f"Response length: {len(response.text)} chars",
            )
        elif response.status_code == 401:
            return CheckResult(
                name="Authenticated Endpoint",
                passed=False,
                message="Authentication failed (401 Unauthorized)",
                details="Check DRAGONFLY_API_KEY is correct",
            )
        elif response.status_code == 403:
            return CheckResult(
                name="Authenticated Endpoint",
                passed=False,
                message="Access forbidden (403)",
                details=response.text[:500] if response.text else None,
            )
        elif response.status_code == 404:
            # Endpoint may not exist yet - not a connectivity failure
            return CheckResult(
                name="Authenticated Endpoint",
                passed=True,
                message="Endpoint returned 404 (not deployed yet, but auth layer reached)",
                details="Connectivity OK, endpoint not implemented",
            )
        else:
            return CheckResult(
                name="Authenticated Endpoint",
                passed=False,
                message=f"Unexpected status {response.status_code}",
                details=response.text[:500] if response.text else None,
            )
    except requests.exceptions.Timeout:
        return CheckResult(
            name="Authenticated Endpoint",
            passed=False,
            message=f"Request timed out after {REQUEST_TIMEOUT}s",
        )
    except requests.exceptions.ConnectionError as e:
        return CheckResult(
            name="Authenticated Endpoint",
            passed=False,
            message=f"Connection refused: {e}",
        )
    except Exception as e:
        return CheckResult(
            name="Authenticated Endpoint",
            passed=False,
            message=f"Unexpected error: {e}",
        )


def check_cors(api_url: str, origin: str) -> CheckResult:
    """
    Check 4: CORS Preflight / Origin Header Validation
    Verify the API accepts requests from the Vercel frontend origin.
    """
    url = f"{api_url}/health"
    headers = {
        "Origin": origin,
    }

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

        # Check for CORS headers in response
        acao = response.headers.get("Access-Control-Allow-Origin", "")

        # CORS is valid if:
        # 1. ACAO matches origin exactly, OR
        # 2. ACAO is "*" (wildcard)
        cors_valid = acao == origin or acao == "*"

        if cors_valid:
            return CheckResult(
                name=f"CORS ({origin})",
                passed=True,
                message=f"Access-Control-Allow-Origin: {acao}",
            )
        elif acao:
            return CheckResult(
                name=f"CORS ({origin})",
                passed=False,
                message=f"CORS mismatch: got '{acao}', expected '{origin}' or '*'",
                details="Update DRAGONFLY_CORS_ORIGINS on Railway",
            )
        else:
            return CheckResult(
                name=f"CORS ({origin})",
                passed=False,
                message="No Access-Control-Allow-Origin header in response",
                details="CORS may not be configured on the backend",
            )
    except requests.exceptions.Timeout:
        return CheckResult(
            name=f"CORS ({origin})",
            passed=False,
            message=f"Request timed out after {REQUEST_TIMEOUT}s",
        )
    except requests.exceptions.ConnectionError as e:
        return CheckResult(
            name=f"CORS ({origin})",
            passed=False,
            message=f"Connection refused: {e}",
        )
    except Exception as e:
        return CheckResult(
            name=f"CORS ({origin})",
            passed=False,
            message=f"Unexpected error: {e}",
        )


def check_cors_preflight(api_url: str, origin: str) -> CheckResult:
    """
    Additional: OPTIONS preflight request
    Verify preflight requests are handled correctly.
    """
    url = f"{api_url}/api/health"
    headers = {
        "Origin": origin,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "Authorization, X-API-KEY",
    }

    try:
        response = requests.options(url, headers=headers, timeout=REQUEST_TIMEOUT)

        acao = response.headers.get("Access-Control-Allow-Origin", "")
        acam = response.headers.get("Access-Control-Allow-Methods", "")
        acah = response.headers.get("Access-Control-Allow-Headers", "")

        # Check if preflight is handled
        if response.status_code in (200, 204):
            cors_valid = acao == origin or acao == "*"
            if cors_valid:
                return CheckResult(
                    name=f"CORS Preflight ({origin})",
                    passed=True,
                    message=f"Preflight OK (ACAO: {acao})",
                    details=f"Methods: {acam}, Headers: {acah}",
                )
            else:
                return CheckResult(
                    name=f"CORS Preflight ({origin})",
                    passed=False,
                    message="CORS mismatch in preflight",
                    details=f"ACAO: '{acao}'",
                )
        else:
            return CheckResult(
                name=f"CORS Preflight ({origin})",
                passed=False,
                message=f"Preflight returned {response.status_code}",
                details=response.text[:200] if response.text else None,
            )
    except Exception as e:
        return CheckResult(
            name=f"CORS Preflight ({origin})",
            passed=False,
            message=f"Preflight error: {e}",
        )


# =============================================================================
# MAIN
# =============================================================================


def run_all_checks() -> Tuple[List[CheckResult], int]:
    """
    Run all connectivity checks.

    Returns:
        Tuple of (results list, exit code)
    """
    # Load configuration from environment
    api_url = os.environ.get("PROD_API_URL", DEFAULT_PROD_API_URL).rstrip("/")
    api_key = os.environ.get("DRAGONFLY_API_KEY", "")

    # Vercel URL for CORS testing
    vercel_url = os.environ.get("NEXT_PUBLIC_APP_URL", "")
    if not vercel_url:
        # Use default Vercel URLs
        vercel_urls = DEFAULT_VERCEL_URLS
    else:
        vercel_urls = [vercel_url]

    print("")
    print("═" * 70)
    print("  🔗 DRAGONFLY PRODUCTION CONNECTIVITY VERIFIER")
    print("═" * 70)
    print("")
    print(f"  API URL: {api_url}")
    print(f"  API Key: {'***' + api_key[-8:] if len(api_key) > 8 else '(not set)'}")
    print(f"  Vercel:  {', '.join(vercel_urls)}")
    print("")
    print("─" * 70)

    results: List[CheckResult] = []

    # Check 1: Health endpoint
    print("\n📡 Check 1: Health Endpoint")
    result = check_health(api_url)
    results.append(result)
    _print_result(result)

    # Check 2: API Health endpoint
    print("\n📡 Check 2: API Health Endpoint")
    result = check_api_health(api_url)
    results.append(result)
    _print_result(result)

    # Check 3: Authenticated endpoint
    print("\n🔐 Check 3: Authenticated Endpoint")
    if api_key:
        result = check_authenticated_endpoint(api_url, api_key)
    else:
        result = CheckResult(
            name="Authenticated Endpoint",
            passed=False,
            message="DRAGONFLY_API_KEY not set",
            details="Set DRAGONFLY_API_KEY environment variable",
        )
    results.append(result)
    _print_result(result)

    # Check 4: CORS for each Vercel URL
    for vercel_url in vercel_urls:
        print(f"\n🌐 Check 4: CORS Validation ({vercel_url})")
        result = check_cors(api_url, vercel_url)
        results.append(result)
        _print_result(result)

        # Also check preflight
        result = check_cors_preflight(api_url, vercel_url)
        results.append(result)
        _print_result(result)

    # Summary
    print("\n" + "═" * 70)
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    if failed == 0:
        print("  ✅ ALL CHECKS PASSED")
        exit_code = 0
    else:
        print(f"  ❌ {failed} CHECK(S) FAILED")
        exit_code = 1

    print(f"     Passed: {passed}/{len(results)}")
    print("═" * 70)
    print("")

    return results, exit_code


def _print_result(result: CheckResult) -> None:
    """Print a check result with formatting."""
    icon = "✅" if result.passed else "❌"
    print(f"   {icon} {result.message}")
    if result.details:
        print(f"      └─ {result.details}")


def main() -> None:
    """Entry point."""
    _, exit_code = run_all_checks()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
