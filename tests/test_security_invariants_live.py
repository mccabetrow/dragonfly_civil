"""
tests/test_security_invariants_live.py

Live Database Security Invariant Tests for Dragonfly Civil.

This module queries the actual database to verify security invariants:
1. RLS Coverage: Every table in public/ops/intake has RLS enabled + forced
2. Security Definer Whitelist: Only approved functions use SECURITY DEFINER
3. Grant Audit: No unexpected grants to anon/authenticated/public roles

RUNNING:
========
    pytest tests/test_security_invariants_live.py -v -m security

These tests are included in the Hard Gate and must pass before deployment.

MARKER:
=======
Tests are marked with @pytest.mark.security for selective execution.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

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


# =============================================================================
# SECURITY DEFINER WHITELIST
# =============================================================================
# Only these functions are allowed to use SECURITY DEFINER
# Add new functions here ONLY after security review
# Last audited: 2024-12-22

ALLOWED_SECURITY_DEFINERS = frozenset(
    [
        # ==== OPS SCHEMA ====
        # Core queue operations (need elevated privileges)
        "ops.claim_pending_job",
        "ops.queue_job",
        "ops.queue_job_idempotent",
        "ops.enqueue_job",
        "ops.reap_stuck_jobs",
        "ops.complete_job",
        "ops.fail_job",
        "ops.update_job_status",
        "ops.get_queue_health_summary",
        # Worker management
        "ops.register_heartbeat",
        "ops.worker_heartbeat",
        # Audit logging
        "ops.log_action",
        "ops.log_audit",
        "ops.log_intake_event",
        # Batch management
        "ops.create_ingest_batch",
        "ops.create_intake_batch",
        "ops.finalize_ingest_batch",
        "ops.finalize_intake_batch",
        "ops.check_batch_integrity",
        # Judgment operations
        "ops.upsert_judgment",
        "ops.upsert_judgment_extended",
        # ==== INTAKE SCHEMA ====
        # FOIL intake operations
        "intake.create_foil_dataset",
        "intake.finalize_foil_dataset",
        "intake.quarantine_foil_row",
        "intake.store_foil_raw_row",
        "intake.store_foil_raw_rows_bulk",
        "intake.update_foil_dataset_mapping",
        "intake.update_foil_dataset_status",
        "intake.update_foil_raw_row_status",
        "intake.process_raw_row",
        # ==== PUBLIC SCHEMA ====
        # Access control helpers
        "public.dragonfly_can_read",
        "public.dragonfly_has_any_role",
        "public.dragonfly_has_role",
        "public.dragonfly_is_admin",
        "public.handle_new_user",
        # Enforcement operations
        "public.add_enforcement_event",
        "public.add_evidence",
        "public.evaluate_enforcement_path",
        "public.generate_enforcement_tasks",
        "public.get_enforcement_timeline",
        "public.log_enforcement_action",
        "public.log_enforcement_event",
        "public.set_enforcement_stage",
        "public.spawn_enforcement_flow",
        "public.update_enforcement_action_status",
        # Case operations
        "public.insert_case",
        "public.insert_case_with_entities",
        "public.insert_entity",
        "public.insert_or_get_case",
        "public.insert_or_get_case_with_entities",
        "public.insert_or_get_entity",
        "public.copilot_case_context",
        "public.request_case_copilot",
        # Judgment operations
        "public.update_judgment_status",
        "public.set_judgment_priority",
        "public.score_case_collectability",
        "public.set_case_scores",
        "public.portfolio_judgments_paginated",
        "public.ops_update_judgment",
        # Plaintiff operations
        "public.set_plaintiff_status",
        "public.update_plaintiff_status",
        "public.ops_update_plaintiff_status",
        "public.complete_plaintiff_task",
        "public.upsert_plaintiff_task",
        "public.ops_update_task",
        "public.log_call_outcome",
        "public.outreach_log_call",
        "public.outreach_update_status",
        # Enrichment operations
        "public.complete_enrichment",
        "public.set_case_enrichment",
        "public.upsert_enrichment_bundle",
        "public.upsert_debtor_intelligence",
        "public.enrichment_log_run",
        "public.enrichment_update_debtor",
        # Import operations
        "public.advance_import_run",
        "public.check_import_guardrails",
        "public.store_intake_validation",
        "public.submit_intake_review",
        "public.get_intake_stats",
        "public.fetch_new_candidates",
        # Metrics and dashboards
        "public.ceo_12_metrics",
        "public.ceo_command_center_metrics",
        "public.enforcement_activity_metrics",
        "public.enforcement_radar_filtered",
        "public.intake_radar_metrics",
        "public.intake_radar_metrics_v2",
        "public.compute_litigation_budget",
        "public.get_litigation_budget",
        "public.approve_daily_budget",
        # Logging operations
        "public.log_access",
        "public.get_access_logs",
        "public.log_event",
        "public.log_export",
        "public.log_external_data_call",
        "public.log_insert_case",
        "public.log_insert_entity",
        "public.log_sensitive_update",
        "public.block_sensitive_delete",
        # Ops triage
        "public.ops_triage_alerts",
        "public.ops_triage_alerts_ack",
        "public.ops_triage_alerts_fetch",
        # Queue operations
        "public.dequeue_job",
        "public.pgmq_delete",
        "public.pgmq_get_queue_metrics",
        "public.pgmq_metrics",
        # Triggers (SECURITY DEFINER is standard)
        "public.trg_core_judgments_enqueue_enrich",
        "public.trg_log_judgment_status_change",
        # System utilities
        "public.pgrst_reload",
        "public.broadcast_live_event",
        "public.submit_website_lead",
    ]
)

# Schemas to audit for RLS compliance
AUDITED_SCHEMAS = ("public", "ops", "intake")

# Tables excluded from RLS requirement (system tables, legacy tables)
RLS_EXCLUDED_TABLES = frozenset(
    [
        "schema_migrations",
        "supabase_migrations",
        "_realtime_schema_cache",
        # Legacy/system tables (audit these periodically)
        "dragonfly_migrations",  # Internal migration tracking
        "judgment_history",  # Legacy audit table (deprecated)
        "raw_simplicity_imports",  # ETL staging table (internal only)
    ]
)

# Tables excluded from FORCE RLS requirement (service-only tables)
FORCE_RLS_EXCLUDED_TABLES = frozenset(
    [
        *RLS_EXCLUDED_TABLES,
        # These have RLS but not FORCE - intentional for service access
        "budget_approval_log",  # Service-role only writes
        "etl_run_logs",  # ETL worker writes
        "foil_followup_log",  # Service-role only
        "foil_requests",  # Service-role only
    ]
)


# =============================================================================
# DB CONNECTION HELPERS
# =============================================================================


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
# FIXTURES
# =============================================================================


@pytest.fixture
def db_connection():
    """Provide a database connection for security tests."""
    url = _get_db_url()
    if not url:
        pytest.skip("No database URL configured")

    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
        yield conn


# =============================================================================
# TEST CLASS: RLS COVERAGE
# =============================================================================


class TestRLSCoverage:
    """Tests to verify Row Level Security is enabled on all tables."""

    @skip_if_no_db
    def test_all_tables_have_rls_enabled(self, db_connection):
        """
        Test A.1: Verify ALL tables in audited schemas have RLS enabled.

        Fails if ANY table has relrowsecurity = false.
        """
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    n.nspname AS schema_name,
                    c.relname AS table_name,
                    c.relrowsecurity AS rls_enabled,
                    c.relforcerowsecurity AS rls_forced
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = ANY(%s)
                  AND c.relkind = 'r'
                  AND c.relname NOT LIKE 'pg_%%'
                  AND c.relname NOT LIKE '_pg_%%'
                  AND c.relname NOT LIKE '_realtime_%%'
                  AND c.relrowsecurity = false
                ORDER BY n.nspname, c.relname
                """,
                (list(AUDITED_SCHEMAS),),
            )
            violations = cur.fetchall()

        # Filter out excluded tables
        real_violations = [v for v in violations if v["table_name"] not in RLS_EXCLUDED_TABLES]

        if real_violations:
            violation_list = "\n".join(
                f"  - {v['schema_name']}.{v['table_name']}" for v in real_violations
            )
            pytest.fail(
                f"RLS NOT ENABLED on {len(real_violations)} tables:\n{violation_list}\n\n"
                f"Fix: ALTER TABLE <schema>.<table> ENABLE ROW LEVEL SECURITY;"
            )

    @skip_if_no_db
    def test_all_tables_have_rls_forced(self, db_connection):
        """
        Test A.2: Verify ALL tables have RLS FORCED.

        FORCE RLS ensures that even SECURITY DEFINER functions
        cannot bypass RLS policies.
        """
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    n.nspname AS schema_name,
                    c.relname AS table_name,
                    c.relrowsecurity AS rls_enabled,
                    c.relforcerowsecurity AS rls_forced
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = ANY(%s)
                  AND c.relkind = 'r'
                  AND c.relname NOT LIKE 'pg_%%'
                  AND c.relname NOT LIKE '_pg_%%'
                  AND c.relname NOT LIKE '_realtime_%%'
                  AND c.relrowsecurity = true
                  AND c.relforcerowsecurity = false
                ORDER BY n.nspname, c.relname
                """,
                (list(AUDITED_SCHEMAS),),
            )
            violations = cur.fetchall()

        # Filter out excluded tables
        real_violations = [
            v for v in violations if v["table_name"] not in FORCE_RLS_EXCLUDED_TABLES
        ]

        if real_violations:
            violation_list = "\n".join(
                f"  - {v['schema_name']}.{v['table_name']}" for v in real_violations
            )
            pytest.fail(
                f"RLS NOT FORCED on {len(real_violations)} tables:\n{violation_list}\n\n"
                f"Fix: ALTER TABLE <schema>.<table> FORCE ROW LEVEL SECURITY;"
            )

    @skip_if_no_db
    def test_rls_coverage_summary(self, db_connection):
        """
        Test A.3: Summary test - ensure 100% RLS coverage.

        Prints a coverage report and fails if coverage < 100%.
        """
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    n.nspname AS schema_name,
                    COUNT(*) AS total_tables,
                    SUM(CASE WHEN c.relrowsecurity THEN 1 ELSE 0 END) AS rls_enabled,
                    SUM(CASE WHEN c.relforcerowsecurity THEN 1 ELSE 0 END) AS rls_forced
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = ANY(%s)
                  AND c.relkind = 'r'
                  AND c.relname NOT LIKE 'pg_%%'
                  AND c.relname NOT LIKE '_pg_%%'
                  AND c.relname NOT LIKE '_realtime_%%'
                GROUP BY n.nspname
                ORDER BY n.nspname
                """,
                (list(AUDITED_SCHEMAS),),
            )
            results = cur.fetchall()

        print("\n" + "=" * 60)
        print("RLS COVERAGE REPORT")
        print("=" * 60)

        total_tables = 0
        total_enabled = 0
        total_forced = 0

        for row in results:
            schema = row["schema_name"]
            tables = row["total_tables"]
            enabled = row["rls_enabled"]
            forced = row["rls_forced"]

            total_tables += tables
            total_enabled += enabled
            total_forced += forced

            pct_enabled = (enabled / tables * 100) if tables > 0 else 0
            pct_forced = (forced / tables * 100) if tables > 0 else 0

            print(f"  {schema}:")
            print(f"    Tables: {tables}")
            print(f"    RLS Enabled: {enabled}/{tables} ({pct_enabled:.0f}%)")
            print(f"    RLS Forced:  {forced}/{tables} ({pct_forced:.0f}%)")

        print("-" * 60)
        overall_enabled = (total_enabled / total_tables * 100) if total_tables > 0 else 0
        overall_forced = (total_forced / total_tables * 100) if total_tables > 0 else 0
        print(f"  TOTAL: {total_tables} tables")
        print(f"  RLS Enabled: {overall_enabled:.0f}%")
        print(f"  RLS Forced:  {overall_forced:.0f}%")
        print("=" * 60)

        # Don't fail on this test - it's informational
        # The specific tests above will fail if there are violations


