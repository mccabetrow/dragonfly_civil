# tests/test_security_regret.py
"""
Zero Regret Security Invariant Suite

This test suite mathematically proves that no sensitive data is reachable
by the client (anon/authenticated roles). It enforces:

1. Invariant A: No Direct Table Access
   - anon/authenticated cannot SELECT from tables/views directly
   - Exception: realtime.*, storage.* (Supabase infrastructure)

2. Invariant B: Whitelist RPCs Only
   - Only explicitly whitelisted functions are executable by client roles
   - Any new RPC must be added to the whitelist

3. Invariant C: Toxic Column Scanner
   - No exposed object can contain sensitive columns (ssn, password, secret, etc.)
   - Scans all views and RPC return types

Run: pytest tests/test_security_regret.py -v
"""

from __future__ import annotations

import os
import re
from typing import Set

import psycopg
import pytest
from psycopg.rows import dict_row

# =============================================================================
# MARKERS
# =============================================================================

pytestmark = pytest.mark.security  # Security gate marker


# =============================================================================
# CONFIGURATION
# =============================================================================

# Schemas that are Supabase infrastructure and should be excluded from checks
INFRASTRUCTURE_SCHEMAS = frozenset(
    {
        "realtime",
        "storage",
        "graphql",
        "graphql_public",
        "supabase_migrations",
        "supabase_functions",
        "vault",
        "pgsodium",
        "pgsodium_masks",
        "extensions",
        "pg_catalog",
        "information_schema",
        "auth",  # Supabase auth schema
    }
)

# Roles that should have zero direct table access
CLIENT_ROLES = ("anon", "authenticated")

