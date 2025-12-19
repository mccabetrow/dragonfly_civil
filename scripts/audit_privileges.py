#!/usr/bin/env python3
"""
Dragonfly Engine - Privilege Audit Script

Verifies that the dragonfly_app role has proper least-privilege security:
- SELECT on tables works
- RPC calls work
- DELETE/DROP/CREATE are denied

Usage:
    python scripts/audit_privileges.py

Environment:
    SUPABASE_DB_URL: Database connection string (should use dragonfly_app role)

Exit Codes:
    0: All security checks passed
    1: One or more security checks failed
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Callable

import psycopg
from psycopg import OperationalError

# Add project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.supabase_client import get_supabase_db_url


@dataclass
class AuditResult:
    """Result of a single audit check."""

    name: str
    passed: bool
    expected_pass: bool
    message: str

    @property
    def is_secure(self) -> bool:
        """True if the result matches security expectations."""
        return self.passed == self.expected_pass


class PrivilegeAuditor:
    """
    Audits database privileges for security compliance.

    Verifies that the connected role (dragonfly_app) has:
    - SELECT access on tables (for reads)
    - EXECUTE access on RPCs (for controlled writes)
    - NO DELETE/DROP/CREATE access (for security)
    """

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.results: list[AuditResult] = []

    def _run_check(
        self,
        name: str,
        sql: str,
        expected_pass: bool,
        error_class: type | tuple[type, ...] = Exception,
    ) -> AuditResult:
        """
        Run a single audit check.

        Args:
            name: Human-readable check name
            sql: SQL to execute
            expected_pass: True if we expect the SQL to succeed
            error_class: Exception type(s) that indicate permission denied
        """
        try:
            with psycopg.connect(self.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    # Fetch if there's a result
                    try:
                        cur.fetchall()
                    except Exception:
                        pass
                conn.rollback()  # Don't actually commit anything

            result = AuditResult(
                name=name,
                passed=True,
                expected_pass=expected_pass,
                message="Query executed successfully",
            )

        except psycopg.errors.InsufficientPrivilege as e:
            result = AuditResult(
                name=name,
                passed=False,
                expected_pass=expected_pass,
                message=f"Permission denied: {e}",
            )

        except psycopg.errors.UndefinedTable as e:
            result = AuditResult(
                name=name,
                passed=False,
                expected_pass=expected_pass,
                message=f"Table does not exist: {e}",
            )

        except Exception as e:
            # Check if error message indicates permission denied
            err_msg = str(e).lower()
            if "permission denied" in err_msg or "must be owner" in err_msg:
                result = AuditResult(
                    name=name,
                    passed=False,
                    expected_pass=expected_pass,
                    message=f"Permission denied: {e}",
                )
            else:
                result = AuditResult(
                    name=name,
                    passed=False,
                    expected_pass=expected_pass,
                    message=f"Unexpected error: {e}",
                )

        self.results.append(result)
        return result

    def audit_select_access(self) -> None:
        """Verify SELECT access on core tables."""
        self._run_check(
            name="SELECT from public.judgments",
            sql="SELECT count(*) FROM public.judgments",
            expected_pass=True,
        )

        self._run_check(
            name="SELECT from ops.job_queue",
            sql="SELECT count(*) FROM ops.job_queue",
            expected_pass=True,
        )

    def audit_rpc_access(self) -> None:
        """Verify RPC function access."""
        self._run_check(
            name="EXECUTE ops.register_heartbeat RPC",
            sql="""
                SELECT ops.register_heartbeat(
                    'audit-test-worker',
                    'audit_script',
                    'localhost',
                    'running'
                )
            """,
            expected_pass=True,
        )

        self._run_check(
            name="EXECUTE ops.log_intake_event RPC",
            sql="""
                SELECT ops.log_intake_event(
                    NULL::uuid,
                    NULL::uuid,
                    'INFO',
                    'Privilege audit test',
                    NULL::jsonb
                )
            """,
            expected_pass=True,
        )

    def audit_delete_denied(self) -> None:
        """Verify DELETE is denied on core tables."""
        self._run_check(
            name="DELETE from public.judgments (MUST FAIL)",
            sql="DELETE FROM public.judgments WHERE 1=0",
            expected_pass=False,  # We WANT this to fail
        )

        self._run_check(
            name="DELETE from ops.job_queue (MUST FAIL)",
            sql="DELETE FROM ops.job_queue WHERE 1=0",
            expected_pass=False,
        )

    def audit_drop_denied(self) -> None:
        """Verify DROP TABLE is denied."""
        self._run_check(
            name="DROP TABLE public.judgments (MUST FAIL)",
            sql="DROP TABLE public.judgments",
            expected_pass=False,
        )

    def audit_create_denied(self) -> None:
        """Verify CREATE TABLE is denied in public schema."""
        self._run_check(
            name="CREATE TABLE in public schema (MUST FAIL)",
            sql="CREATE TABLE public.hacker_table (id serial)",
            expected_pass=False,
        )

    def audit_insert_denied(self) -> None:
        """Verify raw INSERT is denied (must use RPCs)."""
        self._run_check(
            name="INSERT into public.judgments (MUST FAIL)",
            sql="""
                INSERT INTO public.judgments (case_number, plaintiff_name, defendant_name, judgment_amount)
                VALUES ('AUDIT-TEST-001', 'Test', 'Test', 100.00)
            """,
            expected_pass=False,
        )

    def audit_update_denied(self) -> None:
        """Verify raw UPDATE is denied (must use RPCs)."""
        self._run_check(
            name="UPDATE public.judgments (MUST FAIL)",
            sql="UPDATE public.judgments SET status = 'hacked' WHERE 1=0",
            expected_pass=False,
        )

    def run_all_checks(self) -> bool:
        """
        Run all privilege audit checks.

        Returns:
            True if all checks are secure, False otherwise
        """
        print("\n" + "=" * 60)
        print("DRAGONFLY PRIVILEGE AUDIT")
        print("=" * 60 + "\n")

        # Test connection first
        try:
            with psycopg.connect(self.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT current_user, current_database()")
                    user, db = cur.fetchone()
                    print(f"Connected as: {user}")
                    print(f"Database: {db}")
                    print()
        except Exception as e:
            print(f"❌ FAILED to connect: {e}")
            return False

        # Run audits
        print("Running security checks...\n")

        print("📖 READ ACCESS CHECKS:")
        self.audit_select_access()

        print("\n🔧 RPC ACCESS CHECKS:")
        self.audit_rpc_access()

        print("\n🔒 WRITE DENIAL CHECKS (should fail):")
        self.audit_insert_denied()
        self.audit_update_denied()
        self.audit_delete_denied()

        print("\n⛔ DDL DENIAL CHECKS (should fail):")
        self.audit_drop_denied()
        self.audit_create_denied()

        # Print results
        print("\n" + "=" * 60)
        print("RESULTS")
        print("=" * 60 + "\n")

        secure_count = 0
        vulnerable_count = 0

        for result in self.results:
            if result.is_secure:
                status = "✓ SECURE"
                color = "\033[92m"  # Green
                secure_count += 1
            else:
                status = "✗ VULNERABLE"
                color = "\033[91m"  # Red
                vulnerable_count += 1

            reset = "\033[0m"
            print(f"{color}{status}{reset} - {result.name}")
            if not result.is_secure:
                print(f"         → {result.message}")

        print("\n" + "-" * 60)
        print(f"SUMMARY: {secure_count} secure, {vulnerable_count} vulnerable")

        if vulnerable_count == 0:
            print("\n\033[92m✓ ALL SECURITY CHECKS PASSED\033[0m")
            print("The dragonfly_app role has proper least-privilege access.\n")
            return True
        else:
            print("\n\033[91m✗ SECURITY VULNERABILITIES DETECTED\033[0m")
            print("Review the failed checks and update grants/revokes.\n")
            return False


def main() -> int:
    """Run the privilege audit."""
    # Get DSN from environment
    dsn = get_supabase_db_url()

    if not dsn:
        print("ERROR: SUPABASE_DB_URL not set")
        print("Set the environment variable to the dragonfly_app connection string:")
        print("  export SUPABASE_DB_URL='postgresql://dragonfly_app:password@host:5432/postgres'")
        return 1

    # Check if we're connecting as dragonfly_app
    if "dragonfly_app" not in dsn:
        print("⚠️  WARNING: DSN does not appear to use dragonfly_app role")
        print("   This audit should be run with the dragonfly_app role to verify its permissions.")
        print()

    auditor = PrivilegeAuditor(dsn)
    success = auditor.run_all_checks()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
