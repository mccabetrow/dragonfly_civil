# tests/test_ingest_traceability.py
"""
Ingest Traceability Tests - North Star Architecture

These tests verify the "Timeline" - full traceability of all ingest operations.

Test Scenarios:
1. Upload a file -> verify audit log entries
2. Upload same file again -> verify duplicate detection
3. Verify correlation_id links all operations
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta

import pytest

from backend.ingest.contract import (
    IngestContract,
    IngestEvent,
    IngestLogger,
    IngestStage,
    compute_dedup_key,
    compute_file_hash,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def supabase_client():
    """Get Supabase client with service_role key."""
    from src.supabase_client import create_supabase_client

    return create_supabase_client()


@pytest.fixture
def test_csv_content() -> bytes:
    """Generate test CSV content."""
    unique_id = uuid.uuid4().hex[:8]
    csv_content = f"""case_number,defendant_name,judgment_amount,plaintiff_name
TEST-{unique_id}-001,John Doe,1500.00,Acme Corp
TEST-{unique_id}-002,Jane Smith,2500.50,Widget Inc
TEST-{unique_id}-003,Bob Johnson,3750.00,Test LLC
"""
    return csv_content.encode("utf-8")


@pytest.fixture
def test_filename() -> str:
    """Generate unique test filename."""
    return f"test_ingest_{uuid.uuid4().hex[:8]}.csv"


# =============================================================================
# Contract Tests
# =============================================================================


class TestIngestContract:
    """Test the IngestContract class."""

    def test_required_columns(self):
        """Verify required columns are defined."""
        assert "case_number" in IngestContract.REQUIRED_COLS
        assert "defendant_name" in IngestContract.REQUIRED_COLS
        assert "judgment_amount" in IngestContract.REQUIRED_COLS

    def test_validate_row_valid(self):
        """Test validation of a valid row."""
        row = {
            "case_number": "TEST-001",
            "defendant_name": "John Doe",
            "judgment_amount": "1500.00",
        }
        errors = IngestContract.validate_row(row)
        assert len(errors) == 0

    def test_validate_row_missing_column(self):
        """Test validation catches missing required columns."""
        row = {
            "case_number": "TEST-001",
            # missing defendant_name
            "judgment_amount": "1500.00",
        }
        errors = IngestContract.validate_row(row)
        assert len(errors) == 1
        assert "defendant_name" in errors[0]

    def test_validate_row_empty_value(self):
        """Test validation catches empty values."""
        row = {
            "case_number": "TEST-001",
            "defendant_name": "",  # empty
            "judgment_amount": "1500.00",
        }
        errors = IngestContract.validate_row(row)
        assert len(errors) == 1
        assert "Empty" in errors[0]

    def test_validate_row_negative_amount(self):
        """Test validation catches negative amounts."""
        row = {
            "case_number": "TEST-001",
            "defendant_name": "John Doe",
            "judgment_amount": "-100.00",
        }
        errors = IngestContract.validate_row(row)
        assert len(errors) == 1
        assert "negative" in errors[0].lower()

    def test_compute_file_hash_deterministic(self, test_csv_content):
        """Test that file hash is deterministic."""
        hash1 = compute_file_hash(test_csv_content)
        hash2 = compute_file_hash(test_csv_content)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

    def test_compute_file_hash_different_content(self):
        """Test that different content produces different hashes."""
        hash1 = compute_file_hash(b"content1")
        hash2 = compute_file_hash(b"content2")
        assert hash1 != hash2

    def test_compute_dedup_key_format(self):
        """Test dedup_key format."""
        batch_id = "abc-123"
        row_index = 5
        key = compute_dedup_key(batch_id, row_index)
        assert key == "validation-abc-123-5"

    def test_compute_dedup_key_with_stage(self):
        """Test dedup_key with custom stage."""
        key = compute_dedup_key("batch-1", 0, "enrichment")
        assert key == "enrichment-batch-1-0"


# =============================================================================
# Logger Tests
# =============================================================================


class TestIngestLogger:
    """Test the IngestLogger class."""

    def test_logger_creates_correlation_id(self, supabase_client):
        """Test that logger creates a correlation_id."""
        logger = IngestLogger(supabase_client)
        assert logger.correlation_id is not None
        assert len(logger.correlation_id) == 36  # UUID format

    def test_logger_uses_provided_correlation_id(self, supabase_client):
        """Test that logger uses provided correlation_id."""
        custom_id = str(uuid.uuid4())
        logger = IngestLogger(supabase_client, correlation_id=custom_id)
        assert logger.correlation_id == custom_id

    @pytest.mark.integration
    def test_log_event(self, supabase_client):
        """Test logging an event to the database."""
        logger = IngestLogger(supabase_client)

        # Log an event
        result = logger.log(
            batch_id=None,
            stage=IngestStage.UPLOAD,
            event=IngestEvent.STARTED,
            metadata={"test": True},
        )

        assert result is not None
        assert result.get("stage") == "upload"
        assert result.get("event") == "started"

        # Verify it's in the database
        records = (
            supabase_client.table("ingest_event_log")
            .select("*")
            .eq("correlation_id", logger.correlation_id)
            .execute()
        )
        assert len(records.data) >= 1


# =============================================================================
# Traceability Integration Tests
# =============================================================================


class TestIngestTraceability:
    """
    Integration tests for full ingest traceability.

    These tests verify the "Timeline" - every action is logged and traceable.
    """

    @pytest.mark.integration
    def test_upload_creates_audit_trail(self, supabase_client, test_csv_content, test_filename):
        """
        Test that uploading a file creates a complete audit trail.

        Expected audit log entries:
        1. upload/started
        2. upload/completed (batch created)
        3. parse/rows_inserted
        4. enqueue/jobs_created
        """
        from backend.api.services.ingest_service import IngestService

        # Process the file
        service = IngestService(supabase_client)
        result = service.process_file_sync(test_csv_content, test_filename)

        assert result.success
        assert result.batch_id is not None
        assert not result.is_duplicate

        # Verify audit trail
        audit_records = (
            supabase_client.table("ingest_event_log")
            .select("*")
            .eq("correlation_id", result.correlation_id)
            .order("created_at")
            .execute()
        )

        events = [(r["stage"], r["event"]) for r in audit_records.data]

        # Verify key events are present
        assert ("upload", "started") in events
        assert ("upload", "completed") in events or ("upload", "duplicate") in events

        # Cleanup
        _cleanup_test_batch(supabase_client, result.batch_id)

    @pytest.mark.integration
    def test_duplicate_upload_detected(self, supabase_client, test_csv_content, test_filename):
        """
        Test the "Double Tap" - uploading the same file twice.

        Expected:
        1. First upload creates batch
        2. Second upload detects duplicate
        3. Same batch_id returned
        4. No new rows created
        5. Audit log shows "duplicate"
        """
        from backend.api.services.ingest_service import IngestService

        service = IngestService(supabase_client)

        # First upload
        result1 = service.process_file_sync(test_csv_content, test_filename)
        assert result1.success
        assert not result1.is_duplicate
        batch_id = result1.batch_id
        rows_created = result1.rows_inserted

        # Second upload (same content)
        result2 = service.process_file_sync(test_csv_content, test_filename + "_copy")

        # Verify idempotency
        assert result2.batch_id == batch_id, "Same file hash should return same batch_id"
        assert result2.is_duplicate, "Second upload should be detected as duplicate"
        assert result2.rows_inserted == 0, "No new rows should be created"
        assert result2.jobs_created == 0, "No new jobs should be created"

        # Verify audit log shows duplicate
        audit_records = (
            supabase_client.table("ingest_event_log")
            .select("*")
            .eq("correlation_id", result2.correlation_id)
            .execute()
        )

        events = [(r["stage"], r["event"]) for r in audit_records.data]
        assert ("upload", "duplicate") in events

        # Cleanup
        _cleanup_test_batch(supabase_client, batch_id)

    @pytest.mark.integration
    def test_correlation_id_links_operations(
        self, supabase_client, test_csv_content, test_filename
    ):
        """
        Test that correlation_id links all operations in a single request.
        """
        from backend.api.services.ingest_service import IngestService

        service = IngestService(supabase_client)
        result = service.process_file_sync(test_csv_content, test_filename)

        # All audit log entries should have the same correlation_id
        audit_records = (
            supabase_client.table("ingest_event_log")
            .select("*")
            .eq("correlation_id", result.correlation_id)
            .execute()
        )

        assert len(audit_records.data) >= 2, "Should have multiple audit entries"

        correlation_ids = {r["correlation_id"] for r in audit_records.data}
        assert len(correlation_ids) == 1, "All entries should have same correlation_id"

        # Cleanup
        _cleanup_test_batch(supabase_client, result.batch_id)

    @pytest.mark.integration
    def test_timeline_view(self, supabase_client, test_csv_content, test_filename):
        """
        Test the ops.v_ingest_timeline view.
        """
        from backend.api.services.ingest_service import IngestService

        service = IngestService(supabase_client)
        result = service.process_file_sync(test_csv_content, test_filename)

        # Query the timeline view
        timeline = (
            supabase_client.table("v_ingest_timeline")
            .select("*")
            .eq("batch_id", result.batch_id)
            .order("step_number")
            .execute()
        )

        assert len(timeline.data) >= 1, "Timeline should have entries"

        # Verify step_number ordering
        if len(timeline.data) > 1:
            step_numbers = [r["step_number"] for r in timeline.data]
            assert step_numbers == sorted(step_numbers), "Steps should be ordered"

        # Cleanup
        _cleanup_test_batch(supabase_client, result.batch_id)


# =============================================================================
# Helper Functions
# =============================================================================


def _cleanup_test_batch(client, batch_id: str):
    """Clean up test data."""
    if not batch_id:
        return

    try:
        # Delete jobs
        client.table("job_queue").delete().eq("payload->>batch_id", batch_id).execute()

        # Delete raw rows
        client.table("simplicity_raw_rows").delete().eq("batch_id", batch_id).execute()

        # Delete batch
        client.table("simplicity_batches").delete().eq("id", batch_id).execute()

        # Delete audit logs
        client.table("ingest_event_log").delete().eq("batch_id", batch_id).execute()
    except Exception:
        pass  # Best effort cleanup
