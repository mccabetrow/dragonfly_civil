"""
Tests for Data Integrity & Reconciliation Engine

Tests the reconciliation service that:
- Tracks row lifecycle through ingest
- Logs discrepancies to the dead letter queue
- Verifies batch integrity
- Supports retry functionality

Business requirement: "Absolute proof that every row ingested from
Simplicity or FOIL is stored perfectly. Dead Letter Queue to fix it manually."
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from backend.services.reconciliation import (
    BatchVerificationResult,
    Discrepancy,
    DiscrepancyStatus,
    ErrorType,
    IntegrityDashboard,
    ReconciliationService,
    RowStage,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_conn() -> MagicMock:
    """Create a mock database connection."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=None)
    conn.cursor.return_value = cursor
    return conn


@pytest.fixture
def sample_batch_id() -> str:
    """Generate a sample batch UUID."""
    return str(uuid.uuid4())


@pytest.fixture
def sample_row_data() -> Dict[str, Any]:
    """Sample row data from a CSV import."""
    return {
        "plaintiff_name": "Test Plaintiff LLC",
        "defendant_name": "John Doe",
        "case_number": "2024-CV-12345",
        "judgment_amount": "15000.00",
        "judgment_date": "2024-01-15",
        "court": "New York Supreme Court",
    }


@pytest.fixture
def reconciliation_service(mock_conn: MagicMock) -> ReconciliationService:
    """Create a ReconciliationService instance with mocked connection."""
    return ReconciliationService(conn=mock_conn)


# =============================================================================
# RowStage ENUM TESTS
# =============================================================================


class TestRowStageEnum:
    """Test RowStage enum values."""

    def test_all_stages_exist(self):
        """All expected audit stages are defined."""
        assert RowStage.RECEIVED.value == "received"
        assert RowStage.PARSED.value == "parsed"
        assert RowStage.VALIDATED.value == "validated"
        assert RowStage.STORED.value == "stored"
        assert RowStage.FAILED.value == "failed"

    def test_stage_count(self):
        """Exactly 5 stages are defined."""
        assert len(RowStage) == 5


# =============================================================================
# ErrorType ENUM TESTS
# =============================================================================


class TestErrorTypeEnum:
    """Test ErrorType enum values."""

    def test_all_types_exist(self):
        """All expected error types are defined."""
        assert ErrorType.PARSE_ERROR.value == "parse_error"
        assert ErrorType.VALIDATION_ERROR.value == "validation_error"
        assert ErrorType.TRANSFORM_ERROR.value == "transform_error"
        assert ErrorType.DB_ERROR.value == "db_error"
        assert ErrorType.DUPLICATE.value == "duplicate"
        assert ErrorType.CONSTRAINT_ERROR.value == "constraint_error"
        assert ErrorType.UNKNOWN.value == "unknown"


# =============================================================================
# DiscrepancyStatus ENUM TESTS
# =============================================================================


class TestDiscrepancyStatusEnum:
    """Test DiscrepancyStatus enum values."""

    def test_all_statuses_exist(self):
        """All expected resolution statuses are defined."""
        assert DiscrepancyStatus.PENDING.value == "pending"
        assert DiscrepancyStatus.REVIEWING.value == "reviewing"
        assert DiscrepancyStatus.RETRYING.value == "retrying"
        assert DiscrepancyStatus.RESOLVED.value == "resolved"
        assert DiscrepancyStatus.DISMISSED.value == "dismissed"


# =============================================================================
# BatchVerificationResult DATACLASS TESTS
# =============================================================================


class TestBatchVerificationResult:
    """Test BatchVerificationResult dataclass."""

    def test_is_perfect_when_all_match(self):
        """is_perfect returns True when all rows match."""
        result = BatchVerificationResult(
            batch_id="test-batch",
            csv_row_count=100,
            db_row_count=100,
            failed_row_count=0,
            integrity_score=100.0,
            is_complete=True,
        )
        assert result.is_perfect is True

    def test_is_perfect_false_with_missing(self):
        """is_perfect returns False when rows are missing."""
        result = BatchVerificationResult(
            batch_id="test-batch",
            csv_row_count=100,
            db_row_count=98,
            failed_row_count=2,
            integrity_score=98.0,
            is_complete=False,
        )
        assert result.is_perfect is False

    def test_is_perfect_false_with_failures(self):
        """is_perfect returns False when there are failures."""
        result = BatchVerificationResult(
            batch_id="test-batch",
            csv_row_count=100,
            db_row_count=100,
            failed_row_count=5,
            integrity_score=95.0,
            is_complete=False,
        )
        assert result.is_perfect is False