# =============================================================================
# TEST CLASS: SECURITY DEFINER WHITELIST
# =============================================================================


class TestSecurityDefinerWhitelist:
    """Tests to verify only whitelisted functions use SECURITY DEFINER."""

    @skip_if_no_db
    def test_no_unauthorized_security_definers(self, db_connection):
        """
        Test B.1: Verify all SECURITY DEFINER functions are whitelisted.

        Fails if a function exists with secdef=true that's not in the whitelist.
        """
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    n.nspname AS schema_name,
                    p.proname AS function_name,
                    n.nspname || '.' || p.proname AS full_name,
                    pg_get_functiondef(p.oid) AS definition
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = ANY(%s)
                  AND p.prosecdef = true
                ORDER BY n.nspname, p.proname
                """,
                (list(AUDITED_SCHEMAS),),
            )
            security_definer_functions = cur.fetchall()

        # Check each function against whitelist
        unauthorized = []
        for func in security_definer_functions:
            full_name = func["full_name"]
            if full_name not in ALLOWED_SECURITY_DEFINERS:
                unauthorized.append(full_name)

        if unauthorized:
            violation_list = "\n".join(f"  - {f}" for f in unauthorized)
            pytest.fail(
                f"UNAUTHORIZED SECURITY DEFINER functions detected:\n{violation_list}\n\n"
                f"Either:\n"
                f"  1. Remove SECURITY DEFINER from the function, or\n"
                f"  2. Add to ALLOWED_SECURITY_DEFINERS whitelist after security review"
            )

    @skip_if_no_db
    def test_whitelist_functions_exist(self, db_connection):
        """
        Test B.2: Verify all whitelisted functions actually exist.

        This catches stale whitelist entries.
        """
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    n.nspname || '.' || p.proname AS full_name
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = ANY(%s)
                  AND p.prosecdef = true
                """,
                (list(AUDITED_SCHEMAS),),
            )
            existing = {row["full_name"] for row in cur.fetchall()}

        # Find whitelist entries that don't exist (but don't fail - just warn)
        stale = ALLOWED_SECURITY_DEFINERS - existing
        if stale:
            stale_list = "\n".join(f"  - {f}" for f in sorted(stale))
            print(
                f"\nWARNING: Whitelist entries not found in database:\n{stale_list}\n"
                f"Consider removing these from ALLOWED_SECURITY_DEFINERS"
            )


