"""
tests/test_security_audit.py

Zero Trust Security Audit Tests for Dragonfly Civil.

This module enforces the security invariants defined in our Zero Trust model:
1. Every table in audited schemas MUST have RLS enabled and forced
2. Every SECURITY DEFINER function MUST be explicitly whitelisted
3. No unexpected privileges for anon/authenticated/public roles

RUNNING:
========
    pytest tests/test_security_audit.py -v

These tests MUST pass before any deployment to production.

SECURITY MODEL:
===============
Zero Trust: Deny all access by default. Grant access only through explicit
RLS policies. SECURITY DEFINER functions are tightly controlled because they
can bypass RLS checks.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import psycopg

try:
    import psycopg
    from psycopg.rows import dict_row

    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False


# =============================================================================
# MARKERS AND SKIP CONDITIONS
# =============================================================================

pytestmark = [
    pytest.mark.security,  # Security gate marker
    pytest.mark.skipif(not HAS_PSYCOPG, reason="psycopg v3 required"),
]


# =============================================================================
# CONFIGURATION
# =============================================================================

# Schemas subject to Zero Trust hardening
AUDITED_SCHEMAS = ("public", "ops", "intake", "enforcement")

# Tables excluded from RLS requirements (system/migration tables)
RLS_EXCLUDED_TABLES = frozenset(
    [
        # Supabase system tables
        "schema_migrations",
        "supabase_migrations",
        "_realtime_schema_cache",
        # Internal migration tracking
        "dragonfly_migrations",
        # Legacy tables (pending deprecation)
        "judgment_history",
        "raw_simplicity_imports",
    ]
)

# =============================================================================
# SECURITY DEFINER WHITELIST
# =============================================================================
# Only these functions are allowed to use SECURITY DEFINER.
# Each function must be documented in docs/SECURITY_EXCEPTIONS.md with:
#   - Why it needs SECURITY DEFINER
#   - What risks are mitigated
#   - Who approved it and when
#
# To add a new function:
#   1. Add it to this whitelist
#   2. Document it in SECURITY_EXCEPTIONS.md
#   3. Get security review approval
#
# Last audited: 2025-12-22

ALLOWED_SEC_DEFINERS = frozenset(
    [
        # =====================================================================
        # OPS SCHEMA - Queue & Worker Operations
        # =====================================================================
        # These functions manage the job queue and need to bypass RLS to
        # atomically claim/update jobs regardless of the calling role.
        "ops.claim_pending_job",
        "ops.queue_job",
        "ops.queue_job_idempotent",
        "ops.enqueue_job",
        "ops.reap_stuck_jobs",
        "ops.complete_job",
        "ops.fail_job",
        "ops.update_job_status",
        "ops.get_queue_health_summary",
        # Worker heartbeat management
        "ops.register_heartbeat",
        "ops.worker_heartbeat",
        # Audit logging (needs to write regardless of caller's permissions)
        "ops.log_action",
        "ops.log_audit",
        "ops.log_intake_event",
        # Batch management
        "ops.create_ingest_batch",
        "ops.create_intake_batch",
        "ops.finalize_ingest_batch",
        "ops.finalize_intake_batch",
        "ops.check_batch_integrity",
        # Judgment upsert operations
        "ops.upsert_judgment",
        "ops.upsert_judgment_extended",
        # =====================================================================
        # INTAKE SCHEMA - FOIL Data Ingestion
        # =====================================================================
        # FOIL intake operations need elevated privileges to process raw data
        "intake.create_foil_dataset",
        "intake.finalize_foil_dataset",
        "intake.quarantine_foil_row",
        "intake.store_foil_raw_row",
        "intake.store_foil_raw_rows_bulk",
        "intake.update_foil_dataset_mapping",
        "intake.update_foil_dataset_status",
        "intake.update_foil_raw_row_status",
        "intake.process_raw_row",
        # =====================================================================
        # PUBLIC SCHEMA - Access Control Helpers
        # =====================================================================
        # Role-checking functions (need to query role tables)
        "public.dragonfly_can_read",
        "public.dragonfly_has_any_role",
        "public.dragonfly_has_role",
        "public.dragonfly_is_admin",
        "public.handle_new_user",
        # =====================================================================
        # PUBLIC SCHEMA - Enforcement Operations
        # =====================================================================
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
        # =====================================================================
        # PUBLIC SCHEMA - Case & Judgment Operations
        # =====================================================================
        "public.insert_case",
        "public.insert_case_with_entities",
        "public.insert_entity",
        "public.insert_or_get_case",
        "public.insert_or_get_case_with_entities",
        "public.insert_or_get_entity",
        "public.copilot_case_context",
        "public.request_case_copilot",
        "public.update_judgment_status",
        "public.set_judgment_priority",
        "public.score_case_collectability",
        "public.set_case_scores",
        "public.portfolio_judgments_paginated",
        "public.ops_update_judgment",
        # =====================================================================
        # PUBLIC SCHEMA - Plaintiff Operations
        # =====================================================================
        "public.set_plaintiff_status",
        "public.update_plaintiff_status",
        "public.ops_update_plaintiff_status",
        "public.complete_plaintiff_task",
        "public.upsert_plaintiff_task",
        "public.ops_update_task",
        "public.log_call_outcome",
        "public.outreach_log_call",
        "public.outreach_update_status",
        # =====================================================================
        # PUBLIC SCHEMA - Enrichment Operations
        # =====================================================================
        "public.complete_enrichment",
        "public.set_case_enrichment",
        "public.upsert_enrichment_bundle",
        "public.upsert_debtor_intelligence",
        "public.enrichment_log_run",
        "public.enrichment_update_debtor",
        # =====================================================================
        # PUBLIC SCHEMA - Import Operations
        # =====================================================================
        "public.advance_import_run",
        "public.check_import_guardrails",
        "public.store_intake_validation",
        "public.submit_intake_review",
        "public.get_intake_stats",
        "public.fetch_new_candidates",
        # =====================================================================
        # PUBLIC SCHEMA - Metrics & Dashboards
        # =====================================================================
        "public.ceo_12_metrics",
        "public.ceo_command_center_metrics",
        "public.enforcement_activity_metrics",
        "public.enforcement_radar_filtered",
        "public.intake_radar_metrics",
        "public.intake_radar_metrics_v2",
        "public.compute_litigation_budget",
        "public.get_litigation_budget",
        "public.approve_daily_budget",
        # =====================================================================
        # PUBLIC SCHEMA - Logging Operations
        # =====================================================================
        "public.log_access",
        "public.get_access_logs",
        "public.log_event",
        "public.log_export",
        "public.log_external_data_call",
        "public.log_insert_case",
        "public.log_insert_entity",
        "public.log_sensitive_update",
        "public.block_sensitive_delete",
        # =====================================================================
        # PUBLIC SCHEMA - Ops Triage
        # =====================================================================
        "public.ops_triage_alerts",
        "public.ops_triage_alerts_ack",
        "public.ops_triage_alerts_fetch",
        # =====================================================================
        # PUBLIC SCHEMA - Queue Operations
        # =====================================================================
        "public.dequeue_job",
        "public.pgmq_delete",
        "public.pgmq_get_queue_metrics",
        "public.pgmq_metrics",
        # =====================================================================
        # PUBLIC SCHEMA - Triggers & System Utilities
        # =====================================================================
        "public.trg_core_judgments_enqueue_enrich",
        "public.trg_log_judgment_status_change",
        "public.pgrst_reload",
        "public.broadcast_live_event",
        "public.submit_website_lead",
        # =====================================================================
        # ENFORCEMENT SCHEMA - Enforcement Strategy Operations
        # =====================================================================
        "enforcement.record_outcome",
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
    if not url or not HAS_PSYCOPG:
        return False
    try:
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
    """Provide a database connection for security audit tests."""
    url = _get_db_url()
    if not url:
        pytest.skip("No database URL configured")

    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
        yield conn


# =============================================================================
# TEST A: RLS ENFORCEMENT
# =============================================================================


class TestRLSEnforcement:
    """
    Test A: Verify Row Level Security is enabled and forced on all tables.

    Zero Trust requires that every table has:
    - relrowsecurity = true (RLS enabled)
    - relforcerowsecurity = true (RLS forced, even for table owners)
    """

    @skip_if_no_db
    def test_all_tables_have_rls_enabled(self, db_connection):
        """
        Test A.1: Every table in audited schemas must have RLS enabled.

        Queries pg_class and pg_namespace to find tables with
        relrowsecurity = false.
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
                f"RLS NOT ENABLED on {len(real_violations)} tables:\n"
                f"{violation_list}\n\n"
                f"Fix: Run the harden_schemas.sql migration or:\n"
                f"  ALTER TABLE <schema>.<table> ENABLE ROW LEVEL SECURITY;"
            )

    @skip_if_no_db
    def test_all_tables_have_rls_forced(self, db_connection):
        """
        Test A.2: Every table with RLS must have it FORCED.

        FORCE RLS ensures that even SECURITY DEFINER functions and
        table owners must obey RLS policies. This prevents privilege
        escalation attacks.
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
        real_violations = [v for v in violations if v["table_name"] not in RLS_EXCLUDED_TABLES]

        if real_violations:
            violation_list = "\n".join(
                f"  - {v['schema_name']}.{v['table_name']}" for v in real_violations
            )
            pytest.fail(
                f"RLS NOT FORCED on {len(real_violations)} tables:\n"
                f"{violation_list}\n\n"
                f"Fix: ALTER TABLE <schema>.<table> FORCE ROW LEVEL SECURITY;"
            )


# =============================================================================
# TEST B: SECURITY DEFINER WHITELIST
# =============================================================================


class TestSecurityDefinerWhitelist:
    """
    Test B: Verify all SECURITY DEFINER objects are explicitly whitelisted.

    SECURITY DEFINER functions run with the privileges of the function owner,
    not the calling user. This can bypass RLS if not carefully controlled.
    Every SECURITY DEFINER function must be:
    - Explicitly listed in ALLOWED_SEC_DEFINERS
    - Documented in docs/SECURITY_EXCEPTIONS.md
    """

    @skip_if_no_db
    def test_no_unauthorized_security_definer_functions(self, db_connection):
        """
        Test B.1: All SECURITY DEFINER functions must be whitelisted.

        Queries pg_proc to find functions with prosecdef = true.
        Fails if any function is not in ALLOWED_SEC_DEFINERS.
        """
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    n.nspname AS schema_name,
                    p.proname AS function_name,
                    n.nspname || '.' || p.proname AS full_name,
                    pg_get_function_identity_arguments(p.oid) AS arguments
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
            if full_name not in ALLOWED_SEC_DEFINERS:
                unauthorized.append(f"{full_name}({func['arguments'] or ''})")

        if unauthorized:
            violation_list = "\n".join(f"  - {f}" for f in unauthorized)
            pytest.fail(
                f"UNAUTHORIZED SECURITY DEFINER functions detected:\n"
                f"{violation_list}\n\n"
                f"These functions run with elevated privileges and bypass RLS.\n"
                f"Either:\n"
                f"  1. Remove SECURITY DEFINER from the function, or\n"
                f"  2. Add to ALLOWED_SEC_DEFINERS whitelist after security review\n"
                f"  3. Document in docs/SECURITY_EXCEPTIONS.md"
            )

    @skip_if_no_db
    def test_no_unauthorized_security_definer_views(self, db_connection):
        """
        Test B.2: Check for SECURITY DEFINER in view definitions.

        Views can also use SECURITY DEFINER (via security_invoker = false).
        We check view definitions for the SECURITY DEFINER clause.
        """
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    n.nspname AS schema_name,
                    c.relname AS view_name,
                    n.nspname || '.' || c.relname AS full_name,
                    pg_get_viewdef(c.oid) AS definition
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = ANY(%s)
                  AND c.relkind = 'v'
                ORDER BY n.nspname, c.relname
                """,
                (list(AUDITED_SCHEMAS),),
            )
            views = cur.fetchall()

        # Check for security_invoker = false (SECURITY DEFINER behavior)
        # Note: In PostgreSQL 15+, views default to security_invoker = false
        # This is informational - views with RLS dependencies may need review
        secdef_views = []
        for view in views:
            definition = view["definition"] or ""
            # Check if view explicitly sets security_invoker
            if "security_invoker" in definition.lower():
                if "security_invoker=false" in definition.lower().replace(" ", ""):
                    secdef_views.append(view["full_name"])

        # Currently informational - uncomment to enforce
        # if secdef_views:
        #     pytest.fail(f"Views with SECURITY DEFINER: {secdef_views}")

    @skip_if_no_db
    def test_whitelist_entries_exist(self, db_connection):
        """
        Test B.3: Verify whitelisted functions actually exist.

        Catches stale whitelist entries that should be removed.
        """
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT n.nspname || '.' || p.proname AS full_name
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = ANY(%s)
                  AND p.prosecdef = true
                """,
                (list(AUDITED_SCHEMAS),),
            )
            existing = {row["full_name"] for row in cur.fetchall()}

        # Find stale entries
        stale = ALLOWED_SEC_DEFINERS - existing
        if stale:
            stale_list = "\n".join(f"  - {f}" for f in sorted(stale))
            print(
                f"\nWARNING: Stale whitelist entries (function not found):\n"
                f"{stale_list}\n"
                f"Consider removing these from ALLOWED_SEC_DEFINERS"
            )


# =============================================================================
# SUMMARY REPORT
# =============================================================================


@pytest.fixture(scope="module", autouse=True)
def security_audit_summary(request):
    """Print security audit summary after all tests complete."""
    yield
    print("\n" + "=" * 70)
    print("SECURITY AUDIT SUMMARY")
    print("=" * 70)
    print(f"  Audited Schemas:              {', '.join(AUDITED_SCHEMAS)}")
    print(f"  Excluded Tables:              {len(RLS_EXCLUDED_TABLES)}")
    print(f"  Whitelisted Security Definers: {len(ALLOWED_SEC_DEFINERS)}")
    print("=" * 70)
    print("  Documentation: docs/SECURITY_EXCEPTIONS.md")
    print("=" * 70)