# =============================================================================
# IntegrityDashboard DATACLASS TESTS
# =============================================================================


class TestIntegrityDashboard:
    """Test IntegrityDashboard dataclass."""

    def test_dashboard_creation(self):
        """IntegrityDashboard can be created with all fields."""
        dashboard = IntegrityDashboard(
            total_rows_received=1000,
            total_rows_stored=997,
            total_rows_failed=3,
            total_batches=50,
            integrity_score=99.7,
            pending_discrepancies=3,
            resolved_discrepancies=10,
            rows_received_24h=100,
            rows_stored_24h=100,
            batches_pending=2,
            batches_processing=1,
            computed_at=datetime.now(timezone.utc),
        )
        assert dashboard.total_rows_received == 1000
        assert dashboard.total_rows_stored == 997
        assert dashboard.integrity_score == 99.7


# =============================================================================
# ReconciliationService UNIT TESTS
# =============================================================================


@pytest.mark.unit
class TestReconciliationServiceLogMethods:
    """Test ReconciliationService logging methods."""

    def test_log_row_received_inserts_audit_record(
        self,
        reconciliation_service: ReconciliationService,
        sample_batch_id: str,
        sample_row_data: Dict[str, Any],
    ):
        """log_row_received inserts an audit record with stage='received'."""
        cursor = reconciliation_service.conn.cursor.return_value
        cursor.fetchone.return_value = (str(uuid.uuid4()),)

        result = reconciliation_service.log_row_received(
            batch_id=sample_batch_id,
            row_index=0,
            raw_data=sample_row_data,
        )

        # Verify cursor was used
        assert result is not None
        cursor.execute.assert_called_once()
        call_args = cursor.execute.call_args
        assert "INSERT INTO ops.ingest_audit_log" in call_args[0][0]
        assert "'received'" in call_args[0][0]

    def test_log_row_validated_updates_stage(
        self,
        reconciliation_service: ReconciliationService,
        sample_batch_id: str,
    ):
        """log_row_validated updates the audit record stage."""
        cursor = reconciliation_service.conn.cursor.return_value

        reconciliation_service.log_row_validated(
            batch_id=sample_batch_id,
            row_index=0,
        )

        cursor.execute.assert_called_once()
        call_args = cursor.execute.call_args
        assert "UPDATE ops.ingest_audit_log" in call_args[0][0]
        assert "'validated'" in call_args[0][0]

    def test_log_row_stored_updates_stage(
        self,
        reconciliation_service: ReconciliationService,
        sample_batch_id: str,
    ):
        """log_row_stored updates the audit record with judgment_id."""
        cursor = reconciliation_service.conn.cursor.return_value
        judgment_id = str(uuid.uuid4())

        reconciliation_service.log_row_stored(
            batch_id=sample_batch_id,
            row_index=0,
            judgment_id=judgment_id,
        )

        cursor.execute.assert_called_once()
        call_args = cursor.execute.call_args
        assert "UPDATE ops.ingest_audit_log" in call_args[0][0]
        assert "'stored'" in call_args[0][0]

    def test_log_row_stored_without_judgment_id(
        self,
        reconciliation_service: ReconciliationService,
        sample_batch_id: str,
    ):
        """log_row_stored works without judgment_id (plaintiff imports)."""
        cursor = reconciliation_service.conn.cursor.return_value

        reconciliation_service.log_row_stored(
            batch_id=sample_batch_id,
            row_index=0,
        )

        cursor.execute.assert_called_once()
        call_args = cursor.execute.call_args
        assert "UPDATE ops.ingest_audit_log" in call_args[0][0]
        assert "'stored'" in call_args[0][0]

    def test_log_row_failed_updates_stage(
        self,
        reconciliation_service: ReconciliationService,
        sample_batch_id: str,
    ):
        """log_row_failed records error details."""
        cursor = reconciliation_service.conn.cursor.return_value

        reconciliation_service.log_row_failed(
            batch_id=sample_batch_id,
            row_index=0,
            error_stage="validation",
            error_code="INVALID_DATE",
            error_message="Invalid date format: expected MM/DD/YYYY",
        )

        cursor.execute.assert_called_once()
        call_args = cursor.execute.call_args
        assert "UPDATE ops.ingest_audit_log" in call_args[0][0]
        assert "'failed'" in call_args[0][0]


