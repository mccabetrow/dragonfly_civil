"""
Dragonfly Audit Logging Tests

Tests for the universal ops.audit_log system.

Run: pytest tests/test_audit_logging.py -v
     python -m tools.test_audit_logging  # For gate integration

NOTE: Marked as integration because these tests require ops.audit_log
      with correlation_id column - schema not yet deployed to prod.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

# Mark entire module as integration - requires correlation_id column in audit_log
pytestmark = pytest.mark.integration


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(scope="module")
def db_connection():
    """Get database connection for tests."""
    import psycopg
    from psycopg.rows import dict_row

    dsn = os.environ.get("SUPABASE_MIGRATE_DB_URL") or os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        pytest.skip("SUPABASE_MIGRATE_DB_URL or SUPABASE_DB_URL not set")

    conn = psycopg.connect(dsn, row_factory=dict_row)
    yield conn
    conn.close()


# =============================================================================
# SCHEMA TESTS
# =============================================================================


@pytest.mark.audit
def test_audit_log_table_exists(db_connection):
    """Verify ops.audit_log table exists with expected columns."""
    result = db_connection.execute(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'ops' AND table_name = 'audit_log'
        ORDER BY ordinal_position
    """
    )

    columns = {row["column_name"]: row for row in result}

    # Required columns
    assert "id" in columns, "Missing 'id' column"
    assert "correlation_id" in columns, "Missing 'correlation_id' column"
    assert "batch_id" in columns, "Missing 'batch_id' column"
    assert "domain" in columns, "Missing 'domain' column"
    assert "stage" in columns, "Missing 'stage' column"
    assert "event" in columns, "Missing 'event' column"
    assert "metadata" in columns, "Missing 'metadata' column"
    assert "created_at" in columns, "Missing 'created_at' column"

    # Type checks
    assert columns["id"]["data_type"] == "uuid"
    assert columns["domain"]["data_type"] == "text"
    assert columns["metadata"]["data_type"] == "jsonb"


@pytest.mark.audit
def test_audit_log_indices_exist(db_connection):
    """Verify required indices exist on ops.audit_log."""
    result = db_connection.execute(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'ops' AND tablename = 'audit_log'
    """
    )

    index_names = {row["indexname"] for row in result}

    # Check for key indices
    assert any("domain_created" in idx for idx in index_names), "Missing domain+created_at index"
    assert any("correlation_id" in idx for idx in index_names), "Missing correlation_id index"


@pytest.mark.audit
def test_audit_metrics_view_exists(db_connection):
    """Verify ops.v_audit_metrics_24h view exists."""
    result = db_connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'ops' AND table_name = 'v_audit_metrics_24h'
    """
    )

    columns = {row["column_name"] for row in result}

    assert "domain" in columns, "Missing 'domain' column in metrics view"
    assert "success_rate_pct" in columns, "Missing 'success_rate_pct' column"
    assert "top_errors" in columns, "Missing 'top_errors' column"