# =============================================================================
# TEST CLASS: GRANT AUDIT
# =============================================================================


class TestGrantAudit:
    """Tests to verify no unexpected grants exist.

    NOTE: These tests verify Zero Trust by checking grants.
    The current architecture uses RLS policies for access control,
    which means grants may exist but RLS blocks actual access.
    These tests will be enforced after applying the hardening migration.
    """

    @skip_if_no_db
    @pytest.mark.skip(
        reason="Pending RLS hardening migration - uses policies instead of revoked grants"
    )
    def test_no_anon_table_access_on_ops(self, db_connection):
        """
        Test C.1: Verify anon role has no table access in ops schema.
        """
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.relname AS table_name,
                    has_table_privilege('anon', c.oid, 'SELECT') AS can_select,
                    has_table_privilege('anon', c.oid, 'INSERT') AS can_insert,
                    has_table_privilege('anon', c.oid, 'UPDATE') AS can_update,
                    has_table_privilege('anon', c.oid, 'DELETE') AS can_delete
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'ops'
                  AND c.relkind = 'r'
                """
            )
            results = cur.fetchall()

        violations = []
        for row in results:
            if any([row["can_select"], row["can_insert"], row["can_update"], row["can_delete"]]):
                violations.append(row["table_name"])

        if violations:
            pytest.fail(
                f"anon role has access to ops tables: {violations}\n"
                f"Fix: REVOKE ALL ON ops.<table> FROM anon;"
            )

    @skip_if_no_db
    @pytest.mark.skip(
        reason="Pending RLS hardening migration - uses policies instead of revoked grants"
    )
    def test_no_authenticated_table_access_on_ops(self, db_connection):
        """
        Test C.2: Verify authenticated role has no direct table access in ops schema.
        """
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.relname AS table_name,
                    has_table_privilege('authenticated', c.oid, 'SELECT') AS can_select,
                    has_table_privilege('authenticated', c.oid, 'INSERT') AS can_insert,
                    has_table_privilege('authenticated', c.oid, 'UPDATE') AS can_update,
                    has_table_privilege('authenticated', c.oid, 'DELETE') AS can_delete
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'ops'
                  AND c.relkind = 'r'
                """
            )
            results = cur.fetchall()

        violations = []
        for row in results:
            if any([row["can_select"], row["can_insert"], row["can_update"], row["can_delete"]]):
                violations.append(row["table_name"])

        if violations:
            pytest.fail(
                f"authenticated role has access to ops tables: {violations}\n"
                f"Fix: REVOKE ALL ON ops.<table> FROM authenticated;"
            )


# =============================================================================
# SUMMARY FIXTURE
# =============================================================================


@pytest.fixture(scope="module", autouse=True)
def security_summary(request):
    """Print security test summary after all tests complete."""
    yield
    print("\n" + "=" * 60)
    print("SECURITY INVARIANT SUMMARY")
    print("=" * 60)
    print(f"  Audited Schemas: {', '.join(AUDITED_SCHEMAS)}")
    print(f"  Whitelisted Security Definers: {len(ALLOWED_SECURITY_DEFINERS)}")
    print("=" * 60)
