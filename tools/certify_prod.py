#!/usr/bin/env python3
"""
Dragonfly production certification harness.

REQUIRED CHECKS (Fail-Fast):
=============================
1. /health 200      - Process is alive
2. /readyz 200      - Database is connected
3. ops.get_system_health() 200 - RPC functions work

If ANY of these fail, certification fails immediately.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import List

import httpx

# Ensure project root modules resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use Single DSN Contract
from src.dsn_compat import get_database_url

TIMEOUT = httpx.Timeout(10.0)
OPS_SCHEMA = "ops"
OPS_TABLE = "import_runs"
REQUIRED_HEADERS = ("X-Dragonfly-SHA-Short", "X-Dragonfly-Env")
BLOCKED_STATUSES = {401, 403, 404}

# Critical checks that MUST pass (fail-fast)
CRITICAL_CHECKS = {"/health (liveness)", "/readyz (readiness)", "ops.get_system_health"}


@dataclass
class CheckResult:
    """Represents the outcome of a certification check."""

    name: str
    passed: bool
    detail: str


class ProdCertifier:
    """Runs deterministic certification checks."""

    def __init__(
        self,
        base_url: str,
        env: str,
        supabase_url: str,
        anon_key: str,
        service_key: str,
        db_url: str,
        base_path: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.base_path = base_path.rstrip("/") if base_path else ""
        self.env = env.lower()
        self.supabase_url = supabase_url.rstrip("/")
        self.anon_key = anon_key
        self.service_key = service_key
        self.db_url = db_url

    # ------------------------------------------------------------------
    # HTTP Helpers
    # ------------------------------------------------------------------

    def _api_get(self, path: str) -> httpx.Response:
        """GET request to API, respecting base_path if configured."""
        full_path = f"{self.base_path}{path}" if self.base_path else path
        url = f"{self.base_url}{full_path}"
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            return client.get(url)

    def _api_get_raw(self, path: str) -> httpx.Response:
        """GET request to API at exact path (ignores base_path)."""
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
    # Railway Domain Contract: Service Identity Verification
    # ------------------------------------------------------------------

    def check_service_identity(self) -> CheckResult:
        """
        STEP 0: Verify domain is attached to dragonfly-api (not Railway fallback).

        This is the FIRST check in certification. It catches:
        1. Railway edge fallback (X-Railway-Fallback: true)
        2. "Application not found" JSON responses
        3. Wrong service (service_name != "dragonfly-api")
        4. Standard HTTP errors (404, 502, 503)

        Returns:
            CheckResult with pass/fail and detailed remediation if failed.
        """
        try:
            resp = self._api_get_raw("/")
            status = resp.status_code

            # Check for Railway fallback header FIRST
            if resp.headers.get("X-Railway-Fallback", "").lower() == "true":
                return CheckResult(
                    "Service identity",
                    False,
                    "RAILWAY FALLBACK: Domain not attached to service",
                )

            # Handle HTTP errors
            if status == 404:
                return CheckResult(
                    "Service identity",
                    False,
                    "404 Not Found - domain may not be attached",
                )
            if status == 502:
                return CheckResult(
                    "Service identity",
                    False,
                    "502 Bad Gateway - application crashed or not started",
                )
            if status == 503:
                return CheckResult(
                    "Service identity",
                    False,
                    "503 Service Unavailable - application not ready",
                )
            if status >= 400:
                return CheckResult(
                    "Service identity",
                    False,
                    f"HTTP {status} - unexpected error",
                )

            # Parse JSON response
            try:
                data = resp.json()
            except Exception:
                return CheckResult(
                    "Service identity",
                    False,
                    "Response is not JSON - wrong service or endpoint",
                )

            # Check for Railway "Application not found" message
            message = data.get("message", "")
            if "application not found" in message.lower():
                return CheckResult(
                    "Service identity",
                    False,
                    "RAILWAY FALLBACK: 'Application not found' in response",
                )

            # Verify service_name contract
            service_name = data.get("service_name", "")
            if service_name != "dragonfly-api":
                return CheckResult(
                    "Service identity",
                    False,
                    f"Wrong service: expected 'dragonfly-api', got '{service_name}'",
                )

            # Extract identity info for logging
            env = data.get("env", "unknown")
            sha = data.get("sha_short", "unknown")
            version = data.get("version", "unknown")

            return CheckResult(
                "Service identity",
                True,
                f"dragonfly-api v{version} (sha={sha}, env={env})",
            )

        except httpx.ConnectError as exc:
            return CheckResult(
                "Service identity",
                False,
                f"Connection failed - check domain/port: {exc}",
            )
        except httpx.TimeoutException:
            return CheckResult(
                "Service identity",
                False,
                "Request timed out - app may be hung or unreachable",
            )
        except Exception as exc:
            return CheckResult(
                "Service identity",
                False,
                f"Request failed: {exc}",
            )

    def _print_railway_remediation(self) -> None:
        """Print Railway-specific remediation for domain issues."""
        print("\n" + "=" * 72)
        print("  ❌ RAILWAY DOMAIN NOT ATTACHED TO SERVICE")
        print("=" * 72)
        print()
        print("  The domain is resolving to Railway's edge, but NOT to dragonfly-api.")
        print()
        print("  TO FIX:")
        print("  1. Open Railway dashboard: https://railway.app/dashboard")
        print("  2. Select your project → dragonfly-api service")
        print("  3. Go to Settings → Networking → Public Networking")
        print("  4. Verify your domain is listed and attached")
        print("  5. If using custom domain, check DNS CNAME points to Railway")
        print()
        print("  QUICK CHECK:")
        print(f"    curl -I {self.base_url}/ | grep X-Railway")
        print()
        print("  If you see 'X-Railway-Fallback: true', the domain is NOT attached.")
        print("=" * 72 + "\n")

    # ------------------------------------------------------------------
    # OpenAPI Autodiscovery
    # ------------------------------------------------------------------

    def check_openapi_routes(self) -> CheckResult:
        """
        Fetch /openapi.json and verify /health and /readyz are present.

        If endpoints are missing from root but exist under /api, emit
        CRITICAL remediation guidance.
        """
        try:
            resp = self._api_get_raw("/openapi.json")
            if resp.status_code != 200:
                return CheckResult(
                    "OpenAPI autodiscovery",
                    False,
                    f"/openapi.json returned {resp.status_code} (expected 200)",
                )

            openapi_spec = resp.json()
            paths = openapi_spec.get("paths", {})

            # Check for /health and /readyz at root
            has_health = "/health" in paths
            has_readyz = "/readyz" in paths

            # Check if they exist under /api instead (misconfiguration)
            has_api_health = "/api/health" in paths
            has_api_readyz = "/api/readyz" in paths

            if has_health and has_readyz:
                return CheckResult(
                    "OpenAPI autodiscovery",
                    True,
                    "/health and /readyz present in OpenAPI spec",
                )

            # Build remediation message
            issues = []
            if not has_health:
                if has_api_health:
                    issues.append("/health missing at root (found at /api/health)")
                else:
                    issues.append("/health missing")
            if not has_readyz:
                if has_api_readyz:
                    issues.append("/readyz missing at root (found at /api/readyz)")
                else:
                    issues.append("/readyz missing")

            detail = "; ".join(issues)

            # Print critical remediation if routes are under /api
            if has_api_health or has_api_readyz:
                print("\n" + "=" * 72)
                print("  ⚠️  CRITICAL: Route Mounting Misconfiguration Detected")
                print("=" * 72)
                print("  Your app has health endpoints mounted under /api instead of root.")
                print()
                print("  REMEDIATION OPTIONS:")
                print("  1. Move endpoints to root path in your FastAPI app:")
                print("     app.include_router(health_root_router, prefix='')")
                print()
                print("  2. Or configure certifier with --base-path /api:")
                print(f"     python -m tools.certify_prod --url {self.base_url} --base-path /api")
                print("=" * 72 + "\n")

            return CheckResult("OpenAPI autodiscovery", False, detail)

        except Exception as exc:
            return CheckResult(
                "OpenAPI autodiscovery",
                False,
                f"Failed to fetch/parse openapi.json: {exc}",
            )

    # ------------------------------------------------------------------
    # Certification Checks
    # ------------------------------------------------------------------

    def check_health(self) -> CheckResult:
        """Check /health liveness probe - must always return 200 if process is alive.

        This endpoint NEVER checks database connectivity. It only confirms
        the API process is running and can respond to HTTP requests.
        """
        try:
            resp = self._api_get("/health")
            if resp.status_code == 200:
                # Optionally verify version/sha/env in response
                try:
                    data = resp.json()
                    version = data.get("version", "unknown")
                    sha = data.get("sha", "unknown")
                    env = data.get("env", "unknown")
                    detail = f"200 OK (v{version}, sha={sha}, env={env})"
                except Exception:
                    detail = "200 OK"
                return CheckResult("/health (liveness)", True, detail)
            return CheckResult("/health (liveness)", False, f"Expected 200, got {resp.status_code}")
        except Exception as exc:  # pragma: no cover - network failure surfaces to operator
            return CheckResult("/health (liveness)", False, f"Request failed: {exc}")

    def check_readyz(self) -> CheckResult:
        """Check /readyz readiness probe - must return 200 only if DB is ready.

        This is the STRICT gate for production readiness. If /readyz returns 503,
        the certifier MUST fail - the API is running but cannot serve traffic.

        503 response includes metadata: next_retry_in_seconds, consecutive_failures
        """
        try:
            resp = self._api_get("/readyz")
            if resp.status_code == 200:
                return CheckResult("/readyz (readiness)", True, "200 OK - DB connected")

            # 503 = API is alive but DB not ready (degraded mode)
            if resp.status_code == 503:
                try:
                    data = resp.json()
                    reason = data.get("reason", "unknown")
                    next_retry = data.get("next_retry_in_seconds")
                    failures = data.get("consecutive_failures")
                    detail = f"503 - {reason}"
                    if next_retry is not None:
                        detail += f" (retry in {next_retry}s, {failures} failures)"
                except Exception:
                    detail = "503 Service Unavailable"
                return CheckResult("/readyz (readiness)", False, detail)

            return CheckResult(
                "/readyz (readiness)", False, f"Expected 200, got {resp.status_code}"
            )
        except Exception as exc:  # pragma: no cover
            return CheckResult("/readyz (readiness)", False, f"Request failed: {exc}")

    def check_headers(self) -> CheckResult:
        try:
            resp = self._api_get("/health")
        except Exception as exc:  # pragma: no cover
            return CheckResult("Response headers", False, f"Request failed: {exc}")

        sha = resp.headers.get("X-Dragonfly-SHA-Short", "")
        env_header = resp.headers.get("X-Dragonfly-Env", "")
        sha_ok = bool(sha) and sha.lower() != "unknown"
        env_ok = env_header.lower() == self.env

        passed = sha_ok and env_ok
        detail = f"sha={sha or 'missing'}, env={env_header or 'missing'}"
        return CheckResult("Response headers", passed, detail)

    def _ops_get(self, key: str, auth: str | None = None) -> httpx.Response:
        url = f"{self.supabase_url}/rest/v1/{OPS_TABLE}?select=id&limit=1"
        headers = self._rest_headers(key, profile=OPS_SCHEMA, auth=auth)
        with httpx.Client(timeout=TIMEOUT) as client:
            return client.get(url, headers=headers)

    def check_ops_schema_blocked(self, role: str) -> CheckResult:
        """Verify ops schema is blocked for anon/authenticated via REST API."""
        auth_header = None
        if role == "auth":
            auth_header = "Bearer fake-user-jwt"
        try:
            resp = self._ops_get(self.anon_key, auth=auth_header)
            status = resp.status_code
            is_blocked = status in BLOCKED_STATUSES or (status == 200 and resp.json() == [])
            if is_blocked:
                return CheckResult(f"ops schema blocked ({role})", True, f"status={status}")
            return CheckResult(
                f"ops schema blocked ({role})",
                False,
                f"Unexpected access (status={status})",
            )
        except Exception as exc:  # pragma: no cover
            return CheckResult(f"ops schema blocked ({role})", False, f"Request failed: {exc}")

    def check_ops_fort_knox(self) -> CheckResult:
        """
        Verify Fort Knox security invariants for ops schema at database level.

        Checks:
        1. anon has NO USAGE on ops schema
        2. authenticated has NO USAGE on ops schema
        3. service_role HAS USAGE on ops schema
        4. All SECURITY DEFINER functions have search_path set
        """
        try:
            import psycopg
            from psycopg.rows import dict_row
        except Exception as exc:  # pragma: no cover
            return CheckResult("ops fort knox", False, f"psycopg missing: {exc}")

        try:
            with psycopg.connect(self.db_url, autocommit=True) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    # Check 1-3: Schema privileges
                    cur.execute(
                        """
                        SELECT 
                            has_schema_privilege('anon', 'ops', 'USAGE') AS anon_usage,
                            has_schema_privilege('authenticated', 'ops', 'USAGE') AS auth_usage,
                            has_schema_privilege('service_role', 'ops', 'USAGE') AS service_usage
                    """
                    )
                    privs = cur.fetchone()

                    anon_blocked = not privs["anon_usage"]
                    auth_blocked = not privs["auth_usage"]
                    service_ok = privs["service_usage"]

                    if not anon_blocked:
                        return CheckResult(
                            "ops fort knox", False, "SECURITY VIOLATION: anon has ops schema access"
                        )
                    if not auth_blocked:
                        return CheckResult(
                            "ops fort knox",
                            False,
                            "SECURITY VIOLATION: authenticated has ops schema access",
                        )
                    if not service_ok:
                        return CheckResult(
                            "ops fort knox",
                            False,
                            "CONFIG ERROR: service_role lost ops schema access",
                        )

                    # Check 4: SECURITY DEFINER functions have search_path
                    cur.execute(
                        """
                        SELECT COUNT(*) AS unsafe_count
                        FROM pg_proc p
                        JOIN pg_namespace n ON n.oid = p.pronamespace
                        WHERE n.nspname = 'ops'
                          AND p.prosecdef = TRUE
                          AND (p.proconfig IS NULL OR NOT EXISTS (
                              SELECT 1 FROM unnest(p.proconfig) cfg 
                              WHERE cfg LIKE 'search_path=%%'
                          ))
                    """
                    )
                    definer_result = cur.fetchone()
                    unsafe_count = definer_result["unsafe_count"]

                    if unsafe_count > 0:
                        return CheckResult(
                            "ops fort knox",
                            False,
                            f"SECURITY WARNING: {unsafe_count} SECURITY DEFINER functions missing search_path",
                        )

                    detail = "anon=blocked, auth=blocked, service_role=ok, search_path=locked"
                    return CheckResult("ops fort knox", True, detail)

        except Exception as exc:  # pragma: no cover
            return CheckResult("ops fort knox", False, f"DB error: {exc}")

    def check_ops_rpc(self) -> CheckResult:
        url = f"{self.supabase_url}/rest/v1/rpc/get_system_health"
        headers = self._rest_headers(
            self.service_key, profile=OPS_SCHEMA, auth=f"Bearer {self.service_key}"
        )
        payload = {"p_limit": 5}
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return CheckResult("ops.get_system_health", True, "RPC succeeded")
            return CheckResult(
                "ops.get_system_health",
                False,
                f"RPC failed (status={resp.status_code})",
            )
        except Exception as exc:  # pragma: no cover
            return CheckResult("ops.get_system_health", False, f"Request failed: {exc}")

    def check_ingest_idempotency(self) -> CheckResult:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except Exception as exc:  # pragma: no cover - psycopg missing in env
            return CheckResult("ingest idempotency", False, f"psycopg missing: {exc}")

        source_batch_id = f"certify_{uuid.uuid4().hex[:12]}"
        file_hash = hashlib.sha256(source_batch_id.encode()).hexdigest()

        try:
            with psycopg.connect(self.db_url, autocommit=True) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "DELETE FROM ingest.import_runs WHERE source_batch_id = %s",
                        (source_batch_id,),
                    )
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
                    row = cur.fetchone()
                    first_id = str(row["id"]) if row else ""

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

                with conn.cursor() as cleanup:
                    cleanup.execute(
                        "DELETE FROM ingest.import_runs WHERE source_batch_id = %s",
                        (source_batch_id,),
                    )

            skipped = duplicate_row is None
            detail = f"run_id={first_id or 'existing'}, duplicate_skipped={skipped}"
            return CheckResult("ingest idempotency", skipped, detail)
        except Exception as exc:  # pragma: no cover
            return CheckResult("ingest idempotency", False, f"DB error: {exc}")

    def run(self, fail_fast: bool = True) -> List[CheckResult]:
        """
        Run all certification checks.

        Args:
            fail_fast: If True, return immediately on critical check failure.

        Returns:
            List of CheckResult objects.
        """
        results = []

        # =======================================================================
        # STEP 0: Railway Domain Contract - Service Identity Verification
        # =======================================================================
        # This MUST run before any other checks. Verifies:
        # 1. Domain is attached to dragonfly-api (not Railway fallback)
        # 2. Response contains service_name="dragonfly-api"
        # 3. No "Application not found" message
        identity_result = self.check_service_identity()
        results.append(identity_result)

        if not identity_result.passed:
            # Check if it's a Railway fallback issue
            if "RAILWAY" in identity_result.detail or "not attached" in identity_result.detail:
                self._print_railway_remediation()
            else:
                print("\n" + "=" * 72)
                print("  ❌ SERVICE IDENTITY VERIFICATION FAILED")
                print("=" * 72)
                print(f"  URL: {self.base_url}")
                print(f"  Error: {identity_result.detail}")
                print()
                print("  REMEDIATION:")
                print("  1. Verify the domain is correct (check Railway dashboard)")
                print("  2. Check if the app is deployed and running (railway logs)")
                print("  3. Confirm PORT binding: app must bind to 0.0.0.0:$PORT")
                print("  4. Run: python -m tools.diagnose_boot (inside container)")
                print("=" * 72 + "\n")
            return results  # Cannot proceed - domain is wrong

        # =======================================================================
        # CRITICAL CHECKS - must pass for deployment
        # =======================================================================
        critical_checks = [
            ("check_health", self.check_health),
            ("check_readyz", self.check_readyz),
            ("check_ops_rpc", self.check_ops_rpc),
        ]

        for name, check_fn in critical_checks:
            result = check_fn()
            results.append(result)

            if fail_fast and not result.passed:
                print(f"\n❌ FAIL-FAST: Critical check '{result.name}' failed")
                print(f"   Detail: {result.detail}")
                print("\n   REMEDIATION:")
                if "health" in result.name.lower():
                    print("   - Ensure API container is running")
                    print("   - Check Railway deployment logs")
                    print("   - Run: python -m tools.certify_prod --url <url> --base-path /api")
                elif "readyz" in result.name.lower():
                    print("   - Check DATABASE_URL is set correctly")
                    print("   - Run: python -m tools.probe_db --env prod")
                    print("   - Verify Supabase project is not paused")
                elif "ops" in result.name.lower():
                    print("   - Verify ops.get_system_health() RPC exists")
                    print("   - Check service_role key has access to ops schema")
                return results

        # OpenAPI autodiscovery - verify routes are correctly mounted
        results.append(self.check_openapi_routes())

        # Additional checks (non-critical)
        results.append(self.check_headers())
        results.append(self.check_ops_schema_blocked("anon"))
        results.append(self.check_ops_schema_blocked("auth"))
        results.append(self.check_ops_fort_knox())
        results.append(self.check_ingest_idempotency())

        return results


def _print_report(results: List[CheckResult]) -> bool:
    print("\n" + "=" * 72)
    print("  DRAGONFLY PRODUCTION CERTIFICATION")
    print("=" * 72)
    all_passed = True
    for result in results:
        icon = "✅" if result.passed else "❌"
        print(f"{icon} {result.name} :: {result.detail}")
        if not result.passed:
            all_passed = False
    print("=" * 72)
    status = "GO FOR PLAINTIFFS" if all_passed else "NOT CERTIFIED"
    print(f"  Status: {status}")
    print("=" * 72 + "\n")
    return all_passed


def _print_dry_run(url: str, env: str, base_path: str = "") -> None:
    print("\n=== DRY RUN: CERTIFICATION PLAN ===")
    print(f"Target URL: {url}")
    print(f"Environment: {env}")
    if base_path:
        print(f"Base Path: {base_path}")
    print("Tests:")
    print("  0. GET / -> Railway domain contract (service_name='dragonfly-api')")
    print("     ↳ Detects X-Railway-Fallback header and 'Application not found'")
    print("  1. GET /health -> 200 (liveness)")
    print("  2. GET /readyz -> 200 (readiness)")
    print("  3. RPC: ops.get_system_health via service_role")
    print("  4. GET /openapi.json -> verify /health and /readyz in spec")
    print("  5. Response headers: X-Dragonfly-SHA-Short + X-Dragonfly-Env")
    print("  6. Ops schema blocked for anon/auth roles (REST API)")
    print("  7. Ops Fort Knox (DB): anon/auth revoked, search_path locked")
    print("  8. Idempotency: ingest.import_runs duplicate guard")
    print("No network or database calls were executed.\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dragonfly production certification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
RAILWAY DOMAIN CONTRACT (Step 0):
  GET / must return JSON with service_name="dragonfly-api".
  If response has X-Railway-Fallback: true or "Application not found",
  the domain is NOT attached to the service. See Railway dashboard.

CRITICAL CHECKS (Fail-Fast):
  1. /health 200       - Process is alive
  2. /readyz 200       - Database is connected  
  3. ops.get_system_health() 200 - RPC functions work

OpenAPI AUTODISCOVERY:
  Fetches /openapi.json and verifies /health and /readyz are present.
  If endpoints exist under /api but not root, provides remediation.

BASE PATH:
  Use --base-path /api if your app mounts all routes under /api.
  This prefixes health check paths: /api/health, /api/readyz.

SINGLE DSN CONTRACT:
  Uses DATABASE_URL (canonical) or SUPABASE_DB_URL (deprecated).
""",
    )
    parser.add_argument("--url", required=True, help="Base API URL (e.g., https://api.example.com)")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="prod",
        help="Target environment (default: prod)",
    )
    parser.add_argument(
        "--base-path",
        default="",
        dest="base_path",
        help="Prefix for health endpoints (e.g., /api). Default: empty (root)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log intended checks without touching the deployment",
    )
    parser.add_argument(
        "--no-fail-fast",
        action="store_true",
        dest="no_fail_fast",
        help="Run all checks even if critical ones fail",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.dry_run:
        _print_dry_run(args.url, args.env, args.base_path)
        return 0

    os.environ["SUPABASE_MODE"] = args.env

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    missing = [
        name
        for name, value in (
            ("SUPABASE_URL", supabase_url),
            ("SUPABASE_ANON_KEY", anon_key),
            ("SUPABASE_SERVICE_ROLE_KEY", service_key),
        )
        if not value
    ]
    if missing:
        print(f"❌ Missing required environment variables: {', '.join(missing)}")
        return 1

    try:
        # Use Single DSN Contract
        db_url = get_database_url(require=True, check_env=args.env)
    except Exception as exc:  # pragma: no cover - surfaced to operator
        print(f"❌ Unable to resolve DATABASE_URL: {exc}")
        return 1

    certifier = ProdCertifier(
        base_url=args.url,
        env=args.env,
        supabase_url=supabase_url,
        anon_key=anon_key,
        service_key=service_key,
        db_url=db_url,
        base_path=args.base_path,
    )

    base_path_info = f" (base_path={args.base_path})" if args.base_path else ""
    print(
        f"\nCertifying {args.url} ({args.env}){base_path_info} @ {datetime.utcnow().isoformat()}Z\n"
    )

    # Run certification with fail-fast (unless --no-fail-fast)
    fail_fast = not args.no_fail_fast
    results = certifier.run(fail_fast=fail_fast)
    passed = _print_report(results)
    return 0 if passed else 1


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    sys.exit(main())
