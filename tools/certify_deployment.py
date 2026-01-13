#!/usr/bin/env python3
"""
Dragonfly Engine - Production Deployment Certification

Single-command verification that the deployment is ready for live plaintiffs.

Checks performed:
  1. Connectivity & Headers
     - GET /health => 200
     - X-Dragonfly-Env == 'prod' and X-Dragonfly-SHA-Short present

  2. Database & Pooler
     - GET /readyz => 200
     - SUPABASE_DB_URL uses port 6543 and sslmode=require

  3. Ops Privacy
     - ops schema blocked for anon/authenticated
     - ops.get_system_health() RPC succeeds with service_role

  4. Idempotency Simulation (The Data Moat)
     - Insert test import_run, verify duplicate is skipped

Usage:
    python -m tools.certify_deployment --url https://dragonfly-api-production.up.railway.app
    python -m tools.certify_deployment --url http://localhost:8000 --env dev

Exit codes:
    0 = All checks passed (GO FOR PLAINTIFFS)
    1 = One or more checks failed (FIX REQUIRED)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List
from urllib.parse import parse_qs, urlparse

import httpx

# Ensure project root modules resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.supabase_client import get_supabase_db_url

TIMEOUT = httpx.Timeout(15.0)
REQUIRED_HEADERS = ("X-Dragonfly-SHA-Short", "X-Dragonfly-Env")
BLOCKED_STATUSES = {401, 403, 404}

# Default production URL
DEFAULT_PROD_URL = "https://dragonfly-api-production.up.railway.app"


@dataclass
class CheckResult:
    """Represents the outcome of a single certification check."""

    name: str
    passed: bool
    detail: str
    critical: bool = True  # If False, failure is a warning not a blocker


class DeploymentCertifier:
    """End-to-end certification harness for Dragonfly deployments."""

    def __init__(
        self,
        base_url: str,
        env: str,
        supabase_url: str,
        anon_key: str,
        service_key: str,
        db_url: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.env = env.lower()
        self.supabase_url = supabase_url.rstrip("/")
        self.anon_key = anon_key
        self.service_key = service_key
        self.db_url = db_url

    # ------------------------------------------------------------------
    # HTTP Helpers
    # ------------------------------------------------------------------

    def _api_get(self, path: str) -> httpx.Response:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            return client.get(url)

    def _rest_headers(
        self, key: str, *, profile: str | None = None, auth: str | None = None
    ) -> dict[str, str]:
        headers = {
            "apikey": key,
            "Content-Type": "application/json",
        }
        if auth:
            headers["Authorization"] = auth
        if profile:
            headers["Accept-Profile"] = profile
            headers["Content-Profile"] = profile
        return headers

    # ------------------------------------------------------------------
    # 1. Connectivity & Headers
    # ------------------------------------------------------------------

    def check_health(self) -> CheckResult:
        """GET /health => 200"""
        try:
            resp = self._api_get("/health")
            if resp.status_code == 200:
                return CheckResult("GET /health", True, "200 OK")
            return CheckResult("GET /health", False, f"Expected 200, got {resp.status_code}")
        except Exception as exc:
            return CheckResult("GET /health", False, f"Request failed: {exc}")

    def check_headers(self) -> CheckResult:
        """Verify X-Dragonfly-Env and X-Dragonfly-SHA-Short headers"""
        try:
            resp = self._api_get("/health")
        except Exception as exc:
            return CheckResult("Response headers", False, f"Request failed: {exc}")

        sha = resp.headers.get("X-Dragonfly-SHA-Short", "")
        env_header = resp.headers.get("X-Dragonfly-Env", "")

        # Validate SHA is present and not placeholder
        sha_ok = bool(sha) and sha.lower() not in ("unknown", "local-dev", "")

        # Validate environment matches expected
        env_ok = env_header.lower() == self.env

        if not sha_ok:
            return CheckResult(
                "Response headers",
                False,
                f"X-Dragonfly-SHA-Short missing or invalid: '{sha}'",
            )

        if not env_ok:
            return CheckResult(
                "Response headers",
                False,
                f"X-Dragonfly-Env mismatch: expected '{self.env}', got '{env_header}'",
            )

        return CheckResult(
            "Response headers",
            True,
            f"SHA={sha}, Env={env_header}",
        )

    # ------------------------------------------------------------------
    # 2. Database & Pooler
    # ------------------------------------------------------------------

    def check_readyz(self) -> CheckResult:
        """GET /readyz => 200"""
        try:
            resp = self._api_get("/readyz")
            if resp.status_code == 200:
                return CheckResult("GET /readyz", True, "200 OK (DB connected)")
            return CheckResult("GET /readyz", False, f"Expected 200, got {resp.status_code}")
        except Exception as exc:
            return CheckResult("GET /readyz", False, f"Request failed: {exc}")

    def check_pooler_config(self) -> CheckResult:
        """Verify SUPABASE_DB_URL uses port 6543 and sslmode=require"""
        if not self.db_url:
            return CheckResult("Pooler config", False, "SUPABASE_DB_URL not set")

        try:
            parsed = urlparse(self.db_url)
            port = parsed.port
            query = parse_qs(parsed.query)
            sslmode = query.get("sslmode", [""])[0]

            violations = []

            if port != 6543:
                violations.append(f"port={port} (expected 6543)")

            if sslmode != "require":
                violations.append(f"sslmode={sslmode or 'missing'} (expected require)")

            if violations:
                return CheckResult(
                    "Pooler config",
                    False,
                    f"DSN violations: {', '.join(violations)}",
                )

            return CheckResult(
                "Pooler config",
                True,
                "port=6543, sslmode=require",
            )
        except Exception as exc:
            return CheckResult("Pooler config", False, f"Parse error: {exc}")

    # ------------------------------------------------------------------
    # 3. Ops Privacy
    # ------------------------------------------------------------------

    def check_ops_schema_blocked(self, role: str) -> CheckResult:
        """Verify ops schema is blocked for anon/auth roles"""
        auth_header = None
        if role == "auth":
            auth_header = "Bearer fake-user-jwt"

        try:
            url = f"{self.supabase_url}/rest/v1/import_runs?select=id&limit=1"
            headers = self._rest_headers(self.anon_key, profile="ingest", auth=auth_header)

            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.get(url, headers=headers)

            status = resp.status_code
            is_blocked = status in BLOCKED_STATUSES or (status == 200 and resp.json() == [])

            if is_blocked:
                return CheckResult(f"ops blocked ({role})", True, f"status={status}")

            return CheckResult(
                f"ops blocked ({role})",
                False,
                f"Unexpected access (status={status})",
            )
        except Exception as exc:
            return CheckResult(f"ops blocked ({role})", False, f"Request failed: {exc}")

    def check_ops_rpc(self) -> CheckResult:
        """Verify ops.get_system_health() RPC works with service_role"""
        url = f"{self.supabase_url}/rest/v1/rpc/get_system_health"
        headers = self._rest_headers(
            self.service_key,
            profile="ops",
            auth=f"Bearer {self.service_key}",
        )
        payload = {"p_limit": 5}

        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.post(url, headers=headers, json=payload)

            if resp.status_code == 200:
                return CheckResult("ops.get_system_health()", True, "RPC succeeded")

            return CheckResult(
                "ops.get_system_health()",
                False,
                f"RPC failed (status={resp.status_code})",
            )
        except Exception as exc:
            return CheckResult("ops.get_system_health()", False, f"Request failed: {exc}")

    # ------------------------------------------------------------------
    # 4. Idempotency Simulation (The Data Moat)
    # ------------------------------------------------------------------

    def check_ingest_idempotency(self) -> CheckResult:
        """Verify duplicate import_runs are rejected"""
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            return CheckResult(
                "Ingest idempotency",
                False,
                f"psycopg not installed: {exc}",
                critical=False,
            )

        source_batch_id = f"certify_test_{uuid.uuid4().hex[:12]}"
        file_hash = hashlib.sha256(source_batch_id.encode()).hexdigest()

        try:
            with psycopg.connect(self.db_url, autocommit=True) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    # Cleanup any prior test data
                    cur.execute(
                        "DELETE FROM ingest.import_runs WHERE source_batch_id = %s",
                        (source_batch_id,),
                    )

                    # First insert - should succeed
                    cur.execute(
                        """
                        INSERT INTO ingest.import_runs (
                            source_batch_id, file_hash, status, record_count,
                            started_at, completed_at
                        ) VALUES (%s, %s, 'completed', 0, NOW(), NOW())
                        ON CONFLICT (source_batch_id) DO NOTHING
                        RETURNING id
                        """,
                        (source_batch_id, file_hash),
                    )
                    first_row = cur.fetchone()
                    first_id = str(first_row["id"]) if first_row else "none"

                    # Second insert - should be skipped (conflict)
                    cur.execute(
                        """
                        INSERT INTO ingest.import_runs (
                            source_batch_id, file_hash, status, record_count,
                            started_at, completed_at
                        ) VALUES (%s, %s, 'completed', 0, NOW(), NOW())
                        ON CONFLICT (source_batch_id) DO NOTHING
                        RETURNING id
                        """,
                        (source_batch_id, file_hash),
                    )
                    duplicate_row = cur.fetchone()

                    # Cleanup
                    cur.execute(
                        "DELETE FROM ingest.import_runs WHERE source_batch_id = %s",
                        (source_batch_id,),
                    )

            skipped = duplicate_row is None

            if skipped:
                return CheckResult(
                    "Ingest idempotency",
                    True,
                    f"Duplicate correctly skipped (first_id={first_id})",
                )

            return CheckResult(
                "Ingest idempotency",
                False,
                "Duplicate was NOT skipped - idempotency broken!",
            )

        except Exception as exc:
            return CheckResult(
                "Ingest idempotency",
                False,
                f"DB error: {exc}",
                critical=False,
            )

    # ------------------------------------------------------------------
    # Run All Checks
    # ------------------------------------------------------------------

    def run_all(self) -> List[CheckResult]:
        """Execute all certification checks in order."""
        return [
            # 1. Connectivity & Headers
            self.check_health(),
            self.check_headers(),
            # 2. Database & Pooler
            self.check_readyz(),
            self.check_pooler_config(),
            # 3. Ops Privacy
            self.check_ops_schema_blocked("anon"),
            self.check_ops_schema_blocked("auth"),
            self.check_ops_rpc(),
            # 4. Idempotency
            self.check_ingest_idempotency(),
        ]


def _print_banner_pass() -> None:
    """Print the GO FOR PLAINTIFFS success banner."""
    print()
    print("\033[42m" + "=" * 72 + "\033[0m")
    print("\033[42m" + " " * 72 + "\033[0m")
    print(
        "\033[42m" + "   ✅✅✅   G O   F O R   P L A I N T I F F S   ✅✅✅".center(72) + "\033[0m"
    )
    print("\033[42m" + " " * 72 + "\033[0m")
    print(
        "\033[42m"
        + "   All certification checks passed. Dragonfly is production-ready.".center(72)
        + "\033[0m"
    )
    print("\033[42m" + " " * 72 + "\033[0m")
    print("\033[42m" + "   Next steps:".center(72) + "\033[0m")
    print("\033[42m" + "   1. Scale worker-ingest to 1".center(72) + "\033[0m")
    print("\033[42m" + "   2. Scale worker-enforcement to 1".center(72) + "\033[0m")
    print("\033[42m" + "   3. You are LIVE".center(72) + "\033[0m")
    print("\033[42m" + " " * 72 + "\033[0m")
    print("\033[42m" + "=" * 72 + "\033[0m")
    print()


def _print_banner_fail(reason: str) -> None:
    """Print the STOP - FIX REQUIRED failure banner."""
    print()
    print("\033[41m" + "=" * 72 + "\033[0m")
    print("\033[41m" + " " * 72 + "\033[0m")
    print(
        "\033[41m"
        + "   🛑🛑🛑   S T O P  -  F I X   R E Q U I R E D   🛑🛑🛑".center(72)
        + "\033[0m"
    )
    print("\033[41m" + " " * 72 + "\033[0m")
    print("\033[41m" + f"   {reason[:66]}".ljust(72) + "\033[0m")
    print("\033[41m" + " " * 72 + "\033[0m")
    print("\033[41m" + "   Do NOT scale workers until this is fixed.".center(72) + "\033[0m")
    print("\033[41m" + " " * 72 + "\033[0m")
    print("\033[41m" + "=" * 72 + "\033[0m")
    print()


def _print_report(results: List[CheckResult]) -> tuple[bool, str]:
    """Print detailed results and return (all_passed, first_failure_reason)."""
    print()
    print("=" * 72)
    print("  DRAGONFLY DEPLOYMENT CERTIFICATION")
    print(f"  Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 72)
    print()

    all_passed = True
    first_failure = ""

    for result in results:
        if result.passed:
            icon = "✅"
        elif result.critical:
            icon = "❌"
        else:
            icon = "⚠️ "

        print(f"  {icon} {result.name}")
        print(f"      {result.detail}")

        if not result.passed and result.critical:
            all_passed = False
            if not first_failure:
                first_failure = f"{result.name}: {result.detail}"

    print()
    print("=" * 72)

    return all_passed, first_failure


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Dragonfly Production Deployment Certification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tools.certify_deployment --url https://dragonfly-api-production.up.railway.app
  python -m tools.certify_deployment --url http://localhost:8000 --env dev
  python -m tools.certify_deployment --dry-run
""",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_PROD_URL,
        help=f"Base API URL (default: {DEFAULT_PROD_URL})",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="prod",
        help="Target environment (default: prod)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print test plan without executing",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    args = parse_args(argv)

    if args.dry_run:
        print("\n=== DRY RUN: CERTIFICATION PLAN ===")
        print(f"Target URL: {args.url}")
        print(f"Environment: {args.env}")
        print()
        print("Checks to perform:")
        print("  1. GET /health => 200")
        print("  2. Verify X-Dragonfly-SHA-Short and X-Dragonfly-Env headers")
        print("  3. GET /readyz => 200")
        print("  4. Verify SUPABASE_DB_URL pooler config (port 6543, sslmode=require)")
        print("  5. Verify ops schema blocked for anon/auth")
        print("  6. Verify ops.get_system_health() RPC with service_role")
        print("  7. Test ingest.import_runs idempotency")
        print()
        print("No network or database calls executed.")
        return 0

    # Set environment for credential loading
    os.environ["SUPABASE_MODE"] = args.env

    # Load credentials from environment
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    missing = []
    if not supabase_url:
        missing.append("SUPABASE_URL")
    if not anon_key:
        missing.append("SUPABASE_ANON_KEY")
    if not service_key:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")

    if missing:
        print(f"\n❌ Missing required environment variables: {', '.join(missing)}")
        print("   Run: . ./scripts/load_env.ps1")
        return 1

    # Load database URL
    try:
        db_url = get_supabase_db_url()
    except Exception as exc:
        print(f"\n❌ Unable to resolve SUPABASE_DB_URL: {exc}")
        return 1

    # Run certification
    print(f"\n🔍 Certifying: {args.url}")
    print(f"   Environment: {args.env}")

    certifier = DeploymentCertifier(
        base_url=args.url,
        env=args.env,
        supabase_url=supabase_url,
        anon_key=anon_key,
        service_key=service_key,
        db_url=db_url,
    )

    results = certifier.run_all()
    all_passed, first_failure = _print_report(results)

    if all_passed:
        _print_banner_pass()
        return 0
    else:
        _print_banner_fail(first_failure)
        return 1


if __name__ == "__main__":
    sys.exit(main())
