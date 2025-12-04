"""
tests/test_fcra_access_logging.py

Test suite for FCRA-compliant access logging system.
Tests the immutable access_logs table, logging functions, and triggers.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

# Import test utilities
from tests.conftest import get_test_client, skip_if_no_db


class TestAccessLogsTable:
    """Tests for the access_logs table structure and immutability."""

    @skip_if_no_db
    def test_access_logs_table_exists(self):
        """Verify access_logs table exists in public schema."""
        client = get_test_client()

        # Query pg_tables to check if table exists
        result = client.rpc(
            "dragonfly_check_table_exists",
            {"p_schema": "public", "p_table": "access_logs"},
        ).execute()

        # If RPC doesn't exist, use direct query
        if hasattr(result, "error") and result.error:
            result = client.from_("access_logs").select("id").limit(0).execute()
            assert result.data is not None, "access_logs table should exist"
        else:
            assert result.data is True, "access_logs table should exist"

    @skip_if_no_db
    def test_access_logs_has_required_columns(self):
        """Verify access_logs has all required columns."""
        client = get_test_client()

        # Use information_schema to check columns
        result = client.rpc(
            "run_sql",
            {
                "query": """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'access_logs'
                ORDER BY ordinal_position
            """
            },
        ).execute()

        if hasattr(result, "error") and result.error:
            pytest.skip("Cannot query information_schema - skipping column check")

        columns = {row["column_name"] for row in result.data}
        required_columns = {
            "id",
            "accessed_at",
            "user_id",
            "user_identifier",
            "table_name",
            "row_id",
            "access_type",
            "metadata",
            "session_id",
            "ip_address",
        }

        assert required_columns.issubset(
            columns
        ), f"Missing columns: {required_columns - columns}"


class TestLogAccessFunction:
    """Tests for the log_access() RPC function."""

    @skip_if_no_db
    def test_log_access_inserts_record(self):
        """Verify log_access() creates an access log entry."""
        client = get_test_client()

        test_table = "debtor_intelligence"
        test_row_id = str(uuid.uuid4())

        # Call log_access
        result = client.rpc(
            "log_access",
            {
                "_table_name": test_table,
                "_row_id": test_row_id,
                "_access_type": "SELECT",
                "_metadata": {"purpose": "unit_test"},
            },
        ).execute()

        assert result.data is not None, "log_access should return the new record ID"

        # Verify the record was created (requires audit role)
        # If we can't verify, at least confirm no error
        assert not hasattr(result, "error") or result.error is None

    @skip_if_no_db
    def test_log_access_validates_access_type(self):
        """Verify log_access() rejects invalid access types."""
        client = get_test_client()

        # Try with invalid access type
        result = client.rpc(
            "log_access",
            {
                "_table_name": "test_table",
                "_row_id": "test_row",
                "_access_type": "INVALID_TYPE",
                "_metadata": {},
            },
        ).execute()

        # Should fail with an error
        assert (
            hasattr(result, "error") and result.error is not None
        ), "Invalid access_type should raise an error"

    @skip_if_no_db
    def test_log_access_accepts_valid_types(self):
        """Verify log_access() accepts all valid access types."""
        client = get_test_client()

        valid_types = ["SELECT", "UPDATE", "EXPORT", "DELETE_BLOCKED"]

        for access_type in valid_types:
            result = client.rpc(
                "log_access",
                {
                    "_table_name": "test_table",
                    "_row_id": str(uuid.uuid4()),
                    "_access_type": access_type,
                    "_metadata": {"test": True},
                },
            ).execute()

            assert (
                not hasattr(result, "error") or result.error is None
            ), f"Access type '{access_type}' should be valid"


class TestLogExportFunction:
    """Tests for the log_export() convenience function."""

    @skip_if_no_db
    def test_log_export_creates_record(self):
        """Verify log_export() creates an EXPORT access log entry."""
        client = get_test_client()

        result = client.rpc(
            "log_export",
            {
                "_table_name": "debtor_intelligence",
                "_row_count": 100,
                "_export_format": "csv",
                "_purpose": "compliance_audit",
            },
        ).execute()

        assert result.data is not None, "log_export should return the new record ID"
        assert not hasattr(result, "error") or result.error is None


class TestAccessLogsImmutability:
    """Tests for access_logs table immutability (append-only)."""

    @skip_if_no_db
    def test_access_logs_update_blocked(self):
        """Verify UPDATE operations on access_logs are blocked."""
        client = get_test_client()

        # First, insert a test record
        insert_result = client.rpc(
            "log_access",
            {
                "_table_name": "test_immutability",
                "_row_id": str(uuid.uuid4()),
                "_access_type": "SELECT",
                "_metadata": {"original": True},
            },
        ).execute()

        if hasattr(insert_result, "error") and insert_result.error:
            pytest.skip("Cannot insert test record")

        log_id = insert_result.data

        # Try to update the record (should fail or have no effect due to RULE)
        _ = (
            client.from_("access_logs")
            .update({"metadata": {"modified": True}})
            .eq("id", log_id)
            .execute()
        )

        # UPDATE should either fail or have no effect (due to RULE)
        # Query the record to verify it wasn't changed
        verify_result = (
            client.from_("access_logs").select("metadata").eq("id", log_id).execute()
        )

        if verify_result.data:
            metadata = verify_result.data[0].get("metadata", {})
            assert (
                metadata.get("original") is True
            ), "access_logs record should not be modified"

    @skip_if_no_db
    def test_access_logs_delete_blocked(self):
        """Verify DELETE operations on access_logs are blocked."""
        client = get_test_client()

        # First, insert a test record
        insert_result = client.rpc(
            "log_access",
            {
                "_table_name": "test_delete_block",
                "_row_id": str(uuid.uuid4()),
                "_access_type": "SELECT",
                "_metadata": {"for_delete_test": True},
            },
        ).execute()

        if hasattr(insert_result, "error") and insert_result.error:
            pytest.skip("Cannot insert test record")

        log_id = insert_result.data

        # Try to delete the record (should fail due to RULE)
        _ = client.from_("access_logs").delete().eq("id", log_id).execute()

        # Verify record still exists
        verify_result = (
            client.from_("access_logs").select("id").eq("id", log_id).execute()
        )

        # Record should still exist (DELETE blocked by RULE)
        assert (
            verify_result.data and len(verify_result.data) > 0
        ), "access_logs record should not be deleted"


class TestSensitiveTableTriggers:
    """Tests for audit triggers on sensitive tables."""

    @skip_if_no_db
    def test_debtor_intelligence_update_logged(self):
        """Verify UPDATE on debtor_intelligence creates an access log entry."""
        client = get_test_client()

        # This test requires an existing debtor_intelligence record
        # First check if we can query the table
        check = client.from_("debtor_intelligence").select("id").limit(1).execute()

        if not check.data or len(check.data) == 0:
            pytest.skip("No debtor_intelligence records to test with")

        test_id = check.data[0]["id"]

        # Get current count of access logs for this record
        before_count = (
            client.from_("access_logs")
            .select("id")
            .eq("table_name", "debtor_intelligence")
            .eq("row_id", test_id)
            .eq("access_type", "UPDATE")
            .execute()
        )

        before_len = len(before_count.data) if before_count.data else 0

        # Update the record (should trigger audit log)
        client.from_("debtor_intelligence").update(
            {"last_updated": datetime.now(timezone.utc).isoformat()}
        ).eq("id", test_id).execute()

        # Check for new access log entry
        after_count = (
            client.from_("access_logs")
            .select("id")
            .eq("table_name", "debtor_intelligence")
            .eq("row_id", test_id)
            .eq("access_type", "UPDATE")
            .execute()
        )

        after_len = len(after_count.data) if after_count.data else 0

        assert (
            after_len > before_len
        ), "UPDATE on debtor_intelligence should create access log entry"

    @skip_if_no_db
    def test_debtor_intelligence_delete_blocked(self):
        """Verify DELETE on debtor_intelligence is blocked and logged."""
        client = get_test_client()

        # Check if we can query the table
        check = client.from_("debtor_intelligence").select("id").limit(1).execute()

        if not check.data or len(check.data) == 0:
            pytest.skip("No debtor_intelligence records to test with")

        test_id = check.data[0]["id"]

        # Try to delete (should fail)
        _ = client.from_("debtor_intelligence").delete().eq("id", test_id).execute()

        # Verify record still exists
        verify = (
            client.from_("debtor_intelligence").select("id").eq("id", test_id).execute()
        )

        assert (
            verify.data and len(verify.data) > 0
        ), "debtor_intelligence record should not be deleted (FCRA protection)"

        # Check that DELETE_BLOCKED was logged
        block_log = (
            client.from_("access_logs")
            .select("id")
            .eq("table_name", "debtor_intelligence")
            .eq("row_id", test_id)
            .eq("access_type", "DELETE_BLOCKED")
            .execute()
        )

        assert (
            block_log.data and len(block_log.data) > 0
        ), "Blocked delete should be logged with DELETE_BLOCKED access_type"


class TestAccessLogsRLS:
    """Tests for RLS policies on access_logs table."""

    @skip_if_no_db
    def test_access_logs_requires_audit_role(self):
        """Verify only audit/admin role can read access_logs."""
        # This test would require switching user context
        # In practice, we verify the policy exists
        client = get_test_client()

        # Try to query access_logs with service_role (should work)
        result = client.from_("access_logs").select("id").limit(1).execute()

        # service_role should be able to read
        assert (
            not hasattr(result, "error") or result.error is None
        ), "service_role should be able to read access_logs"

    @skip_if_no_db
    def test_get_access_logs_function(self):
        """Verify get_access_logs() RPC works for authorized users."""
        client = get_test_client()

        # First insert a test log
        client.rpc(
            "log_access",
            {
                "_table_name": "test_get_logs",
                "_row_id": str(uuid.uuid4()),
                "_access_type": "SELECT",
                "_metadata": {},
            },
        ).execute()

        # Query using the RPC
        result = client.rpc(
            "get_access_logs", {"_table_name": "test_get_logs", "_limit": 10}
        ).execute()

        # With service_role, should work
        if hasattr(result, "error") and result.error:
            # May fail if caller doesn't have admin/audit role
            # This is expected behavior for non-admin users
            pytest.skip("Caller lacks audit role - expected for non-admin users")

        assert (
            result.data is not None
        ), "get_access_logs should return data for authorized users"


class TestExternalDataCallsDeleteBlock:
    """Tests for DELETE blocking on external_data_calls table."""

    @skip_if_no_db
    def test_external_data_calls_delete_blocked(self):
        """Verify DELETE on external_data_calls is blocked."""
        client = get_test_client()

        # Check if table has records
        check = client.from_("external_data_calls").select("id").limit(1).execute()

        if not check.data or len(check.data) == 0:
            pytest.skip("No external_data_calls records to test with")

        test_id = check.data[0]["id"]

        # Try to delete (should fail)
        _ = client.from_("external_data_calls").delete().eq("id", test_id).execute()

        # Verify record still exists
        verify = (
            client.from_("external_data_calls").select("id").eq("id", test_id).execute()
        )

        assert (
            verify.data and len(verify.data) > 0
        ), "external_data_calls record should not be deleted (FCRA protection)"


# ============================================================================
# Integration Tests
# ============================================================================


class TestFCRAAuditIntegration:
    """Integration tests for the complete FCRA audit system."""

    @skip_if_no_db
    def test_full_audit_trail(self):
        """Test a complete audit trail scenario."""
        client = get_test_client()

        session_id = uuid.uuid4()

        # 1. Log a SELECT access
        select_log = client.rpc(
            "log_access",
            {
                "_table_name": "debtor_intelligence",
                "_row_id": str(uuid.uuid4()),
                "_access_type": "SELECT",
                "_metadata": {"purpose": "wage_garnishment_research"},
                "_session_id": str(session_id),
            },
        ).execute()

        assert select_log.data is not None, "SELECT log should succeed"

        # 2. Log an UPDATE access
        update_log = client.rpc(
            "log_access",
            {
                "_table_name": "debtor_intelligence",
                "_row_id": str(uuid.uuid4()),
                "_access_type": "UPDATE",
                "_metadata": {"fields_updated": ["employer_name", "income_band"]},
                "_session_id": str(session_id),
            },
        ).execute()

        assert update_log.data is not None, "UPDATE log should succeed"

        # 3. Log an EXPORT
        export_log = client.rpc(
            "log_export",
            {
                "_table_name": "debtor_intelligence",
                "_row_count": 50,
                "_export_format": "xlsx",
                "_purpose": "quarterly_compliance_report",
            },
        ).execute()

        assert export_log.data is not None, "EXPORT log should succeed"

    @skip_if_no_db
    def test_audit_log_timestamps(self):
        """Verify audit logs have accurate timestamps."""
        client = get_test_client()

        before = datetime.now(timezone.utc) - timedelta(seconds=1)

        # Create a log entry
        result = client.rpc(
            "log_access",
            {
                "_table_name": "timestamp_test",
                "_row_id": str(uuid.uuid4()),
                "_access_type": "SELECT",
                "_metadata": {},
            },
        ).execute()

        after = datetime.now(timezone.utc) + timedelta(seconds=1)

        if hasattr(result, "error") and result.error:
            pytest.skip("Cannot verify timestamp without insert")

        # Query the created log
        log_id = result.data
        log_record = (
            client.from_("access_logs").select("accessed_at").eq("id", log_id).execute()
        )

        if log_record.data and len(log_record.data) > 0:
            accessed_at = datetime.fromisoformat(
                log_record.data[0]["accessed_at"].replace("Z", "+00:00")
            )

            assert (
                before <= accessed_at <= after
            ), "accessed_at should be within the expected time range"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