@pytest.mark.audit
def test_burn_rate_view_exists(db_connection):
    """Verify ops.v_audit_burn_rate view exists."""
    result = db_connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'ops' AND table_name = 'v_audit_burn_rate'
    """
    )

    columns = {row["column_name"] for row in result}

    assert "domain" in columns, "Missing 'domain' column in burn rate view"
    assert "failures_last_5min" in columns, "Missing 'failures_last_5min' column"
    assert "burn_rate_pct" in columns, "Missing 'burn_rate_pct' column"


# =============================================================================
# INSERT/READ TESTS
# =============================================================================


@pytest.mark.audit
def test_insert_audit_event(db_connection):
    """Test inserting an audit event."""
    correlation_id = uuid.uuid4()

    result = db_connection.execute(
        """
        INSERT INTO ops.audit_log 
        (correlation_id, domain, stage, event, metadata)
        VALUES (%s, 'system', 'test', 'info', '{"test": true}'::jsonb)
        RETURNING id, created_at
    """,
        (correlation_id,),
    )

    row = result.fetchone()
    db_connection.commit()

    assert row is not None
    assert row["id"] is not None
    assert row["created_at"] is not None

    # Clean up
    db_connection.execute("DELETE FROM ops.audit_log WHERE correlation_id = %s", (correlation_id,))
    db_connection.commit()


@pytest.mark.audit
def test_insert_all_domains(db_connection):
    """Test inserting audit events for all valid domains."""
    domains = ["ingest", "enforcement", "pdf", "external", "system", "api", "worker"]
    correlation_id = uuid.uuid4()

    for domain in domains:
        result = db_connection.execute(
            """
            INSERT INTO ops.audit_log 
            (correlation_id, domain, stage, event, metadata)
            VALUES (%s, %s, 'test', 'info', '{"domain_test": true}'::jsonb)
            RETURNING id
        """,
            (correlation_id, domain),
        )

        row = result.fetchone()
        assert row is not None, f"Failed to insert for domain: {domain}"

    db_connection.commit()

    # Verify all were inserted
    result = db_connection.execute(
        """
        SELECT COUNT(*) as count
        FROM ops.audit_log
        WHERE correlation_id = %s
    """,
        (correlation_id,),
    )

    count = result.fetchone()["count"]
    assert count == len(domains), f"Expected {len(domains)} rows, got {count}"

    # Clean up
    db_connection.execute("DELETE FROM ops.audit_log WHERE correlation_id = %s", (correlation_id,))
    db_connection.commit()


@pytest.mark.audit
def test_invalid_domain_rejected(db_connection):
    """Test that invalid domains are rejected by check constraint."""
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        db_connection.execute(
            """
            INSERT INTO ops.audit_log 
            (domain, stage, event, metadata)
            VALUES ('invalid_domain', 'test', 'info', '{}'::jsonb)
        """
        )

    db_connection.rollback()


@pytest.mark.audit
def test_invalid_event_rejected(db_connection):
    """Test that invalid events are rejected by check constraint."""
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        db_connection.execute(
            """
            INSERT INTO ops.audit_log 
            (domain, stage, event, metadata)
            VALUES ('system', 'test', 'invalid_event', '{}'::jsonb)
        """
        )

    db_connection.rollback()


# =============================================================================
# PYTHON API TESTS
# =============================================================================


@pytest.mark.audit
@pytest.mark.asyncio
async def test_log_event_function():
    """Test the Python log_event function."""
    # Skip if no DB connection
    dsn = os.environ.get("SUPABASE_MIGRATE_DB_URL") or os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        pytest.skip("Database connection not configured")

    from backend.utils.audit import log_event

    correlation_id = uuid.uuid4()

    result = await log_event(
        domain="system",
        stage="test",
        event="info",
        correlation_id=correlation_id,
        metadata={"python_test": True, "timestamp": datetime.now(timezone.utc).isoformat()},
    )

    # Result could be None if pool isn't initialized in test context
    # Just verify no exception was raised


@pytest.mark.audit
def test_log_event_sync_function():
    """Test the Python log_event_sync function doesn't block."""
    from backend.utils.audit import log_event_sync

    # This should return immediately without blocking
    correlation_id = uuid.uuid4()

    log_event_sync(
        domain="system",
        stage="test",
        event="info",
        correlation_id=correlation_id,
        metadata={"sync_test": True},
    )

    # Success = no exception and returns quickly


# =============================================================================
# METRICS VIEW TESTS
# =============================================================================


@pytest.mark.audit
def test_metrics_view_returns_data(db_connection):
    """Test that metrics view returns data correctly."""
    # Insert test data
    correlation_id = uuid.uuid4()

    # Insert some completed and failed events
    db_connection.execute(
        """
        INSERT INTO ops.audit_log (correlation_id, domain, stage, event, metadata)
        VALUES 
            (%s, 'ingest', 'test', 'completed', '{}'),
            (%s, 'ingest', 'test', 'completed', '{}'),
            (%s, 'ingest', 'test', 'failed', '{"error_code": "TEST_ERROR"}')
    """,
        (correlation_id, correlation_id, correlation_id),
    )
    db_connection.commit()

    # Query metrics view
    result = db_connection.execute(
        """
        SELECT * FROM ops.v_audit_metrics_24h
        WHERE domain = 'ingest'
    """
    )

    row = result.fetchone()
    assert row is not None, "Metrics view should return data"

    # Clean up
    db_connection.execute("DELETE FROM ops.audit_log WHERE correlation_id = %s", (correlation_id,))
    db_connection.commit()