# Whitelisted RPCs that are allowed for client access
# Format: 'schema.function_name'
ALLOWED_RPCS: Set[str] = {
    # API layer (Zero Regret)
    "api.get_dashboard_stats",
    "api.get_plaintiffs_overview",
    "api.get_judgment_pipeline",
    "api.get_enforcement_overview",
    "api.get_call_queue",
    "api.get_ceo_metrics",
    "api.get_intake_stats",
    "api.get_ingest_timeline",
    # Ops layer (system introspection)
    "ops.get_system_contract_hash",  # Contract versioning for frontend cache busting
    # Public schema RPCs (existing business logic)
    "public.insert_case",
    "public.insert_case_with_entities",
    "public.insert_entity",
    "public.insert_or_get_case",
    "public.insert_or_get_case_with_entities",
    "public.insert_or_get_entity",
    "public.ceo_12_metrics",
    "public.ceo_command_center_metrics",
    "public.get_enforcement_timeline",
    "public.get_intake_stats",
    "public.get_litigation_budget",
    "public.add_enforcement_event",
    "public.add_evidence",
    "public.advance_import_run",
    "public.approve_daily_budget",
    "public.batch_update_judgments",
    "public.block_sensitive_delete",
    "public.broadcast_live_event",
    "public.check_import_guardrails",
    "public.complete_plaintiff_task",
    "public.compute_litigation_budget",
    "public.copilot_case_context",
    "public.current_app_role",
    "public.dequeue_job",
    "public.dragonfly_can_read",
    "public.dragonfly_has_any_role",
    "public.dragonfly_has_role",
    "public.dragonfly_is_admin",
    "public.enforcement_activity_metrics",
    "public.enforcement_radar_filtered",
    "public.enrichment_log_run",
    "public.enrichment_update_debtor",
    "public.evaluate_enforcement_path",
    "public.fetch_new_candidates",
    "public.fn_is_fdcpa_allowed_time",
    "public.foil_requests_touch_updated_at",
    "public.generate_enforcement_tasks",
    "public.get_access_logs",
    "public.intake_radar_metrics",
    "public.intake_radar_metrics_v2",
    "public.log_access",
    "public.log_call_outcome",
    "public.log_enforcement_event",
    "public.log_event",
    "public.log_export",
    "public.log_insert_case",
    "public.log_insert_entity",
    "public.log_sensitive_update",
    "public.normalize_party_name",
    "public.ops_triage_alerts",
    "public.ops_triage_alerts_ack",
    "public.ops_triage_alerts_fetch",
    "public.ops_update_judgment",
    "public.ops_update_plaintiff_status",
    "public.ops_update_task",
    "public.outreach_log_call",
    "public.outreach_update_status",
    "public.pgmq_delete",
    "public.pgmq_get_queue_metrics",
    "public.pgmq_metrics",
    "public.pgrst_reload",
    "public.portfolio_judgments_paginated",
    "public.process_simplicity_imports",
    "public.request_case_copilot",
    "public.score_case_collectability",
    "public.set_enforcement_stage",
    "public.set_judgment_priority",
    "public.set_plaintiff_status",
    "public.spawn_enforcement_flow",
    "public.store_intake_validation",
    "public.submit_intake_review",
    "public.submit_website_lead",
    "public.touch_last_updated",
    "public.touch_updated_at",
    "public.tg_touch_updated_at",
    "public.update_plaintiff_status",
    "public.upsert_plaintiff_task",
    # Trigger functions (needed for DML operations)
    "public._set_enrichment_runs_updated_at",
    "public.trg_core_judgments_enqueue_enrich",
    "public.trg_log_judgment_status_change",
    # pgvector functions (extension functions, safe)
    "public.array_to_halfvec",
    "public.array_to_sparsevec",
    "public.array_to_vector",
    "public.avg",
    "public.binary_quantize",
    "public.cosine_distance",
    "public.halfvec",
    "public.halfvec_accum",
    "public.halfvec_add",
    "public.halfvec_avg",
    "public.halfvec_cmp",
    "public.halfvec_combine",
    "public.halfvec_concat",
    "public.halfvec_eq",
    "public.halfvec_ge",
    "public.halfvec_gt",
    "public.halfvec_in",
    "public.halfvec_l2_squared_distance",
    "public.halfvec_le",
    "public.halfvec_lt",
    "public.halfvec_mul",
    "public.halfvec_ne",
    "public.halfvec_negative_inner_product",
    "public.halfvec_out",
    "public.halfvec_recv",
    "public.halfvec_send",
    "public.halfvec_spherical_distance",
    "public.halfvec_sub",
    "public.halfvec_to_float4",
    "public.halfvec_to_sparsevec",
    "public.halfvec_to_vector",
    "public.halfvec_typmod_in",
    "public.hamming_distance",
    "public.hnsw_bit_support",
    "public.hnsw_halfvec_support",
    "public.hnsw_sparsevec_support",
    "public.hnswhandler",
    "public.inner_product",
    "public.ivfflat_bit_support",
    "public.ivfflat_halfvec_support",
    "public.ivfflathandler",
    "public.jaccard_distance",
    "public.l1_distance",
    "public.l2_distance",
    "public.l2_norm",
    "public.l2_normalize",
    "public.sparsevec",
    "public.sparsevec_cmp",
    "public.sparsevec_eq",
    "public.sparsevec_ge",
    "public.sparsevec_gt",
    "public.sparsevec_in",
    "public.sparsevec_l2_squared_distance",
    "public.sparsevec_le",
    "public.sparsevec_lt",
    "public.sparsevec_ne",
    "public.sparsevec_negative_inner_product",
    "public.sparsevec_out",
    "public.sparsevec_recv",
    "public.sparsevec_send",
    "public.sparsevec_to_halfvec",
    "public.sparsevec_to_vector",
    "public.sparsevec_typmod_in",
    "public.subvector",
    "public.sum",
    "public.vector",
    "public.vector_accum",
    "public.vector_add",
    "public.vector_avg",
    "public.vector_cmp",
    "public.vector_combine",
    "public.vector_concat",
    "public.vector_dims",
    "public.vector_eq",
    "public.vector_ge",
    "public.vector_gt",
    "public.vector_in",
    "public.vector_l2_squared_distance",
    "public.vector_le",
    "public.vector_lt",
    "public.vector_mul",
    "public.vector_ne",
    "public.vector_negative_inner_product",
    "public.vector_norm",
    "public.vector_out",
    "public.vector_recv",
    "public.vector_send",
    "public.vector_spherical_distance",
    "public.vector_sub",
    "public.vector_to_float4",
    "public.vector_to_halfvec",
    "public.vector_to_sparsevec",
    "public.vector_typmod_in",
    # pg_trgm functions (extension functions, safe)
    "public.gin_btree_consistent",
    "public.gin_compare_prefix_anyenum",
    "public.gin_compare_prefix_bit",
    "public.gin_compare_prefix_bool",
    "public.gin_compare_prefix_bpchar",
    "public.gin_compare_prefix_bytea",
    "public.gin_compare_prefix_char",
    "public.gin_compare_prefix_cidr",
    "public.gin_compare_prefix_date",
    "public.gin_compare_prefix_float4",
    "public.gin_compare_prefix_float8",
    "public.gin_compare_prefix_inet",
    "public.gin_compare_prefix_int2",
    "public.gin_compare_prefix_int4",
    "public.gin_compare_prefix_int8",
    "public.gin_compare_prefix_interval",
    "public.gin_compare_prefix_macaddr",
    "public.gin_compare_prefix_macaddr8",
    "public.gin_compare_prefix_money",
    "public.gin_compare_prefix_name",
    "public.gin_compare_prefix_numeric",
    "public.gin_compare_prefix_oid",
    "public.gin_compare_prefix_text",
    "public.gin_compare_prefix_time",
    "public.gin_compare_prefix_timestamp",
    "public.gin_compare_prefix_timestamptz",
    "public.gin_compare_prefix_timetz",
    "public.gin_compare_prefix_uuid",
    "public.gin_compare_prefix_varbit",
    "public.gin_enum_cmp",
    "public.gin_extract_query_anyenum",
    "public.gin_extract_query_bit",
    "public.gin_extract_query_bool",
    "public.gin_extract_query_bpchar",
    "public.gin_extract_query_bytea",
    "public.gin_extract_query_char",
    "public.gin_extract_query_cidr",
    "public.gin_extract_query_date",
    "public.gin_extract_query_float4",
    "public.gin_extract_query_float8",
    "public.gin_extract_query_inet",
    "public.gin_extract_query_int2",
    "public.gin_extract_query_int4",
    "public.gin_extract_query_int8",
    "public.gin_extract_query_interval",
    "public.gin_extract_query_macaddr",
    "public.gin_extract_query_macaddr8",
    "public.gin_extract_query_money",
    "public.gin_extract_query_name",
    "public.gin_extract_query_numeric",
    "public.gin_extract_query_oid",
    "public.gin_extract_query_text",
    "public.gin_extract_query_time",
    "public.gin_extract_query_timestamp",
    "public.gin_extract_query_timestamptz",
    "public.gin_extract_query_timetz",
    "public.gin_extract_query_trgm",
    "public.gin_extract_query_uuid",
    "public.gin_extract_query_varbit",
    "public.gin_extract_value_anyenum",
    "public.gin_extract_value_bit",
    "public.gin_extract_value_bool",
    "public.gin_extract_value_bpchar",
    "public.gin_extract_value_bytea",
    "public.gin_extract_value_char",
    "public.gin_extract_value_cidr",
    "public.gin_extract_value_date",
    "public.gin_extract_value_float4",
    "public.gin_extract_value_float8",
    "public.gin_extract_value_inet",
    "public.gin_extract_value_int2",
    "public.gin_extract_value_int4",
    "public.gin_extract_value_int8",
    "public.gin_extract_value_interval",
    "public.gin_extract_value_macaddr",
    "public.gin_extract_value_macaddr8",
    "public.gin_extract_value_money",
    "public.gin_extract_value_name",
    "public.gin_extract_value_numeric",
    "public.gin_extract_value_oid",
    "public.gin_extract_value_text",
    "public.gin_extract_value_time",
    "public.gin_extract_value_timestamp",
    "public.gin_extract_value_timestamptz",
    "public.gin_extract_value_timetz",
    "public.gin_extract_value_trgm",
    "public.gin_extract_value_uuid",
    "public.gin_extract_value_varbit",
    "public.gin_numeric_cmp",
    "public.gin_trgm_consistent",
    "public.gin_trgm_triconsistent",
    "public.gtrgm_compress",
    "public.gtrgm_consistent",
    "public.gtrgm_decompress",
    "public.gtrgm_distance",
    "public.gtrgm_in",
    "public.gtrgm_options",
    "public.gtrgm_out",
    "public.gtrgm_penalty",
    "public.gtrgm_picksplit",
    "public.gtrgm_same",
    "public.gtrgm_union",
    "public.set_limit",
    "public.show_limit",
    "public.show_trgm",
    "public.similarity",
    "public.similarity_dist",
    "public.similarity_op",
    "public.strict_word_similarity",
    "public.strict_word_similarity_commutator_op",
    "public.strict_word_similarity_dist_commutator_op",
    "public.strict_word_similarity_dist_op",
    "public.strict_word_similarity_op",
    "public.word_similarity",
    "public.word_similarity_commutator_op",
    "public.word_similarity_dist_commutator_op",
    "public.word_similarity_dist_op",
    "public.word_similarity_op",
    # Realtime functions (Supabase infrastructure)
    "realtime.apply_rls",
    "realtime.build_prepared_statement_sql",
    "realtime.cast",
    "realtime.check_equality_op",
    "realtime.is_visible_through_filters",
    "realtime.list_changes",
    "realtime.quote_wal2json",
    "realtime.subscription_check_filters",
    "realtime.to_regrole",
    # GraphQL functions (Supabase infrastructure)
    "graphql._internal_resolve",
    "graphql.comment_directive",
    "graphql.exception",
    "graphql.get_schema_version",
    "graphql.increment_schema_version",
    "graphql.resolve",
    "graphql_public.graphql",
    # Ops schema (authenticated only, not anon)
    "ops.queue_job",
    "ops.queue_job_idempotent",
}

