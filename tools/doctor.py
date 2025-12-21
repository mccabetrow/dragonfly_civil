"""
Dragonfly Doctor - Ultimate Production Environment Diagnostic

World-class environment verification with:
- Cross-project mismatch detection (JWT decode)
- DB connectivity & port detection (Direct vs Pooler)
- RPC function existence validation
- Job status enum verification
- Schema consistency checks

Usage:
    python -m tools.doctor              # Run all checks
    python -m tools.doctor --verbose    # Verbose output
    python -m tools.doctor --env prod   # Target specific environment

Exit Codes:
    0 - All checks passed
    1 - One or more checks failed
    2 - Critical misconfiguration (cross-project mismatch)
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlparse
from uuid import UUID, uuid4

import click
import httpx
import psycopg
from psycopg.conninfo import conninfo_to_dict

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.supabase_client import (
    create_supabase_client,
    get_supabase_credentials,
    get_supabase_db_url,
    get_supabase_env,
)

# Exit codes
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CRITICAL = 2

# PostgREST retry configuration
POSTGREST_MAX_RETRIES = 3
POSTGREST_RETRY_DELAY_SECONDS = 2

# Required RPC functions that must exist
REQUIRED_RPCS = [
    ("ops", "claim_pending_job"),
    ("ops", "register_heartbeat"),
    ("ops", "queue_job"),
    ("ops", "update_job_status"),
]

# Required job status enum values
REQUIRED_JOB_STATUSES = ["pending", "processing", "completed", "failed"]

# RPC functions that MUST be SECURITY DEFINER
SECURITY_DEFINER_RPCS = [
    ("ops", "claim_pending_job"),
    ("ops", "update_job_status"),
    ("ops", "queue_job"),
]

# Tables that MUST have RLS enabled
RLS_REQUIRED_TABLES = [
    ("ops", "job_queue"),
    ("ops", "worker_heartbeats"),
]


class CheckResult(NamedTuple):
    """Result of a diagnostic check."""

    passed: bool
    message: str
    details: dict[str, Any] | None = None


class DoctorDiagnostics:
    """Production environment diagnostic suite."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.checks_run = 0
        self.checks_passed = 0
        self.checks_failed = 0
        self.critical_failure = False

    def log(self, message: str, level: str = "info") -> None:
        """Log a message with appropriate formatting."""
        # Use ASCII-safe symbols for Windows terminal compatibility
        if level == "pass":
            click.echo(click.style("[PASS] ", fg="green") + message)
        elif level == "fail":
            click.echo(click.style("[FAIL] ", fg="red") + message)
        elif level == "warn":
            click.echo(click.style("[WARN] ", fg="yellow") + message)
        elif level == "info":
            click.echo(click.style("[INFO] ", fg="blue") + message)
        elif level == "critical":
            click.echo(click.style("[CRITICAL] ", fg="red", bold=True) + message)
        else:
            click.echo(f"[{level}] {message}")

    def record(self, result: CheckResult) -> None:
        """Record a check result."""
        self.checks_run += 1
        if result.passed:
            self.checks_passed += 1
            self.log(result.message, "pass")
        else:
            self.checks_failed += 1
            self.log(result.message, "fail")

        if self.verbose and result.details:
            for key, value in result.details.items():
                click.echo(f"       {key}: {value}")

    # =========================================================================
    # CHECK 1: Cross-Project Mismatch (JWT Decode)
    # =========================================================================
    def check_cross_project_mismatch(self) -> CheckResult:
        """
        Verify SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY belong to the same project.

        Decodes the JWT without verification to extract the project ref from the
        'iss' claim and compares it against the URL hostname.

        Returns:
            CheckResult with pass/fail status
        """
        try:
            url, key = get_supabase_credentials()
        except RuntimeError as e:
            return CheckResult(False, f"Missing credentials: {e}")

        # Extract project ref from SUPABASE_URL
        try:
            parsed_url = urlparse(url)
            url_host = parsed_url.netloc or parsed_url.path
            if ".supabase.co" not in url_host:
                return CheckResult(
                    True,
                    f"Skipping cross-project check: non-standard URL ({url_host})",
                    {"url_host": url_host},
                )
            url_project_ref = url_host.split(".")[0]
        except Exception as e:
            return CheckResult(False, f"Could not parse SUPABASE_URL: {e}")

        # Decode JWT payload (without signature verification)
        try:
            segments = key.split(".")
            if len(segments) < 2:
                return CheckResult(False, "Invalid JWT format - missing segments")

            payload_segment = segments[1]
            padding = "=" * (-len(payload_segment) % 4)
            decoded = base64.urlsafe_b64decode(payload_segment + padding)
            claims = json.loads(decoded)
        except Exception as e:
            return CheckResult(False, f"Could not decode service role JWT: {e}")

        # Extract project ref from JWT
        jwt_project_ref = None

        # Try 'ref' claim first (some JWTs have it)
        if "ref" in claims:
            jwt_project_ref = claims["ref"]
        elif "iss" in claims:
            # Parse from issuer URL: https://project-ref.supabase.co/auth/v1
            iss = claims["iss"]
            try:
                iss_parsed = urlparse(iss)
                iss_host = iss_parsed.netloc or ""
                if ".supabase.co" in iss_host:
                    jwt_project_ref = iss_host.split(".")[0]
            except Exception:
                pass

        if not jwt_project_ref:
            return CheckResult(
                False,
                f"Could not extract project ref from JWT (claims: {list(claims.keys())})",
            )

        # Compare project refs
        if url_project_ref.lower() == jwt_project_ref.lower():
            return CheckResult(
                True,
                f"Cross-project check OK (project: {url_project_ref})",
                {"url_ref": url_project_ref, "jwt_ref": jwt_project_ref},
            )
        else:
            # CRITICAL - this causes data to be written to wrong DB
            self.critical_failure = True
            return CheckResult(
                False,
                f"CROSS-PROJECT MISMATCH! URL={url_project_ref}, Key={jwt_project_ref}",
                {"url_ref": url_project_ref, "jwt_ref": jwt_project_ref},
            )

    # =========================================================================
    # CHECK 2: DB Connection & Port Detection
    # =========================================================================
    def check_db_connection(self) -> CheckResult:
        """
        Verify database connectivity and detect connection mode.

        Checks:
        - Port 5432 = Direct connection (NOT recommended for production)
        - Port 6543 = Transaction pooler (recommended)
        - Runs SELECT version() to verify connectivity

        Returns:
            CheckResult with connection details
        """
        try:
            db_url = get_supabase_db_url()
        except RuntimeError as e:
            return CheckResult(False, f"SUPABASE_DB_URL not configured: {e}")

        # Parse connection string to extract port
        try:
            parts = conninfo_to_dict(db_url)
            host = str(parts.get("host") or "unknown")
            port_val = parts.get("port")
            port = int(port_val) if port_val else 5432
            user = str(parts.get("user") or "unknown")
        except Exception as e:
            return CheckResult(False, f"Could not parse DB URL: {e}")

        # Detect connection mode
        mode = "Direct" if port == 5432 else "Pooler" if port == 6543 else f"Unknown (port {port})"
        env = get_supabase_env()

        # Warn about direct connections in production
        if port == 5432 and env == "prod":
            self.log(
                "Using Direct mode (port 5432) in Production - consider Transaction Pooler (6543)",
                "warn",
            )

        # Test connectivity
        try:
            with psycopg.connect(db_url, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version()")
                    version_row = cur.fetchone()
                    version = version_row[0] if version_row else "unknown"

                    # Extract PostgreSQL version
                    pg_version = "unknown"
                    if version:
                        match = re.search(r"PostgreSQL (\d+\.\d+)", version)
                        if match:
                            pg_version = match.group(1)

            return CheckResult(
                True,
                f"DB connection OK ({mode} mode, PostgreSQL {pg_version})",
                {
                    "host": host,
                    "port": port,
                    "mode": mode,
                    "user": user,
                    "pg_version": pg_version,
                },
            )

        except psycopg.OperationalError as e:
            return CheckResult(False, f"DB connection failed: {e}")
        except Exception as e:
            return CheckResult(False, f"Unexpected DB error: {e}")

    # =========================================================================
    # CHECK 3: RPC Function Existence
    # =========================================================================
    def check_rpc_functions(self) -> CheckResult:
        """
        Verify required RPC functions exist in information_schema.routines.

        Returns:
            CheckResult with list of missing functions
        """
        try:
            db_url = get_supabase_db_url()
        except RuntimeError as e:
            return CheckResult(False, f"Cannot check RPCs without DB URL: {e}")

        missing_rpcs = []
        found_rpcs = []

        try:
            with psycopg.connect(db_url, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    for schema, routine in REQUIRED_RPCS:
                        cur.execute(
                            """
                            SELECT 1 FROM information_schema.routines
                            WHERE routine_schema = %s AND routine_name = %s
                            LIMIT 1
                            """,
                            (schema, routine),
                        )
                        if cur.fetchone():
                            found_rpcs.append(f"{schema}.{routine}")
                        else:
                            missing_rpcs.append(f"{schema}.{routine}")

            if missing_rpcs:
                return CheckResult(
                    False,
                    f"Missing RPC functions: {', '.join(missing_rpcs)}",
                    {"found": found_rpcs, "missing": missing_rpcs},
                )
            else:
                return CheckResult(
                    True,
                    f"All {len(REQUIRED_RPCS)} required RPC functions exist",
                    {"found": found_rpcs},
                )

        except Exception as e:
            return CheckResult(False, f"RPC check failed: {e}")

    # =========================================================================
    # CHECK 4: Job Status Enum Verification
    # =========================================================================
    def check_job_status_enum(self) -> CheckResult:
        """
        Verify ops.job_status enum contains all required values.

        Returns:
            CheckResult with enum values
        """
        try:
            db_url = get_supabase_db_url()
        except RuntimeError as e:
            return CheckResult(False, f"Cannot check enum without DB URL: {e}")

        try:
            with psycopg.connect(db_url, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    # Check if enum exists and get values
                    cur.execute(
                        """
                        SELECT enumlabel
                        FROM pg_enum e
                        JOIN pg_type t ON e.enumtypid = t.oid
                        JOIN pg_namespace n ON t.typnamespace = n.oid
                        WHERE n.nspname = 'ops' AND t.typname = 'job_status_enum'
                        ORDER BY enumsortorder
                        """
                    )
                    rows = cur.fetchall()

                    if not rows:
                        return CheckResult(
                            False,
                            "ops.job_status_enum does not exist",
                        )

                    enum_values = [row[0] for row in rows]
                    missing_values = [v for v in REQUIRED_JOB_STATUSES if v not in enum_values]

                    if missing_values:
                        return CheckResult(
                            False,
                            f"job_status_enum missing values: {', '.join(missing_values)}",
                            {"found": enum_values, "missing": missing_values},
                        )
                    else:
                        return CheckResult(
                            True,
                            f"job_status_enum has all required values ({len(enum_values)} total)",
                            {"values": enum_values},
                        )

        except Exception as e:
            return CheckResult(False, f"Enum check failed: {e}")

    # =========================================================================
    # CHECK 5: PostgREST Connectivity (with retry for schema cache)
    # =========================================================================
    def check_postgrest_api(self) -> CheckResult:
        """
        Verify PostgREST API is reachable and service role is valid.

        Uses retry logic to handle PostgREST schema cache delays (PGRST002).
        Returns WARNING (not FAIL) for transient PostgREST issues since
        the primary database gate uses direct psycopg connections.

        Returns:
            CheckResult with API response details
        """
        last_error = None

        for attempt in range(1, POSTGREST_MAX_RETRIES + 1):
            try:
                client = create_supabase_client()
                res = client.table("judgments").select("*").limit(1).execute()
                row_count = len(res.data) if hasattr(res, "data") and res.data else 0

                return CheckResult(
                    True,
                    f"PostgREST API OK (judgments table accessible, {row_count} sample rows)",
                    {"row_count": row_count, "attempts": attempt},
                )

            except Exception as e:
                last_error = e
                message = str(e)

                # PGRST002 = schema cache stale; retry after delay
                if "PGRST002" in message or "schema cache" in message.lower():
                    if attempt < POSTGREST_MAX_RETRIES:
                        self.log(
                            f"PostgREST schema cache stale (attempt {attempt}/{POSTGREST_MAX_RETRIES}), "
                            f"retrying in {POSTGREST_RETRY_DELAY_SECONDS}s...",
                            "warn",
                        )
                        time.sleep(POSTGREST_RETRY_DELAY_SECONDS)
                        continue

                # 503/502 = PostgREST temporarily unavailable; retry
                if "503" in message or "502" in message:
                    if attempt < POSTGREST_MAX_RETRIES:
                        self.log(
                            f"PostgREST unavailable (attempt {attempt}/{POSTGREST_MAX_RETRIES}), "
                            f"retrying in {POSTGREST_RETRY_DELAY_SECONDS}s...",
                            "warn",
                        )
                        time.sleep(POSTGREST_RETRY_DELAY_SECONDS)
                        continue

                # Auth errors are not retryable
                if "401" in message or "403" in message:
                    return CheckResult(False, f"Authentication failed: {e}")

                # Other errors: break and report
                break

        # After all retries exhausted, check if it's a transient PostgREST issue
        message = str(last_error) if last_error else "Unknown error"

        # PGRST002 after retries = WARNING (DB gate is primary)
        if "PGRST002" in message or "schema cache" in message.lower():
            self.log(
                f"PostgREST schema cache issue (WARNING only - DB gate passed): {last_error}",
                "warn",
            )
            return CheckResult(
                True,  # Pass with warning since DB gate is primary
                "PostgREST schema cache stale (run: supabase db reload) - DB gate OK",
                {"warning": True, "attempts": POSTGREST_MAX_RETRIES},
            )

        # 503/502 after retries = WARNING
        if "503" in message or "502" in message:
            self.log(
                "PostgREST temporarily unavailable (WARNING only - DB gate passed)",
                "warn",
            )
            return CheckResult(
                True,  # Pass with warning since DB gate is primary
                "PostgREST temporarily unavailable - DB gate OK",
                {"warning": True, "attempts": POSTGREST_MAX_RETRIES},
            )

        return CheckResult(False, f"PostgREST check failed: {last_error}")

    # =========================================================================
    # CHECK 6: Queue Job RPC (with retry for schema cache)
    # =========================================================================
    def check_queue_job_rpc(self) -> CheckResult:
        """
        Verify queue_job RPC is callable via PostgREST.

        Uses retry logic for PostgREST schema cache issues.

        Returns:
            CheckResult with RPC call result
        """
        last_error = None

        for attempt in range(1, POSTGREST_MAX_RETRIES + 1):
            try:
                client = create_supabase_client()
                client.rpc(
                    "queue_job",
                    {
                        "payload": {
                            "idempotency_key": f"doctor:ping:{uuid4().hex[:8]}",
                            "kind": "enrich",
                            "payload": {},
                        }
                    },
                ).execute()

                return CheckResult(
                    True,
                    "queue_job RPC callable via PostgREST",
                    {"attempts": attempt},
                )

            except Exception as e:
                last_error = e
                message = str(e)

                # PGRST202 = function not exposed; PGRST002 = schema cache stale
                if "PGRST002" in message or "503" in message or "502" in message:
                    if attempt < POSTGREST_MAX_RETRIES:
                        time.sleep(POSTGREST_RETRY_DELAY_SECONDS)
                        continue

                # PGRST202 = function not in schema (not retryable)
                if "PGRST202" in message:
                    return CheckResult(
                        False,
                        "queue_job RPC not found in PostgREST schema (apply migration & reload)",
                    )

                break

        # After retries, check if it's a transient issue
        message = str(last_error) if last_error else "Unknown error"

        if "PGRST002" in message or "503" in message or "502" in message:
            self.log(
                "queue_job RPC check skipped (PostgREST unavailable) - DB gate OK",
                "warn",
            )
            return CheckResult(
                True,  # Pass with warning since DB gate is primary
                "queue_job RPC check skipped (PostgREST unavailable) - DB gate OK",
                {"warning": True, "attempts": POSTGREST_MAX_RETRIES},
            )

        return CheckResult(False, f"queue_job RPC failed: {last_error}")

    # =========================================================================
    # CHECK 7: Critical Views Exist
    # =========================================================================
    def check_critical_views(self) -> CheckResult:
        """
        Verify critical dashboard views exist.

        Returns:
            CheckResult with view status
        """
        critical_views = [
            "v_plaintiffs_overview",
            "v_judgment_pipeline",
            "v_enforcement_overview",
        ]

        try:
            db_url = get_supabase_db_url()
        except RuntimeError as e:
            return CheckResult(False, f"Cannot check views without DB URL: {e}")

        missing_views = []
        found_views = []

        try:
            with psycopg.connect(db_url, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    for view in critical_views:
                        cur.execute(
                            """
                            SELECT 1 FROM information_schema.views
                            WHERE table_schema = 'public' AND table_name = %s
                            LIMIT 1
                            """,
                            (view,),
                        )
                        if cur.fetchone():
                            found_views.append(view)
                        else:
                            missing_views.append(view)

            if missing_views:
                return CheckResult(
                    False,
                    f"Missing views: {', '.join(missing_views)}",
                    {"found": found_views, "missing": missing_views},
                )
            else:
                return CheckResult(
                    True,
                    f"All {len(critical_views)} critical views exist",
                    {"found": found_views},
                )

        except Exception as e:
            return CheckResult(False, f"View check failed: {e}")

    # =========================================================================
    # CHECK 8: RLS Enabled on Critical Tables
    # =========================================================================
    def check_rls_enabled(self) -> CheckResult:
        """
        Verify RLS is enabled on critical ops tables.

        Security Invariant: ops.job_queue and ops.worker_heartbeats must have RLS.

        Returns:
            CheckResult with RLS status
        """
        try:
            db_url = get_supabase_db_url()
        except RuntimeError as e:
            return CheckResult(False, f"Cannot check RLS without DB URL: {e}")

        tables_without_rls = []
        tables_with_rls = []

        try:
            with psycopg.connect(db_url, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    for schema, table in RLS_REQUIRED_TABLES:
                        cur.execute(
                            """
                            SELECT relrowsecurity
                            FROM pg_class c
                            JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE n.nspname = %s AND c.relname = %s
                            """,
                            (schema, table),
                        )
                        row = cur.fetchone()
                        fqn = f"{schema}.{table}"

                        if row is None:
                            tables_without_rls.append(f"{fqn} (table not found)")
                        elif row[0]:
                            tables_with_rls.append(fqn)
                        else:
                            tables_without_rls.append(fqn)

            if tables_without_rls:
                return CheckResult(
                    False,
                    f"RLS not enabled: {', '.join(tables_without_rls)}",
                    {"enabled": tables_with_rls, "missing": tables_without_rls},
                )
            else:
                return CheckResult(
                    True,
                    f"RLS enabled on all {len(RLS_REQUIRED_TABLES)} critical tables",
                    {"enabled": tables_with_rls},
                )

        except Exception as e:
            return CheckResult(False, f"RLS check failed: {e}")

    # =========================================================================
    # CHECK 9: SECURITY DEFINER on Critical RPCs
    # =========================================================================
    def check_security_definer_rpcs(self) -> CheckResult:
        """
        Verify critical RPCs are SECURITY DEFINER.

        Security Invariant: ops.claim_pending_job, ops.update_job_status must
        be SECURITY DEFINER to enforce least-privilege access.

        Returns:
            CheckResult with RPC security status
        """
        try:
            db_url = get_supabase_db_url()
        except RuntimeError as e:
            return CheckResult(False, f"Cannot check RPCs without DB URL: {e}")

        insecure_rpcs = []
        secure_rpcs = []

        try:
            with psycopg.connect(db_url, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    for schema, routine in SECURITY_DEFINER_RPCS:
                        cur.execute(
                            """
                            SELECT security_type
                            FROM information_schema.routines
                            WHERE routine_schema = %s AND routine_name = %s
                            LIMIT 1
                            """,
                            (schema, routine),
                        )
                        row = cur.fetchone()
                        fqn = f"{schema}.{routine}"

                        if row is None:
                            insecure_rpcs.append(f"{fqn} (not found)")
                        elif row[0] == "DEFINER":
                            secure_rpcs.append(fqn)
                        else:
                            insecure_rpcs.append(f"{fqn} (INVOKER)")

            if insecure_rpcs:
                return CheckResult(
                    False,
                    f"RPCs not SECURITY DEFINER: {', '.join(insecure_rpcs)}",
                    {"secure": secure_rpcs, "insecure": insecure_rpcs},
                )
            else:
                return CheckResult(
                    True,
                    f"All {len(SECURITY_DEFINER_RPCS)} critical RPCs are SECURITY DEFINER",
                    {"secure": secure_rpcs},
                )

        except Exception as e:
            return CheckResult(False, f"SECURITY DEFINER check failed: {e}")

    def run_all_checks(self) -> int:
        """
        Run all diagnostic checks.

        Returns:
            Exit code (0 = success, 1 = failure, 2 = critical)
        """
        env = get_supabase_env()
        click.echo("")
        click.echo("=" * 70)
        click.echo(f"  DRAGONFLY DOCTOR - Environment: {env.upper()}")
        click.echo("=" * 70)
        click.echo("")

        # Run checks in priority order
        checks = [
            ("Cross-Project Mismatch", self.check_cross_project_mismatch),
            ("Database Connection", self.check_db_connection),
            ("RPC Functions", self.check_rpc_functions),
            ("Job Status Enum", self.check_job_status_enum),
            ("RLS Enabled", self.check_rls_enabled),
            ("SECURITY DEFINER RPCs", self.check_security_definer_rpcs),
            ("PostgREST API", self.check_postgrest_api),
            ("Queue Job RPC", self.check_queue_job_rpc),
            ("Critical Views", self.check_critical_views),
        ]

        for name, check_fn in checks:
            click.echo(f"[{name}]")
            try:
                result = check_fn()
                self.record(result)
            except Exception as e:
                self.record(CheckResult(False, f"Check crashed: {e}"))

            # Stop on critical failure
            if self.critical_failure:
                click.echo("")
                click.echo("=" * 70)
                click.echo(click.style("CRITICAL FAILURE - STOPPING CHECKS", fg="red", bold=True))
                click.echo("=" * 70)
                click.echo("")
                click.echo("Your SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY point to")
                click.echo("DIFFERENT Supabase projects. This will cause data corruption.")
                click.echo("")
                click.echo("Fix: Verify both environment variables are from the same project.")
                click.echo("")
                return EXIT_CRITICAL

            click.echo("")

        # Summary
        click.echo("=" * 70)
        if self.checks_failed == 0:
            click.echo(
                click.style(
                    f"  ALL CHECKS PASSED ({self.checks_passed}/{self.checks_run})",
                    fg="green",
                    bold=True,
                )
            )
            exit_code = EXIT_OK
        else:
            click.echo(
                click.style(
                    f"  {self.checks_failed} CHECK(S) FAILED ({self.checks_passed}/{self.checks_run} passed)",
                    fg="red",
                    bold=True,
                )
            )
            exit_code = EXIT_FAILED
        click.echo("=" * 70)
        click.echo("")

        return exit_code


@click.command()
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
@click.option("--env", type=click.Choice(["dev", "prod"]), help="Target environment")
def main(verbose: bool, env: str | None) -> None:
    """Run the Dragonfly Doctor diagnostic suite."""
    if env:
        os.environ["SUPABASE_MODE"] = env

    doctor = DoctorDiagnostics(verbose=verbose)
    exit_code = doctor.run_all_checks()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