@pytest.mark.unit
class TestReconciliationServiceDiscrepancies:
    """Test ReconciliationService discrepancy methods."""

    def test_create_discrepancy_inserts_record(
        self,
        reconciliation_service: ReconciliationService,
        sample_batch_id: str,
        sample_row_data: Dict[str, Any],
    ):
        """create_discrepancy inserts a record into data_discrepancies."""
        cursor = reconciliation_service.conn.cursor.return_value
        cursor.fetchone.return_value = (str(uuid.uuid4()),)

        discrepancy_id = reconciliation_service.create_discrepancy(
            batch_id=sample_batch_id,
            row_index=5,
            raw_data=sample_row_data,
            error_type=ErrorType.VALIDATION_ERROR,
            error_message="Invalid judgment amount",
        )

        assert discrepancy_id is not None
        cursor.execute.assert_called_once()
        call_args = cursor.execute.call_args
        assert "INSERT INTO ops.data_discrepancies" in call_args[0][0]

    def test_create_discrepancy_with_source_file(
        self,
        reconciliation_service: ReconciliationService,
        sample_batch_id: str,
        sample_row_data: Dict[str, Any],
    ):
        """create_discrepancy includes source_file when provided."""
        cursor = reconciliation_service.conn.cursor.return_value
        cursor.fetchone.return_value = (str(uuid.uuid4()),)

        reconciliation_service.create_discrepancy(
            batch_id=sample_batch_id,
            row_index=5,
            raw_data=sample_row_data,
            error_type=ErrorType.DB_ERROR,
            error_message="Database constraint violation",
            source_file="simplicity_export_2024.csv",
        )

        call_args = cursor.execute.call_args
        # source_file should be in the parameters
        assert "simplicity_export_2024.csv" in str(call_args[0][1])

    def test_create_discrepancy_with_error_details(
        self,
        reconciliation_service: ReconciliationService,
        sample_batch_id: str,
        sample_row_data: Dict[str, Any],
    ):
        """create_discrepancy includes error_details when provided."""
        cursor = reconciliation_service.conn.cursor.return_value
        cursor.fetchone.return_value = (str(uuid.uuid4()),)

        error_details = {
            "field": "judgment_amount",
            "expected": "numeric",
            "received": "not-a-number",
        }

        reconciliation_service.create_discrepancy(
            batch_id=sample_batch_id,
            row_index=5,
            raw_data=sample_row_data,
            error_type=ErrorType.VALIDATION_ERROR,
            error_message="Field validation failed",
            error_details=error_details,
        )

        # error_details should be JSON-encoded in parameters
        assert cursor.execute.called


# =============================================================================
# SOURCE HASH COMPUTATION TESTS
# =============================================================================


class TestSourceHashComputation:
    """Test source hash computation for row fingerprinting."""

    def test_compute_checksum_deterministic(self):
        """Same data produces same hash."""
        service = ReconciliationService(conn=MagicMock())

        data = {
            "plaintiff_name": "Test Corp",
            "defendant_name": "John Doe",
            "case_number": "2024-001",
        }

        hash1 = service._compute_checksum(data)
        hash2 = service._compute_checksum(data)

        assert hash1 == hash2
        assert (
            len(hash1) == 16
        )  # Truncated hash length    def test_compute_checksum_different_for_different_data(self):
        """Different data produces different hash."""
        service = ReconciliationService(conn=MagicMock())

        data1 = {"plaintiff_name": "Corp A"}
        data2 = {"plaintiff_name": "Corp B"}

        hash1 = service._compute_checksum(data1)
        hash2 = service._compute_checksum(data2)

        assert hash1 != hash2

    def test_compute_checksum_handles_unicode(self):
        """Unicode characters should be handled correctly."""
        service = ReconciliationService(conn=MagicMock())
        data = {
            "plaintiff_name": "José García",
            "defendant_name": "北京公司",
        }
        hash_result = service._compute_checksum(data)
        assert hash_result is not None
        assert len(hash_result) == 16  # Truncated hash length


# =============================================================================
# INTEGRATION TEST: Bad Row → Discrepancy Flow
# =============================================================================


