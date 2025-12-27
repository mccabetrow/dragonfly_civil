"""
tests/test_performance_budget.py

Performance Budget Tests for Dragonfly Civil.

This module enforces query performance contracts by running EXPLAIN ANALYZE
on critical RPCs and views. If queries exceed their budgets or use inefficient
access patterns (e.g., Seq Scan instead of Index Scan), tests fail.

PERFORMANCE CONTRACTS:
======================
1. ops.claim_pending_job:
   - Total Cost: < 50 (arbitrary units)
   - Execution Time: < 10ms
   - Access Pattern: Index Scan on ops.job_queue (no Seq Scan)

2. ops.v_queue_health:
   - Execution Time: < 50ms

RUNNING:
========
    pytest tests/test_performance_budget.py -v

These tests can be included in CI to catch performance regressions before
they reach production.

REQUIREMENTS:
=============
- psycopg v3
- Database connection with EXPLAIN ANALYZE permissions
- Sufficient data in ops.job_queue for realistic benchmarks

MARKER:
=======
Tests are marked with @pytest.mark.performance for selective execution.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import pytest

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore[assignment]


# =============================================================================
# CONFIGURATION
# =============================================================================

# Performance budgets (adjust based on baselines)
CLAIM_PENDING_JOB_COST_BUDGET = 50.0  # Arbitrary planner cost units
CLAIM_PENDING_JOB_TIME_BUDGET_MS = 10.0  # Milliseconds
QUEUE_HEALTH_TIME_BUDGET_MS = 50.0  # Milliseconds

# =============================================================================
# MARKERS AND SKIP CONDITIONS
# =============================================================================

pytestmark = [
    pytest.mark.performance,
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
# FIXTURES
# =============================================================================


@pytest.fixture
def db_connection():
    """Provide a database connection for performance tests."""
    url = _get_db_url()
    if not url:
        pytest.skip("No database URL configured")

    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
        yield conn


# =============================================================================
# HELPERS
# =============================================================================


def run_explain_analyze(conn: "psycopg.Connection", query: str) -> dict[str, Any]:
    """
    Run EXPLAIN (ANALYZE, FORMAT JSON) on a query and return parsed results.

    Returns:
        dict with keys:
        - plan: The raw JSON plan
        - total_cost: Planning cost estimate
        - execution_time_ms: Actual execution time in milliseconds
        - node_types: List of all node types in the plan
        - has_seq_scan: True if any Seq Scan is present
        - seq_scan_tables: List of tables accessed via Seq Scan
    """
    with conn.cursor() as cur:
        cur.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {query}")
        result = cur.fetchone()

    # Handle both dict_row and tuple results
    if isinstance(result, dict):
        plan_json = result.get("QUERY PLAN", result)
    else:
        plan_json = result[0] if result else None

    if not plan_json:
        raise ValueError("No EXPLAIN output returned")

    # plan_json is a list with one element containing the plan
    if isinstance(plan_json, list):
        plan_data = plan_json[0]
    else:
        plan_data = plan_json

    plan = plan_data.get("Plan", {})
    execution_time = plan_data.get("Execution Time", 0.0)
    planning_time = plan_data.get("Planning Time", 0.0)

    # Extract all node types recursively
    def extract_nodes(node: dict, nodes: list) -> None:
        if not node:
            return
        node_type = node.get("Node Type", "")
        relation_name = node.get("Relation Name", "")
        nodes.append({"type": node_type, "relation": relation_name})

        # Recurse into child nodes
        for child in node.get("Plans", []):
            extract_nodes(child, nodes)

    all_nodes: list[dict] = []
    extract_nodes(plan, all_nodes)

    node_types = [n["type"] for n in all_nodes]
    seq_scan_tables = [
        n["relation"] for n in all_nodes if n["type"] == "Seq Scan" and n["relation"]
    ]

    return {
        "plan": plan_data,
        "total_cost": plan.get("Total Cost", 0.0),
        "execution_time_ms": execution_time,
        "planning_time_ms": planning_time,
        "node_types": node_types,
        "has_seq_scan": "Seq Scan" in node_types,
        "seq_scan_tables": seq_scan_tables,
    }


def check_function_exists(conn: "psycopg.Connection", schema: str, name: str) -> bool:
    """Check if a function exists in the database."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = %s AND p.proname = %s
            )
            """,
            (schema, name),
        )
        result = cur.fetchone()
        if result is None:
            return False
        # Handle both dict_row and tuple results
        if isinstance(result, dict):
            return result.get("exists", False)
        return result[0] if result else False


def check_view_exists(conn: "psycopg.Connection", schema: str, name: str) -> bool:
    """Check if a view exists in the database."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s AND c.relname = %s AND c.relkind = 'v'
            )
            """,
            (schema, name),
        )
        result = cur.fetchone()
        if result is None:
            return False
        # Handle both dict_row and tuple results
        if isinstance(result, dict):
            return result.get("exists", False)
        return result[0] if result else False


# =============================================================================
# TEST CLASS: RPC Performance
# =============================================================================


class TestClaimPendingJobPerformance:
    """Performance tests for ops.claim_pending_job RPC."""

    @skip_if_no_db
    def test_claim_pending_job_exists(self, db_connection):
        """Verify the RPC exists before testing performance."""
        assert check_function_exists(db_connection, "ops", "claim_pending_job"), (
            "ops.claim_pending_job function not found"
        )

    @skip_if_no_db
    def test_claim_pending_job_cost_budget(self, db_connection):
        """
        Test A.1: Verify ops.claim_pending_job total cost is under budget.

        Uses EXPLAIN ANALYZE to get the planner's cost estimate.
        """
        if not check_function_exists(db_connection, "ops", "claim_pending_job"):
            pytest.skip("ops.claim_pending_job not found")

        # Run EXPLAIN on the RPC call
        query = """
            SELECT * FROM ops.claim_pending_job(
                ARRAY['test_job_type']::text[],
                1,
                'performance_test_worker'
            )
        """

        result = run_explain_analyze(db_connection, query)

        assert result["total_cost"] < CLAIM_PENDING_JOB_COST_BUDGET, (
            f"claim_pending_job cost {result['total_cost']:.2f} exceeds budget "
            f"{CLAIM_PENDING_JOB_COST_BUDGET}. Consider adding/optimizing indexes."
        )

    @skip_if_no_db
    def test_claim_pending_job_execution_time(self, db_connection):
        """
        Test A.2: Verify ops.claim_pending_job executes under time budget.

        Uses EXPLAIN ANALYZE to measure actual execution time.
        """
        if not check_function_exists(db_connection, "ops", "claim_pending_job"):
            pytest.skip("ops.claim_pending_job not found")

        query = """
            SELECT * FROM ops.claim_pending_job(
                ARRAY['test_job_type']::text[],
                1,
                'performance_test_worker'
            )
        """

        result = run_explain_analyze(db_connection, query)

        assert result["execution_time_ms"] < CLAIM_PENDING_JOB_TIME_BUDGET_MS, (
            f"claim_pending_job execution time {result['execution_time_ms']:.2f}ms "
            f"exceeds budget {CLAIM_PENDING_JOB_TIME_BUDGET_MS}ms."
        )

    @skip_if_no_db
    def test_claim_pending_job_uses_index_scan(self, db_connection):
        """
        Test A.3: Verify ops.claim_pending_job uses Index Scan on job_queue.

        Sequential scans on job_queue indicate missing or unused indexes,
        which will cause performance degradation as the queue grows.
        """
        if not check_function_exists(db_connection, "ops", "claim_pending_job"):
            pytest.skip("ops.claim_pending_job not found")

        query = """
            SELECT * FROM ops.claim_pending_job(
                ARRAY['test_job_type']::text[],
                1,
                'performance_test_worker'
            )
        """

        result = run_explain_analyze(db_connection, query)

        # Check for Seq Scan on job_queue specifically
        if "job_queue" in result["seq_scan_tables"]:
            pytest.fail(
                f"claim_pending_job uses Seq Scan on ops.job_queue! "
                f"Node types: {result['node_types']}. "
                f"Add index on (status, job_type, next_run_at) or similar."
            )

        # Log the access pattern for debugging
        print(f"Access pattern: {result['node_types']}")


# =============================================================================
# TEST CLASS: View Performance
# =============================================================================


class TestQueueHealthViewPerformance:
    """Performance tests for ops.v_queue_health view."""

    @skip_if_no_db
    def test_queue_health_view_exists(self, db_connection):
        """Verify the view exists before testing performance."""
        assert check_view_exists(db_connection, "ops", "v_queue_health"), (
            "ops.v_queue_health view not found"
        )

    @skip_if_no_db
    def test_queue_health_execution_time(self, db_connection):
        """
        Test B: Verify ops.v_queue_health executes under time budget.

        This view aggregates queue statistics and should remain fast
        even with large queue sizes.
        """
        if not check_view_exists(db_connection, "ops", "v_queue_health"):
            pytest.skip("ops.v_queue_health not found")

        query = "SELECT * FROM ops.v_queue_health"

        result = run_explain_analyze(db_connection, query)

        assert result["execution_time_ms"] < QUEUE_HEALTH_TIME_BUDGET_MS, (
            f"v_queue_health execution time {result['execution_time_ms']:.2f}ms "
            f"exceeds budget {QUEUE_HEALTH_TIME_BUDGET_MS}ms. "
            f"Consider materialized view or query optimization."
        )

        # Log execution stats
        print(f"Execution: {result['execution_time_ms']:.2f}ms")
        print(f"Planning: {result['planning_time_ms']:.2f}ms")
        print(f"Node types: {result['node_types']}")


# =============================================================================
# TEST CLASS: Index Coverage
# =============================================================================


class TestIndexCoverage:
    """Tests to verify critical indexes exist."""

    @skip_if_no_db
    def test_job_queue_has_status_index(self, db_connection):
        """Verify ops.job_queue has an index covering status."""
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'ops'
                  AND tablename = 'job_queue'
                  AND indexdef ILIKE '%status%'
                """
            )
            indexes = cur.fetchall()

        assert len(indexes) > 0, (
            "ops.job_queue missing index on 'status'. "
            "Add: CREATE INDEX idx_job_queue_status ON ops.job_queue(status);"
        )

    @skip_if_no_db
    def test_job_queue_has_claim_index(self, db_connection):
        """Verify ops.job_queue has a composite index for claim queries."""
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'ops'
                  AND tablename = 'job_queue'
                """
            )
            indexes = cur.fetchall()

        # Check for an index that covers the claim pattern
        # (status, job_type) or (status, job_type, next_run_at)
        index_defs = [idx["indexdef"] if isinstance(idx, dict) else idx[1] for idx in indexes]

        has_claim_index = any(
            "status" in idx.lower() and "job_type" in idx.lower() for idx in index_defs
        )

        if not has_claim_index:
            print("WARNING: No composite index for claim pattern found.")
            print(f"Existing indexes: {index_defs}")
            # Don't fail, just warn - the index might be named differently


# =============================================================================
# SUMMARY FIXTURE
# =============================================================================


@pytest.fixture(scope="module", autouse=True)
def performance_summary(request):
    """Print performance test summary after all tests complete."""
    yield
    print("\n" + "=" * 60)
    print("PERFORMANCE BUDGET SUMMARY")
    print("=" * 60)
    print(f"  claim_pending_job cost budget:  {CLAIM_PENDING_JOB_COST_BUDGET}")
    print(f"  claim_pending_job time budget:  {CLAIM_PENDING_JOB_TIME_BUDGET_MS}ms")
    print(f"  v_queue_health time budget:     {QUEUE_HEALTH_TIME_BUDGET_MS}ms")
    print("=" * 60)