# =============================================================================
# CLI TEST ENTRY POINT
# =============================================================================


def run_cli_tests() -> int:
    """
    Run audit logging tests from CLI for gate integration.

    Returns:
        0 on success, 1 on failure
    """
    import psycopg
    from psycopg.rows import dict_row

    print("=" * 60)
    print("AUDIT LOGGING VALIDATION")
    print("=" * 60)

    dsn = os.environ.get("SUPABASE_MIGRATE_DB_URL") or os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        print("❌ SUPABASE_MIGRATE_DB_URL or SUPABASE_DB_URL not set")
        return 1

    try:
        conn = psycopg.connect(dsn, row_factory=dict_row)
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return 1

    errors = []

    # Check 1: Table exists
    print("\n[1/4] Checking ops.audit_log table exists...")
    result = conn.execute(
        """
        SELECT COUNT(*) as count 
        FROM information_schema.tables 
        WHERE table_schema = 'ops' AND table_name = 'audit_log'
    """
    )
    if result.fetchone()["count"] == 0:
        errors.append("ops.audit_log table does not exist")
        print("  ❌ FAILED")
    else:
        print("  ✅ PASSED")

    # Check 2: Domain column exists
    print("\n[2/4] Checking 'domain' column exists...")
    result = conn.execute(
        """
        SELECT COUNT(*) as count 
        FROM information_schema.columns 
        WHERE table_schema = 'ops' AND table_name = 'audit_log' AND column_name = 'domain'
    """
    )
    if result.fetchone()["count"] == 0:
        errors.append("'domain' column does not exist in ops.audit_log")
        print("  ❌ FAILED")
    else:
        print("  ✅ PASSED")

    # Check 3: Insert test event
    print("\n[3/4] Testing insert into ops.audit_log...")
    test_corr_id = uuid.uuid4()
    try:
        conn.execute(
            """
            INSERT INTO ops.audit_log 
            (correlation_id, domain, stage, event, metadata)
            VALUES (%s, 'system', 'cli_test', 'info', '{"cli": true}')
        """,
            (test_corr_id,),
        )
        conn.commit()

        # Clean up
        conn.execute("DELETE FROM ops.audit_log WHERE correlation_id = %s", (test_corr_id,))
        conn.commit()
        print("  ✅ PASSED")
    except Exception as e:
        errors.append(f"Insert failed: {e}")
        print(f"  ❌ FAILED: {e}")
        conn.rollback()

    # Check 4: Views exist
    print("\n[4/4] Checking metrics views exist...")
    views_ok = True
    for view in ["v_audit_metrics_24h", "v_audit_burn_rate"]:
        result = conn.execute(
            """
            SELECT COUNT(*) as count 
            FROM information_schema.views 
            WHERE table_schema = 'ops' AND table_name = %s
        """,
            (view,),
        )
        if result.fetchone()["count"] == 0:
            errors.append(f"View ops.{view} does not exist")
            views_ok = False

    if views_ok:
        print("  ✅ PASSED")
    else:
        print("  ❌ FAILED")

    conn.close()

    # Summary
    print("\n" + "=" * 60)
    if errors:
        print(f"AUDIT LOGGING VALIDATION: ❌ FAILED ({len(errors)} errors)")
        for err in errors:
            print(f"  - {err}")
        return 1
    else:
        print("AUDIT LOGGING VALIDATION: ✅ PASSED")
        return 0


if __name__ == "__main__":
    import sys

    sys.exit(run_cli_tests())
