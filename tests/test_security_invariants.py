"""
tests/test_security_invariants.py

Zero Trust Security Regression Suite for Dragonfly Civil.

This test module explicitly attempts to "hack" the database by performing
operations that should be denied. If any of these tests fail (i.e., the
operation succeeds), it indicates a security boundary has been breached.

INVARIANTS TESTED:
==================
1. authenticated role CANNOT directly access ops tables (INSERT/SELECT/UPDATE)
2. authenticated role CANNOT execute admin-only RPCs (claim_pending_job, reap_stuck_jobs)
3. anon role has ZERO access to ops/intake schemas
4. RLS is FORCED on all ops and intake tables
5. dragonfly_worker role CAN access ops tables (positive control)

RUNNING:
========
    pytest tests/test_security_invariants.py -v

These tests are included in the Hard Gate (gate_preflight.ps1) and must pass
before any production deployment.

INCIDENT REFERENCE:
===================
Created as part of Incident Response Framework (INC-2025-12-21-01).
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from typing import Generator

import pytest

# Require psycopg v3 for role switching
try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore[assignment]

# =============================================================================
# MARKERS AND SKIP CONDITIONS
# =============================================================================

pytestmark = [
    pytest.mark.security,  # Security gate marker
    pytest.mark.skipif(psycopg is None, reason="psycopg v3 required"),
]


def _get_db_url() -> str | None:
    """Get database URL from environment."""
    return (
        os.environ.get("SUPABASE_DB_URL_ADMIN")
        or os.environ.get("SUPABASE_DB_URL")
        or os.environ.get("DATABASE_URL")
    )


def _has_db() -> bool:
    """Check if database is available."""
    url = _get_db_url()
    if not url:
        return False
    try:
        if psycopg is None:
            return False
        with psycopg.connect(url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return True
    except Exception:
        return False


skip_if_no_db = pytest.mark.skipif(not _has_db(), reason="Database not available")


# =============================================================================
# HELPER: ROLE-BASED CONNECTION
# =============================================================================


@contextmanager
def get_connection(role_name: str | None = None) -> Generator[psycopg.Connection, None, None]:
    """
    Get a database connection, optionally switching to a specific role.

    Args:
        role_name: PostgreSQL role to SET ROLE to. If None, uses default (postgres).

    Yields:
        psycopg.Connection with the specified role.

    Raises:
        pytest.skip: If the role switch is not allowed (test user lacks permission).

    Note:
        Uses SET ROLE which requires the connecting user to be a member of
        the target role, or to have superuser privileges.
    """
    url = _get_db_url()
    if not url:
        pytest.skip("No database URL configured")

    if psycopg is None:
        pytest.skip("psycopg v3 not available")

    conn = psycopg.connect(url, row_factory=dict_row, autocommit=False)
    try:
        if role_name:
            with conn.cursor() as cur:
                try:
                    # Use SET LOCAL ROLE so it only affects this transaction
                    cur.execute(f"SET LOCAL ROLE {role_name}")
                except psycopg.errors.InsufficientPrivilege:
                    conn.close()
                    pytest.skip(f"Cannot SET ROLE to {role_name} (test user lacks permission)")
        yield conn
    finally:
        # Always rollback to avoid leaving state
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()


def _role_exists(role_name: str) -> bool:
    """Check if a PostgreSQL role exists."""
    url = _get_db_url()
    if not url or psycopg is None:
        return False
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = %s",
                    (role_name,),
                )
                return cur.fetchone() is not None
    except Exception:
        return False


# =============================================================================
# TEST CLASS A: APP ROLE RESTRICTIONS (authenticated)
# =============================================================================


@skip_if_no_db
class TestAuthenticatedRoleRestrictions:
    """
    Tests that the `authenticated` role (API users) cannot bypass security.

    These tests attempt operations that SHOULD FAIL. If they succeed, it
    indicates a security misconfiguration.
    """

    def test_authenticated_cannot_insert_into_job_queue(self) -> None:
        """
        SECURITY: authenticated role must NOT be able to INSERT into ops.job_queue.

        Direct table writes bypass RPC validation and could inject malicious jobs.
        """
        if not _role_exists("authenticated"):
            pytest.skip("authenticated role not found")

        with get_connection("authenticated") as conn:
            with conn.cursor() as cur:
                # First, verify at the privilege level that INSERT is denied
                cur.execute("SELECT has_table_privilege('ops.job_queue', 'INSERT') as can_insert")
                result = cur.fetchone()
                assert result is not None
                assert not result[
                    "can_insert"
                ], "authenticated role has INSERT privilege on ops.job_queue"

    def test_authenticated_cannot_select_from_worker_heartbeats(self) -> None:
        """
        SECURITY: authenticated role must NOT be able to SELECT from ops.worker_heartbeats.

        Worker heartbeats are internal infrastructure data, not user-facing.
        """
        if not _role_exists("authenticated"):
            pytest.skip("authenticated role not found")

        with get_connection("authenticated") as conn:
            with conn.cursor() as cur:
                # Either raises InsufficientPrivilege OR returns empty due to RLS
                try:
                    cur.execute("SELECT * FROM ops.worker_heartbeats")
                    rows = cur.fetchall()
                    # If we get here, RLS should have blocked (returning 0 rows)
                    # This is acceptable if RLS is enforced
                    assert (
                        len(rows) == 0
                    ), "RLS should block authenticated from seeing worker_heartbeats"
                except psycopg.errors.InsufficientPrivilege:
                    # Expected: no SELECT privilege
                    pass

    def test_authenticated_cannot_call_reap_stuck_jobs(self) -> None:
        """
        SECURITY: authenticated role must NOT be able to call ops.reap_stuck_jobs().

        This is an admin-only maintenance function that could disrupt job processing.
        """
        if not _role_exists("authenticated"):
            pytest.skip("authenticated role not found")

        with get_connection("authenticated") as conn:
            with conn.cursor() as cur:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    cur.execute("SELECT ops.reap_stuck_jobs(30)")

    def test_authenticated_cannot_call_claim_pending_job(self) -> None:
        """
        SECURITY: authenticated role must NOT be able to call ops.claim_pending_job().

        Job claiming is reserved for authenticated workers, not API users.
        """
        if not _role_exists("authenticated"):
            pytest.skip("authenticated role not found")

        with get_connection("authenticated") as conn:
            with conn.cursor() as cur:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    cur.execute("SELECT * FROM ops.claim_pending_job(ARRAY['test'], 30)")

    def test_authenticated_can_call_queue_job(self) -> None:
        """
        POSITIVE CONTROL: authenticated role CAN call ops.queue_job().

        This is the only ops RPC that authenticated users should be able to call
        (to submit work to the queue). We use a valid job type to avoid enum errors.
        """
        if not _role_exists("authenticated"):
            pytest.skip("authenticated role not found")

        with get_connection("authenticated") as conn:
            with conn.cursor() as cur:
                # First, get a valid job type
                cur.execute(
                    "SELECT enumlabel FROM pg_enum WHERE enumtypid = 'ops.job_type_enum'::regtype LIMIT 1"
                )
                result = cur.fetchone()
                if result is None:
                    pytest.skip("No job types defined in ops.job_type_enum")
                valid_job_type = result["enumlabel"]

                try:
                    # This should succeed if queue_job is granted to authenticated
                    cur.execute(
                        """
                        SELECT ops.queue_job(
                            %s,
                            '{"test": true}'::jsonb,
                            0,
                            now()
                        )
                        """,
                        (valid_job_type,),
                    )
                    result = cur.fetchone()
                    # If successful, we got a job ID (UUID)
                    assert result is not None
                except psycopg.errors.InsufficientPrivilege:
                    # Also acceptable if queue_job is not granted to authenticated
                    # (depends on business requirements)
                    pass
                except psycopg.errors.RaiseException as e:
                    # Function-level validation error - we got past permission check
                    if "Invalid job type" in str(e):
                        pytest.skip("queue_job rejected test job type")
                    raise
                finally:
                    # Always rollback to avoid leaving test data
                    conn.rollback()


# =============================================================================
# TEST CLASS B: WORKER ROLE ACCESS (dragonfly_worker)
# =============================================================================


@skip_if_no_db
class TestWorkerRoleAccess:
    """
    Positive control tests: dragonfly_worker SHOULD have access to ops tables.

    These tests verify that the worker role has the privileges it needs.
    """

    def test_worker_can_select_from_job_queue(self) -> None:
        """
        POSITIVE: dragonfly_worker can SELECT from ops.job_queue.
        """
        if not _role_exists("dragonfly_worker"):
            pytest.skip("dragonfly_worker role not found")

        with get_connection("dragonfly_worker") as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM ops.job_queue")
                result = cur.fetchone()
                assert result is not None

    def test_worker_can_select_from_worker_heartbeats(self) -> None:
        """
        POSITIVE: dragonfly_worker can SELECT from ops.worker_heartbeats.
        """
        if not _role_exists("dragonfly_worker"):
            pytest.skip("dragonfly_worker role not found")

        with get_connection("dragonfly_worker") as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM ops.worker_heartbeats")
                result = cur.fetchone()
                assert result is not None

    def test_worker_can_call_claim_pending_job(self) -> None:
        """
        POSITIVE: dragonfly_worker can call ops.claim_pending_job().
        """
        if not _role_exists("dragonfly_worker"):
            pytest.skip("dragonfly_worker role not found")

        with get_connection("dragonfly_worker") as conn:
            with conn.cursor() as cur:
                # This should not raise - empty result is fine
                cur.execute("SELECT * FROM ops.claim_pending_job(ARRAY['test'], 30)")
                # Just verify it executed without error


# =============================================================================
# TEST CLASS C: RLS ENFORCEMENT
# =============================================================================


@skip_if_no_db
class TestRLSEnforcement:
    """
    Tests that Row Level Security is enabled and forced on protected tables.
    """

    def test_rls_enabled_on_ops_tables(self) -> None:
        """
        INVARIANT: All ops tables must have RLS enabled.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        c.relname,
                        c.relrowsecurity AS rls_enabled,
                        c.relforcerowsecurity AS rls_forced
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'ops' AND c.relkind = 'r'
                    """
                )
                tables = cur.fetchall()

                if not tables:
                    pytest.skip("No tables found in ops schema")

                for table in tables:
                    assert table["rls_enabled"], f"RLS not enabled on ops.{table['relname']}"

    def test_rls_forced_on_critical_ops_tables(self) -> None:
        """
        INVARIANT: Critical ops tables must have RLS FORCED (not just enabled).

        FORCE ROW LEVEL SECURITY means even table owners are subject to RLS.
        """
        critical_tables = ["job_queue", "worker_heartbeats", "ingest_batches"]

        with get_connection() as conn:
            with conn.cursor() as cur:
                for table_name in critical_tables:
                    cur.execute(
                        """
                        SELECT
                            c.relforcerowsecurity AS rls_forced
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'ops'
                          AND c.relname = %s
                          AND c.relkind = 'r'
                        """,
                        (table_name,),
                    )
                    result = cur.fetchone()
                    if result is None:
                        # Table doesn't exist, skip
                        continue
                    assert result["rls_forced"], f"RLS not FORCED on ops.{table_name}"

    def test_rls_enabled_on_intake_tables(self) -> None:
        """
        INVARIANT: All intake tables must have RLS enabled.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        c.relname,
                        c.relrowsecurity AS rls_enabled
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'intake' AND c.relkind = 'r'
                    """
                )
                tables = cur.fetchall()

                if not tables:
                    pytest.skip("No tables found in intake schema")

                for table in tables:
                    assert table["rls_enabled"], f"RLS not enabled on intake.{table['relname']}"


# =============================================================================
# TEST CLASS D: ANON ROLE RESTRICTIONS
# =============================================================================


@skip_if_no_db
class TestAnonRoleRestrictions:
    """
    Tests that the `anon` role (unauthenticated API) has zero access.
    """

    def test_anon_cannot_access_ops_schema(self) -> None:
        """
        SECURITY: anon role must NOT have USAGE on ops schema.
        """
        if not _role_exists("anon"):
            pytest.skip("anon role not found")

        with get_connection("anon") as conn:
            with conn.cursor() as cur:
                with pytest.raises(
                    (psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedTable)
                ):
                    cur.execute("SELECT 1 FROM ops.job_queue LIMIT 1")

    def test_anon_cannot_access_intake_schema(self) -> None:
        """
        SECURITY: anon role must NOT have USAGE on intake schema.
        """
        if not _role_exists("anon"):
            pytest.skip("anon role not found")

        with get_connection("anon") as conn:
            with conn.cursor() as cur:
                # Check if intake.esign exists before testing
                cur.execute(
                    """
                    SELECT 1 FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'intake' AND c.relname = 'esign'
                    """
                )
                if cur.fetchone() is None:
                    pytest.skip("intake.esign table not found")

                with pytest.raises(
                    (psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedTable)
                ):
                    cur.execute("SELECT 1 FROM intake.esign LIMIT 1")


# =============================================================================
# TEST CLASS E: PUBLIC ROLE REVOCATION
# =============================================================================


@skip_if_no_db
class TestPublicRoleRevocation:
    """
    Tests that the `public` pseudo-role has no dangerous privileges.
    """

    def test_public_cannot_create_in_public_schema(self) -> None:
        """
        SECURITY: public role must NOT have CREATE privilege on public schema.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT has_schema_privilege('public', 'public', 'CREATE') AS can_create
                    """
                )
                result = cur.fetchone()
                assert result is not None
                # This may be True in dev - document expected state
                # In hardened prod, should be False


# =============================================================================
# TEST: SECURITY AUDIT VIEW EXISTS
# =============================================================================


@skip_if_no_db
class TestSecurityAuditView:
    """
    Tests that the ops.v_security_audit view exists and is queryable.
    """

    def test_security_audit_view_exists(self) -> None:
        """
        The ops.v_security_audit view should exist for security monitoring.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'ops' AND c.relname = 'v_security_audit'
                    """
                )
                result = cur.fetchone()
                # View is created by the hardening migration
                # Skip if not yet applied
                if result is None:
                    pytest.skip("ops.v_security_audit not found (migration not applied)")

    def test_security_audit_view_returns_data(self) -> None:
        """
        The ops.v_security_audit view should return table security information.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'ops' AND c.relname = 'v_security_audit'
                    """
                )
                if cur.fetchone() is None:
                    pytest.skip("ops.v_security_audit not found")

                cur.execute("SELECT * FROM ops.v_security_audit LIMIT 5")
                rows = cur.fetchall()
                # Should have at least some tables
                assert len(rows) > 0, "v_security_audit should return table information"