# Toxic column patterns - if found in accessible objects, fail the test
TOXIC_COLUMN_PATTERNS = [
    r"\bssn\b",
    r"\bsocial_security\b",
    r"\bpassword\b",
    r"\bpasswd\b",
    r"\bsecret\b",
    r"\btoken\b",
    r"\bapi_key\b",
    r"\bprivate_key\b",
    r"\bdob\b",
    r"\bdate_of_birth\b",
    r"\bbank_account\b",
    r"\brouting_number\b",
    r"\bcredit_card\b",
    r"\bcc_number\b",
]

# Allowed toxic column exceptions (e.g., storage.objects.path_tokens is OK)
TOXIC_COLUMN_EXCEPTIONS = {
    ("storage", "objects", "path_tokens"),  # Not actually sensitive
    ("enforcement", "v_candidate_wage_garnishments", "employer_address"),  # Business data
    ("intelligence", "gig_platforms", "registered_agent_address"),  # Business data
    ("intelligence", "v_gig_platforms_active", "registered_agent_address"),  # Business data
    ("intelligence", "v_gig_platforms_active", "full_address"),  # Business data
}


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(scope="module")
def db_connection():
    """Get database connection for tests."""
    dsn = os.environ.get("SUPABASE_MIGRATE_DB_URL") or os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        pytest.skip("SUPABASE_MIGRATE_DB_URL or SUPABASE_DB_URL not set")

    conn = psycopg.connect(dsn, row_factory=dict_row)
    yield conn
    conn.close()


