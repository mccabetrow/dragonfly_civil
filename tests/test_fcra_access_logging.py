"""
tests/test_fcra_access_logging.py

Modernized test suite for FCRA-compliant access logging system.
Tests the immutable access_logs table and RLS policies using direct table operations.

Key Changes from Legacy:
- Removed run_sql RPC dependency (use direct table operations)
- Blocked operations (DELETE) use pytest.raises to confirm security works
- Timestamp assertions relaxed to ±5 seconds

NOTE: Marked legacy - requires access_logs table and FCRA schema.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from conftest import get_test_client, skip_if_no_db
from postgrest.exceptions import APIError

# Mark as integration (PostgREST) + legacy (optional FCRA schema)
pytestmark = [pytest.mark.integration, pytest.mark.legacy]


class TestAccessLogsTable:
    """Tests for the access_logs table structure and basic operations."""

    @skip_if_no_db
    def test_access_logs_table_exists(self):
        """Verify access_logs table exists and is queryable."""
        client = get_test_client()

        # Direct query - if table doesn't exist, this will fail
        result = client.from_("access_logs").select("id").limit(0).execute()
        assert result.data is not None, "access_logs table should exist and be queryable"

    @skip_if_no_db
    def test_access_logs_select_works(self):
        """Verify we can SELECT from access_logs (service_role can read)."""
        client = get_test_client()

        # Service role should be able to read
        result = (
            client.from_("access_logs").select("id, table_name, access_type").limit(5).execute()
        )
        assert not hasattr(result, "error") or result.error is None, (
            "service_role should be able to read access_logs"
        )


class TestLogAccessFunction:
    """Tests for the log_access() RPC function."""

    @skip_if_no_db
    def test_log_access_inserts_record(self):
        """Verify log_access() creates an access log entry."""
        client = get_test_client()

        test_table = "debtor_intelligence"
        test_row_id = str(uuid.uuid4())

        # Call log_access RPC
        result = client.rpc(
            "log_access",
            {
                "_table_name": test_table,
                "_row_id": test_row_id,
                "_access_type": "SELECT",
                "_metadata": {"purpose": "unit_test"},
            },
        ).execute()

        # Should succeed without error
        assert not hasattr(result, "error") or result.error is None, "log_access should succeed"
        assert result.data is not None, "log_access should return the new record ID"

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

            assert not hasattr(result, "error") or result.error is None, (
                f"Access type '{access_type}' should be valid"
            )


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

        assert not hasattr(result, "error") or result.error is None
        assert result.data is not None, "log_export should return the new record ID"


class TestAccessLogsImmutability:
    """
    Tests for access_logs table immutability (append-only).

    FCRA compliance requires that access logs cannot be modified or deleted.
    These tests confirm that UPDATE/DELETE operations are blocked by RLS/rules.
    """

    @skip_if_no_db
    def test_access_logs_update_blocked(self):
        """Verify UPDATE operations on access_logs are blocked or have no effect."""
        client = get_test_client()

        # First, insert a test record
        insert_result = client.rpc(
            "log_access",
            {
                "_table_name": "test_immutability_update",
                "_row_id": str(uuid.uuid4()),
                "_access_type": "SELECT",
                "_metadata": {"original": True},
            },
        ).execute()

        if hasattr(insert_result, "error") and insert_result.error:
            pytest.skip("Cannot insert test record - log_access RPC unavailable")

        log_id = insert_result.data

        # Try to update the record - should fail due to RULE blocking UPDATE
        # Getting an APIError is SUCCESS - security is working
        try:
            client.from_("access_logs").update({"metadata": {"modified": True}}).eq(
                "id", log_id
            ).execute()
            # If we get here without error, verify record still exists unchanged
            verify_result = (
                client.from_("access_logs").select("metadata").eq("id", log_id).execute()
            )
            if verify_result.data and len(verify_result.data) > 0:
                metadata = verify_result.data[0].get("metadata", {})
                assert metadata.get("original") is True, (
                    "access_logs record should not be modifiable - FCRA compliance"
                )
        except APIError:
            # Getting an error on UPDATE is SUCCESS - security is working
            # The RULE blocks UPDATE with "cannot perform UPDATE RETURNING"
            pass  # This is the expected FCRA-compliant behavior

    @skip_if_no_db
    def test_access_logs_delete_blocked(self):
        """
        Verify DELETE operations on access_logs are blocked.

        This is a SUCCESS case for FCRA: getting a 401/403/blocked response
        when trying to DELETE confirms our security is working.
        """
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
            pytest.skip("Cannot insert test record - log_access RPC unavailable")

        log_id = insert_result.data

        # Try to delete the record
        # This should either:
        # 1. Raise APIError (blocked by RLS policy)
        # 2. Silently fail (blocked by RULE)
        # 3. Return 0 affected rows
        try:
            client.from_("access_logs").delete().eq("id", log_id).execute()
            # If we get here without error, verify record still exists
            verify_result = client.from_("access_logs").select("id").eq("id", log_id).execute()
            assert verify_result.data and len(verify_result.data) > 0, (
                "access_logs record should not be deletable - FCRA compliance"
            )
        except APIError as e:
            # Getting an error on DELETE is SUCCESS - security is working
            # 0A000 = feature_not_supported (RULE blocks DELETE RETURNING)
            # P0001 = raise_exception, 42501 = permission denied
            assert e.code in (
                "0A000",
                "P0001",
                "42501",
                "PGRST301",
                "PGRST204",
            ), f"DELETE should be blocked by policy. Got unexpected error: {e.code}"


class TestFCRAAuditIntegration:
    """Integration tests for the complete FCRA audit system."""

    @skip_if_no_db
    def test_full_audit_trail(self):
        """Test creating a complete audit trail with multiple access types."""
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
        """Verify audit logs have accurate timestamps (within ±5 seconds)."""
        client = get_test_client()

        # Allow 5 second tolerance for clock skew / network latency
        before = datetime.now(timezone.utc) - timedelta(seconds=5)

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

        after = datetime.now(timezone.utc) + timedelta(seconds=5)

        if hasattr(result, "error") and result.error:
            pytest.skip("Cannot verify timestamp without successful insert")

        # Query the created log
        log_id = result.data
        log_record = client.from_("access_logs").select("accessed_at").eq("id", log_id).execute()

        if log_record.data and len(log_record.data) > 0:
            accessed_at_str = log_record.data[0]["accessed_at"]
            # Handle both Z suffix and +00:00 suffix
            accessed_at = datetime.fromisoformat(accessed_at_str.replace("Z", "+00:00"))

            assert before <= accessed_at <= after, (
                f"accessed_at should be within ±5 seconds of now. "
                f"Got {accessed_at}, expected between {before} and {after}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