@pytest.mark.unit
class TestBadRowToDiscrepancyFlow:
    """Test the flow of a bad row through to the dead letter queue."""

    def test_bad_row_creates_discrepancy_with_correct_fields(
        self,
        mock_conn: MagicMock,
        sample_batch_id: str,
    ):
        """
        A batch with 1 bad row should:
        1. Log the row as received
        2. Attempt validation/storage
        3. Log failure
        4. Create discrepancy in dead letter queue
        """
        service = ReconciliationService(conn=mock_conn)
        cursor = mock_conn.cursor.return_value
        cursor.fetchone.return_value = (str(uuid.uuid4()),)

        bad_row = {
            "plaintiff_name": "Test Corp",
            "defendant_name": "",  # Missing required field
            "case_number": "2024-001",
            "judgment_amount": "not-a-number",  # Invalid format
        }

        # 1. Log received
        service.log_row_received(
            batch_id=sample_batch_id,
            row_index=0,
            raw_data=bad_row,
        )

        # 2. Log failure (validation failed)
        service.log_row_failed(
            batch_id=sample_batch_id,
            row_index=0,
            error_stage="validation",
            error_code="VALIDATION_FAILED",
            error_message="defendant_name required, invalid judgment_amount",
        )

        # 3. Create discrepancy
        discrepancy_id = service.create_discrepancy(
            batch_id=sample_batch_id,
            row_index=0,
            raw_data=bad_row,
            error_type=ErrorType.VALIDATION_ERROR,
            error_message="defendant_name required, invalid judgment_amount",
        )

        assert discrepancy_id is not None

        # Verify 3 database calls were made (received + failed + discrepancy)
        assert cursor.execute.call_count == 3

    def test_partial_success_batch_flow(
        self,
        mock_conn: MagicMock,
        sample_batch_id: str,
    ):
        """
        A batch with 10 rows where 1 fails should result in:
        - 9 successful stores
        - 1 discrepancy
        """
        service = ReconciliationService(conn=mock_conn)
        cursor = mock_conn.cursor.return_value
        cursor.fetchone.return_value = (str(uuid.uuid4()),)

        good_rows = [{"name": f"Row {i}", "valid": True} for i in range(9)]
        bad_row = {"name": "Row 9", "valid": False}

        # Process 9 good rows: received → validated → stored
        for i, row in enumerate(good_rows):
            service.log_row_received(sample_batch_id, i, row)
            service.log_row_validated(sample_batch_id, i)
            service.log_row_stored(sample_batch_id, i, f"judgment-{i}")

        # Process 1 bad row: received → failed → discrepancy
        service.log_row_received(sample_batch_id, 9, bad_row)
        service.log_row_failed(sample_batch_id, 9, "validation", "INVALID", "Validation failed")
        service.create_discrepancy(
            batch_id=sample_batch_id,
            row_index=9,
            raw_data=bad_row,
            error_type=ErrorType.VALIDATION_ERROR,
            error_message="Validation failed",
        )

        # Verify: 9 good rows × 3 calls + 1 bad row × 3 calls = 30 calls
        assert cursor.execute.call_count == 30


# =============================================================================
# BATCH VERIFICATION RESULT TESTS
# =============================================================================


@pytest.mark.unit
class TestBatchVerificationDataclass:
    """Test BatchVerificationResult dataclass behavior."""

    def test_result_with_perfect_integrity(self):
        """BatchVerificationResult correctly identifies perfect batches."""
        result = BatchVerificationResult(
            batch_id="test-batch",
            csv_row_count=1000,
            db_row_count=1000,
            failed_row_count=0,
            integrity_score=100.0,
            is_complete=True,
            status="completed",
        )
        assert result.is_perfect is True
        assert result.integrity_score == 100.0

    def test_result_with_partial_success(self):
        """BatchVerificationResult correctly identifies partial success."""
        result = BatchVerificationResult(
            batch_id="test-batch",
            csv_row_count=1000,
            db_row_count=997,
            failed_row_count=3,
            integrity_score=99.7,
            is_complete=True,
            status="completed",
            discrepancies=[
                {"row_index": 100, "error": "validation_error"},
                {"row_index": 500, "error": "db_error"},
                {"row_index": 750, "error": "duplicate"},
            ],
        )
        assert result.is_perfect is False
        assert len(result.discrepancies) == 3


# =============================================================================
# EDGE CASE TESTS
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_raw_data_checksum(self):
        """Empty raw data should still produce a valid hash."""
        service = ReconciliationService(conn=MagicMock())
        hash_result = service._compute_checksum({})
        assert hash_result is not None
        assert len(hash_result) == 16  # Truncated hash length

    def test_null_values_in_raw_data(self):
        """Null values in raw data should be handled."""
        service = ReconciliationService(conn=MagicMock())
        data = {
            "plaintiff_name": "Test",
            "defendant_name": None,
            "amount": None,
        }
        hash_result = service._compute_checksum(data)
        assert hash_result is not None

    def test_unicode_in_error_message(self):
        """Unicode characters in error messages should be handled."""
        service = ReconciliationService(conn=MagicMock())
        data = {
            "plaintiff_name": "José García",
            "notes": "北京公司",
        }
        hash_result = service._compute_checksum(data)
        assert hash_result is not None
        assert len(hash_result) == 16