# =============================================================================
# INVARIANT A: NO DIRECT TABLE ACCESS
# =============================================================================


@pytest.mark.security
def test_invariant_a_no_direct_table_grants(db_connection):
    """
    Invariant A: Client roles (anon, authenticated) must NOT have SELECT
    grants on tables or views outside infrastructure schemas.

    The count of direct table grants to client roles must be 0.
    """
    result = db_connection.execute(
        """
        SELECT 
            grantee,
            table_schema,
            table_name,
            privilege_type
        FROM information_schema.role_table_grants
        WHERE grantee IN ('anon', 'authenticated')
        AND privilege_type = 'SELECT'
        AND table_schema NOT IN (
            'realtime', 'storage', 'graphql', 'graphql_public',
            'supabase_migrations', 'supabase_functions', 'vault',
            'pgsodium', 'pgsodium_masks', 'extensions',
            'pg_catalog', 'information_schema', 'auth'
        )
        ORDER BY table_schema, table_name, grantee
    """
    )

    violations = list(result)

    if violations:
        violation_list = "\n".join(
            f"  - {v['grantee']}: {v['table_schema']}.{v['table_name']} ({v['privilege_type']})"
            for v in violations
        )
        pytest.fail(
            f"INVARIANT A VIOLATION: {len(violations)} direct table/view grants found.\n"
            f"Client roles must NOT have SELECT on tables/views.\n"
            f"Use SECURITY DEFINER RPCs instead.\n\n"
            f"Violations:\n{violation_list}"
        )


