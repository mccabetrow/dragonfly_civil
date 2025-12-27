"""
Dragonfly System Contract Configuration

This file contains the expected contract hash that the database should return.
When you make schema changes that affect the public API (RPCs, views, tables),
you must update this hash after running the migration.

To get the current hash:
    python -m tools.verify_contract --show-hash

To update after a migration:
    1. Run the migration: DB Push (Dev)
    2. Get new hash: python -m tools.verify_contract --show-hash
    3. Update EXPECTED_CONTRACT_HASH below
    4. Commit the change with the migration

This ensures the frontend/backend code is always in sync with the database schema.
"""

# =============================================================================
# CONTRACT HASH
# =============================================================================
# This hash is calculated from:
# - api.* RPC signatures (name, args, return type)
# - Key public.* RPC signatures
# - Dashboard view schemas (intake.*, ops.*, public.v_*, etc.)
# - Core table columns (judgments, plaintiffs, debtors, entities)
#
# Update this after any schema migration that changes the public interface.
# =============================================================================

EXPECTED_CONTRACT_HASH = "2be7430adc79e8a4a1cadbb07d9372be"

# =============================================================================
# CONTRACT METADATA
# =============================================================================

CONTRACT_VERSION = "1.2.0"
CONTRACT_LAST_UPDATED = "2025-12-27"
CONTRACT_UPDATED_BY = "Zero Trust Hardening + Function Ambiguity Fix + ops views"

# Components included in the contract (for documentation)
CONTRACT_COMPONENTS = {
    "api_rpcs": [
        "api.get_dashboard_stats",
        "api.get_plaintiffs_overview",
        "api.get_judgment_pipeline",
        "api.get_enforcement_overview",
        "api.get_call_queue",
        "api.get_ceo_metrics",
        "api.get_intake_stats",
        "api.get_ingest_timeline",
    ],
    "public_rpcs": [
        "public.ceo_12_metrics",
        "public.ceo_command_center_metrics",
        "public.insert_case",
        "public.insert_case_with_entities",
        "public.get_enforcement_timeline",
        "public.get_intake_stats",
        "public.get_litigation_budget",
        "public.score_case_collectability",
        "public.set_plaintiff_status",
        "public.portfolio_judgments_paginated",
    ],
    "views": [
        "intake.v_*",
        "ops.v_*",
        "public.v_*",
        "analytics.v_*",
        "enforcement.v_*",
    ],
    "tables": [
        "public.judgments",
        "public.plaintiffs",
        "public.debtors",
        "public.entities",
    ],
}