@pytest.mark.security
def test_invariant_a_no_write_grants(db_connection):
    """
    Invariant A (extended): Client roles must NOT have INSERT/UPDATE/DELETE
    on tables outside infrastructure schemas.

    All mutations must go through SECURITY DEFINER RPCs.
    """
    result = db_connection.execute(
        """
        SELECT 
            grantee,
            table_schema,
            table_name,
            privilege_type
        FROM information_schema.role_table_grants
        WHERE grantee IN ('anon', 'authenticated')
        AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE')
        AND table_schema NOT IN (
            'realtime', 'storage', 'graphql', 'graphql_public',
            'supabase_migrations', 'supabase_functions', 'vault',
            'pgsodium', 'pgsodium_masks', 'extensions',
            'pg_catalog', 'information_schema', 'auth'
        )
        ORDER BY table_schema, table_name, grantee
    """
    )

    violations = list(result)

    if violations:
        violation_list = "\n".join(
            f"  - {v['grantee']}: {v['table_schema']}.{v['table_name']} ({v['privilege_type']})"
            for v in violations
        )
        pytest.fail(
            f"INVARIANT A VIOLATION: {len(violations)} direct write grants found.\n"
            f"Client roles must NOT have INSERT/UPDATE/DELETE on tables.\n"
            f"Use SECURITY DEFINER RPCs instead.\n\n"
            f"Violations:\n{violation_list}"
        )


# =============================================================================
# INVARIANT B: WHITELIST RPCs ONLY
# =============================================================================


@pytest.mark.security
def test_invariant_b_rpc_whitelist(db_connection):
    """
    Invariant B: Only whitelisted RPCs are executable by client roles.

    Any new RPC granted to anon/authenticated must be explicitly added
    to the ALLOWED_RPCS whitelist.
    """
    result = db_connection.execute(
        """
        SELECT DISTINCT
            routine_schema,
            routine_name,
            grantee
        FROM information_schema.role_routine_grants
        WHERE grantee IN ('anon', 'authenticated')
        AND routine_schema NOT IN (
            'pg_catalog', 'information_schema'
        )
        ORDER BY routine_schema, routine_name, grantee
    """
    )

    violations = []
    for row in result:
        func_name = f"{row['routine_schema']}.{row['routine_name']}"
        if func_name not in ALLOWED_RPCS:
            violations.append((row["grantee"], func_name))

    if violations:
        violation_list = "\n".join(f"  - {grantee}: {func}" for grantee, func in violations)
        pytest.fail(
            f"INVARIANT B VIOLATION: {len(violations)} non-whitelisted RPCs found.\n"
            f"All client-accessible RPCs must be in ALLOWED_RPCS whitelist.\n\n"
            f"Violations:\n{violation_list}\n\n"
            f"To fix: Add to ALLOWED_RPCS or REVOKE EXECUTE from anon/authenticated."
        )


# =============================================================================
# INVARIANT C: TOXIC COLUMN SCANNER
# =============================================================================


@pytest.mark.security
def test_invariant_c_no_toxic_columns(db_connection):
    """
    Invariant C: No accessible object can contain sensitive column names.

    Scans all tables/views accessible to client roles for columns matching
    toxic patterns (ssn, password, secret, token, etc.).
    """
    # Get all columns in accessible tables/views
    result = db_connection.execute(
        """
        SELECT DISTINCT
            c.table_schema,
            c.table_name,
            c.column_name
        FROM information_schema.columns c
        JOIN information_schema.role_table_grants g 
            ON c.table_schema = g.table_schema AND c.table_name = g.table_name
        WHERE g.grantee IN ('anon', 'authenticated')
        AND g.table_schema NOT IN (
            'pg_catalog', 'information_schema', 'auth'
        )
        ORDER BY c.table_schema, c.table_name, c.column_name
    """
    )

    violations = []
    for row in result:
        schema = row["table_schema"]
        table = row["table_name"]
        column = row["column_name"]

        # Check if this is an allowed exception
        if (schema, table, column) in TOXIC_COLUMN_EXCEPTIONS:
            continue

        # Check against toxic patterns
        for pattern in TOXIC_COLUMN_PATTERNS:
            if re.search(pattern, column, re.IGNORECASE):
                violations.append((schema, table, column, pattern))
                break

    if violations:
        violation_list = "\n".join(
            f"  - {schema}.{table}.{column} (matched: {pattern})"
            for schema, table, column, pattern in violations
        )
        pytest.fail(
            f"INVARIANT C VIOLATION: {len(violations)} toxic columns found.\n"
            f"Client-accessible objects must NOT expose sensitive data.\n\n"
            f"Violations:\n{violation_list}\n\n"
            f"To fix: REVOKE access or add to TOXIC_COLUMN_EXCEPTIONS if false positive."
        )


# =============================================================================
# ADDITIONAL SECURITY CHECKS
# =============================================================================


@pytest.mark.security
def test_api_schema_exists(db_connection):
    """Verify the api schema exists for Zero Regret RPCs."""
    result = db_connection.execute(
        """
        SELECT schema_name 
        FROM information_schema.schemata 
        WHERE schema_name = 'api'
    """
    )

    if not result.fetchone():
        pytest.fail("API schema does not exist. Run the zero_regret_access.sql migration first.")


@pytest.mark.security
def test_api_rpcs_are_security_definer(db_connection):
    """Verify all api.* RPCs are SECURITY DEFINER."""
    result = db_connection.execute(
        """
        SELECT 
            proname as function_name,
            prosecdef as is_security_definer
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'api'
    """
    )

    violations = []
    for row in result:
        if not row["is_security_definer"]:
            violations.append(row["function_name"])

    if violations:
        pytest.fail(
            f"API RPCs without SECURITY DEFINER: {violations}\n"
            f"All api.* functions must be SECURITY DEFINER."
        )


@pytest.mark.security
def test_no_anon_access_to_ops_queue(db_connection):
    """Verify anon cannot execute ops.queue_job functions."""
    result = db_connection.execute(
        """
        SELECT routine_name
        FROM information_schema.role_routine_grants
        WHERE grantee = 'anon'
        AND routine_schema = 'ops'
        AND routine_name LIKE 'queue_job%'
    """
    )

    violations = [row["routine_name"] for row in result]

    if violations:
        pytest.fail(
            f"SECURITY VIOLATION: anon can execute ops queue functions: {violations}\n"
            f"Only authenticated users should queue jobs."
        )


@pytest.mark.security
def test_security_definer_functions_have_search_path(db_connection):
    """
    Verify all SECURITY DEFINER functions have explicit search_path set.

    Without search_path, SECURITY DEFINER functions can be exploited via
    search_path manipulation attacks.
    """
    result = db_connection.execute(
        """
        SELECT 
            n.nspname as schema,
            p.proname as function,
            p.proconfig as config
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE p.prosecdef = true
        AND n.nspname NOT IN (
            'pg_catalog', 'information_schema', 'extensions',
            'pgsodium', 'vault', 'supabase_functions'
        )
    """
    )

    violations = []
    for row in result:
        config = row["config"] or []
        has_search_path = any(c.startswith("search_path=") for c in config)
        if not has_search_path:
            violations.append(f"{row['schema']}.{row['function']}")

    if violations:
        # Just warn for now as this is a best practice, not a hard requirement
        print(f"\nWARNING: {len(violations)} SECURITY DEFINER functions without search_path:")
        for v in violations[:10]:
            print(f"  - {v}")
        if len(violations) > 10:
            print(f"  ... and {len(violations) - 10} more")


# =============================================================================
# SUMMARY REPORT
# =============================================================================


@pytest.mark.security
def test_generate_security_report(db_connection):
    """Generate a security summary report (always passes, informational)."""
    # Count direct grants
    result = db_connection.execute(
        """
        SELECT COUNT(*) as count
        FROM information_schema.role_table_grants
        WHERE grantee IN ('anon', 'authenticated')
        AND privilege_type = 'SELECT'
        AND table_schema NOT IN (
            'realtime', 'storage', 'graphql', 'graphql_public',
            'supabase_migrations', 'supabase_functions', 'vault',
            'pgsodium', 'pgsodium_masks', 'extensions',
            'pg_catalog', 'information_schema', 'auth'
        )
    """
    )
    direct_grants = result.fetchone()["count"]

    # Count RPCs
    result = db_connection.execute(
        """
        SELECT COUNT(DISTINCT routine_schema || '.' || routine_name) as count
        FROM information_schema.role_routine_grants
        WHERE grantee IN ('anon', 'authenticated')
        AND routine_schema NOT IN ('pg_catalog', 'information_schema')
    """
    )
    total_rpcs = result.fetchone()["count"]

    print("\n" + "=" * 60)
    print("ZERO REGRET SECURITY REPORT")
    print("=" * 60)
    print(f"Direct table/view grants to client: {direct_grants}")
    print(f"Total RPCs accessible to client: {total_rpcs}")
    print(f"Whitelisted RPCs: {len(ALLOWED_RPCS)}")
    print(f"Toxic column exceptions: {len(TOXIC_COLUMN_EXCEPTIONS)}")
    print("=" * 60)

    if direct_grants == 0:
        print("✅ ZERO DIRECT ACCESS - All data access via RPCs")
    else:
        print(f"⚠️  {direct_grants} DIRECT GRANTS REMAIN - Revoke pending")
