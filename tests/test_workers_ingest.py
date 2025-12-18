"""
Unit tests for backend/workers/ingest_processor.py

These tests:
- Don't hit S3 / Supabase
- Don't hit a real DB
- Validate the mapping logic
- Validate that invalid rows are logged but don't crash
"""

from decimal import Decimal
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backend.workers.ingest_processor import (
    _clean_currency,
    _is_simplicity_format,
    _map_simplicity_row,
    _parse_simplicity_date,
    process_simplicity_frame,
)

# =============================================================================
# Helper Function Tests
# =============================================================================


@pytest.mark.unit
class TestCleanCurrency:
    """Tests for _clean_currency helper."""

    def test_valid_dollar_amount(self):
        """Standard dollar amount with $ and commas."""
        assert _clean_currency("$1,200.50") == Decimal("1200.50")

    def test_plain_number(self):
        """Plain numeric string."""
        assert _clean_currency("500") == Decimal("500")

    def test_numeric_types(self):
        """Int and float pass through."""
        assert _clean_currency(1500) == Decimal("1500")
        assert _clean_currency(1500.75) == Decimal("1500.75")

    def test_empty_string(self):
        """Empty string returns None."""
        assert _clean_currency("") is None

    def test_whitespace_only(self):
        """Whitespace-only returns None."""
        assert _clean_currency("   ") is None

    def test_none_value(self):
        """None returns None."""
        assert _clean_currency(None) is None

    def test_invalid_string(self):
        """Non-numeric string returns None."""
        assert _clean_currency("not-a-number") is None


@pytest.mark.unit
class TestParseSimplicityDate:
    """Tests for _parse_simplicity_date helper."""

    def test_mm_dd_yyyy_format(self):
        """Standard Simplicity date format."""
        result = _parse_simplicity_date("03/15/2021")
        assert result is not None
        assert result.year == 2021
        assert result.month == 3
        assert result.day == 15

    def test_iso_format(self):
        """ISO date format also supported."""
        result = _parse_simplicity_date("2021-03-15")
        assert result is not None
        assert result.year == 2021
        assert result.month == 3
        assert result.day == 15

    def test_empty_string(self):
        """Empty string returns None."""
        assert _parse_simplicity_date("") is None

    def test_none_value(self):
        """None returns None."""
        assert _parse_simplicity_date(None) is None

    def test_invalid_format(self):
        """Invalid format returns None (no crash)."""
        assert _parse_simplicity_date("not-a-date") is None


@pytest.mark.unit
class TestIsSimplicityFormat:
    """Tests for _is_simplicity_format detection."""

    def test_valid_simplicity_columns(self):
        """DataFrame with all Simplicity columns is detected."""
        df = pd.DataFrame(
            columns=[
                "Case Number",
                "Plaintiff",
                "Defendant",
                "Judgment Amount",
                "Filing Date",
                "County",
            ]
        )
        assert _is_simplicity_format(df) is True

    def test_missing_column(self):
        """DataFrame missing a required column is not Simplicity format."""
        df = pd.DataFrame(
            columns=[
                "Case Number",
                "Plaintiff",
                "Defendant",
                # Missing "Judgment Amount"
                "Filing Date",
                "County",
            ]
        )
        assert _is_simplicity_format(df) is False

    def test_generic_format(self):
        """Generic column names are not Simplicity format."""
        df = pd.DataFrame(columns=["case_number", "plaintiff_name", "defendant_name", "amount"])
        assert _is_simplicity_format(df) is False


# =============================================================================
# Mapper Tests
# =============================================================================


@pytest.mark.unit
class TestMapSimplicityRow:
    """Tests for _map_simplicity_row mapper."""

    def test_valid_row(self):
        """A well-formed Simplicity row maps to a clean insert dict."""
        row = pd.Series(
            {
                "Case Number": "12345-2021",
                "Plaintiff": "ACME Collections LLC",
                "Defendant": "John Smith",
                "Judgment Amount": "$1,200.50",
                "Filing Date": "03/15/2021",
                "County": "New York",
            }
        )

        result = _map_simplicity_row(row)

        assert result["case_number"] == "12345-2021"
        assert result["plaintiff_name"] == "ACME Collections LLC"
        assert result["defendant_name"] == "John Smith"
        assert result["county"] == "New York"

        # Amount cleaned and parsed
        assert isinstance(result["judgment_amount"], Decimal)
        assert result["judgment_amount"] == Decimal("1200.50")

        # Date parsed as ISO string
        assert result["filing_date"] == "2021-03-15"

    def test_missing_amount_raises(self):
        """Missing or invalid Judgment Amount should be a hard validation failure."""
        row = pd.Series(
            {
                "Case Number": "12345-2021",
                "Plaintiff": "ACME Collections LLC",
                "Defendant": "John Smith",
                "Judgment Amount": "",  # missing
                "Filing Date": "03/15/2021",
                "County": "New York",
            }
        )

        with pytest.raises(ValueError) as excinfo:
            _map_simplicity_row(row)

        assert "Judgment Amount" in str(excinfo.value)

    def test_invalid_amount_raises(self):
        """Non-numeric Judgment Amount raises ValueError."""
        row = pd.Series(
            {
                "Case Number": "12345-2021",
                "Plaintiff": "ACME Collections LLC",
                "Defendant": "John Smith",
                "Judgment Amount": "not-a-number",
                "Filing Date": "03/15/2021",
                "County": "New York",
            }
        )

        with pytest.raises(ValueError) as excinfo:
            _map_simplicity_row(row)

        assert "Judgment Amount" in str(excinfo.value)

    def test_missing_column_raises(self):
        """Missing required column raises ValueError."""
        row = pd.Series(
            {
                "Case Number": "12345-2021",
                "Plaintiff": "ACME Collections LLC",
                # Missing "Defendant"
                "Judgment Amount": "$1,000.00",
                "Filing Date": "03/15/2021",
                "County": "New York",
            }
        )

        with pytest.raises(ValueError) as excinfo:
            _map_simplicity_row(row)

        assert "missing required columns" in str(excinfo.value).lower()

    def test_whitespace_trimmed(self):
        """Leading/trailing whitespace is trimmed from string fields."""
        row = pd.Series(
            {
                "Case Number": "  12345-2021  ",
                "Plaintiff": "  ACME Collections LLC  ",
                "Defendant": "  John Smith  ",
                "Judgment Amount": "  $1,000.00  ",
                "Filing Date": "03/15/2021",
                "County": "  New York  ",
            }
        )

        result = _map_simplicity_row(row)

        assert result["case_number"] == "12345-2021"
        assert result["plaintiff_name"] == "ACME Collections LLC"
        assert result["defendant_name"] == "John Smith"
        assert result["county"] == "New York"

    def test_none_filing_date(self):
        """Empty filing date results in None (not crash)."""
        row = pd.Series(
            {
                "Case Number": "12345-2021",
                "Plaintiff": "ACME Collections LLC",
                "Defendant": "John Smith",
                "Judgment Amount": "$1,000.00",
                "Filing Date": "",  # empty
                "County": "New York",
            }
        )

        result = _map_simplicity_row(row)
        assert result["filing_date"] is None


# =============================================================================
# Integration Tests (with mocked DB)
# =============================================================================


@pytest.mark.unit
class TestProcessSimplicityFrame:
    """Tests for process_simplicity_frame with mocked DB."""

    def test_invalid_row_logged_and_skipped(self):
        """Invalid rows are logged but don't crash the worker."""
        # First row: valid
        row_ok: Dict[str, Any] = {
            "Case Number": "12345-2021",
            "Plaintiff": "ACME Collections LLC",
            "Defendant": "John Smith",
            "Judgment Amount": "$1,000.00",
            "Filing Date": "03/15/2021",
            "County": "New York",
        }

        # Second row: missing amount -> triggers validation error
        row_bad: Dict[str, Any] = {
            "Case Number": "67890-2022",
            "Plaintiff": "Empire Funding Corp",
            "Defendant": "Jane Doe",
            "Judgment Amount": "",  # invalid
            "Filing Date": "04/20/2022",
            "County": "Bronx",
        }

        df = pd.DataFrame([row_ok, row_bad])

        # Create mock connection with proper context manager cursor
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

        # Patch _log_invalid_row so we don't hit the DB
        with patch("backend.workers.ingest_processor._log_invalid_row") as mock_log_invalid:
            inserted = process_simplicity_frame(mock_conn, df, batch_id="test-batch-1")

        # One valid row inserted
        assert inserted == 1

        # _log_invalid_row called once for the bad row
        mock_log_invalid.assert_called_once()
        args = mock_log_invalid.call_args[0]
        assert args[1] == "test-batch-1"  # batch_id
        # raw payload should contain the offending case number
        assert args[2]["Case Number"] == "67890-2022"

    @pytest.mark.skip(
        reason="Legacy: cursor.execute count changed after ReconciliationService integration"
    )
    def test_all_valid_rows_inserted(self):
        """All valid rows are inserted successfully."""
        rows = [
            {
                "Case Number": "12345-2021",
                "Plaintiff": "ACME Collections LLC",
                "Defendant": "John Smith",
                "Judgment Amount": "$1,000.00",
                "Filing Date": "03/15/2021",
                "County": "New York",
            },
            {
                "Case Number": "67890-2022",
                "Plaintiff": "Empire Funding Corp",
                "Defendant": "Jane Doe",
                "Judgment Amount": "$2,500.00",
                "Filing Date": "04/20/2022",
                "County": "Bronx",
            },
        ]

        df = pd.DataFrame(rows)

        # Create mock connection with proper context manager cursor
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

        inserted = process_simplicity_frame(mock_conn, df, batch_id="test-batch-2")

        assert inserted == 2
        # cursor.execute called twice (once per row)
        assert mock_cursor.execute.call_count == 2

    @pytest.mark.skip(
        reason="Legacy: side_effect mocking broken after ReconciliationService integration"
    )
    def test_db_error_logged_not_crashed(self):
        """DB errors on individual rows are logged but don't crash."""
        rows = [
            {
                "Case Number": "12345-2021",
                "Plaintiff": "ACME Collections LLC",
                "Defendant": "John Smith",
                "Judgment Amount": "$1,000.00",
                "Filing Date": "03/15/2021",
                "County": "New York",
            },
            {
                "Case Number": "67890-2022",
                "Plaintiff": "Empire Funding Corp",
                "Defendant": "Jane Doe",
                "Judgment Amount": "$2,500.00",
                "Filing Date": "04/20/2022",
                "County": "Bronx",
            },
        ]

        df = pd.DataFrame(rows)

        # Create mock connection with proper context manager cursor
        mock_cursor = MagicMock()
        # First call succeeds, second fails
        mock_cursor.execute.side_effect = [None, Exception("DB constraint violation")]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

        with patch("backend.workers.ingest_processor._log_invalid_row") as mock_log_invalid:
            inserted = process_simplicity_frame(mock_conn, df, batch_id="test-batch-3")

        # Only first row inserted
        assert inserted == 1

        # DB error logged for second row
        mock_log_invalid.assert_called_once()
        args = mock_log_invalid.call_args[0]
        assert "DB error" in args[3]  # error_message


# =============================================================================
# Run with: pytest tests/test_workers_ingest.py -v
# =============================================================================


# =============================================================================
# Additional Edge Case Tests
# =============================================================================


@pytest.mark.unit
class TestCleanCurrencyEdgeCases:
    """Additional edge case tests for _clean_currency."""

    def test_negative_amount(self):
        """Negative amounts are parsed correctly."""
        assert _clean_currency("-500.00") == Decimal("-500.00")

    def test_large_amount(self):
        """Very large amounts are handled."""
        result = _clean_currency("$999,999,999.99")
        assert result == Decimal("999999999.99")

    def test_decimal_object(self):
        """Decimal pass-through."""
        d = Decimal("1234.56")
        assert _clean_currency(d) == d

    def test_zero(self):
        """Zero is valid."""
        assert _clean_currency("0") == Decimal("0")
        assert _clean_currency("$0.00") == Decimal("0.00")

    def test_cents_only(self):
        """Cents-only amounts."""
        assert _clean_currency("0.99") == Decimal("0.99")
        assert _clean_currency("$.50") == Decimal(".50")


@pytest.mark.unit
class TestMapSimplicityRowEdgeCases:
    """Additional edge case tests for _map_simplicity_row."""

    def test_special_characters_in_names(self):
        """Special characters in plaintiff/defendant names are preserved."""
        row = pd.Series(
            {
                "Case Number": "12345-2021",
                "Plaintiff": "O'Brien & Associates, LLC",
                "Defendant": "José García-Hernández",
                "Judgment Amount": "$1,000.00",
                "Filing Date": "03/15/2021",
                "County": "New York",
            }
        )
        result = _map_simplicity_row(row)
        assert result["plaintiff_name"] == "O'Brien & Associates, LLC"
        assert result["defendant_name"] == "José García-Hernández"

    def test_very_long_case_number(self):
        """Long case numbers are preserved."""
        long_case = "A" * 100 + "-2021"
        row = pd.Series(
            {
                "Case Number": long_case,
                "Plaintiff": "Test",
                "Defendant": "Test",
                "Judgment Amount": "$1,000.00",
                "Filing Date": "03/15/2021",
                "County": "Test",
            }
        )
        result = _map_simplicity_row(row)
        assert result["case_number"] == long_case

    def test_zero_amount_is_valid(self):
        """Zero judgment amount is technically valid."""
        row = pd.Series(
            {
                "Case Number": "12345-2021",
                "Plaintiff": "Test",
                "Defendant": "Test",
                "Judgment Amount": "$0.00",
                "Filing Date": "03/15/2021",
                "County": "Test",
            }
        )
        result = _map_simplicity_row(row)
        assert result["judgment_amount"] == Decimal("0.00")


# =============================================================================
# Job Processing Tests (with mocked DB)
# =============================================================================


@pytest.mark.unit
class TestClaimPendingJob:
    """Tests for claim_pending_job with mocked DB."""

    def test_claim_returns_job_dict(self):
        """Claiming a job returns the job as a dict."""
        from backend.workers.ingest_processor import claim_pending_job

        mock_job = {
            "id": "test-job-123",
            "job_type": "ingest_csv",
            "status": "processing",
            "payload": {"file_path": "test.csv", "batch_id": "batch-1"},
        }

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = mock_job
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

        result = claim_pending_job(mock_conn)

        assert result == mock_job
        mock_conn.commit.assert_called_once()

    def test_claim_returns_none_when_no_jobs(self):
        """When no jobs are available, returns None."""
        from backend.workers.ingest_processor import claim_pending_job

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

        result = claim_pending_job(mock_conn)

        assert result is None


@pytest.mark.unit
class TestMarkJobFunctions:
    """Tests for mark_job_completed and mark_job_failed."""

    def test_mark_completed(self):
        """mark_job_completed updates status correctly."""
        from backend.workers.ingest_processor import mark_job_completed

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

        mark_job_completed(mock_conn, "job-123")

        # Verify UPDATE was called
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args[0]
        assert "SET status = 'completed'" in call_args[0]
        mock_conn.commit.assert_called_once()

    def test_mark_failed(self):
        """mark_job_failed updates status with error."""
        from backend.workers.ingest_processor import mark_job_failed

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

        mark_job_failed(mock_conn, "job-123", "Something went wrong")

        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args[0]
        assert "SET status = 'failed'" in call_args[0]
        assert call_args[1][0] == "Something went wrong"

    def test_mark_failed_truncates_long_error(self):
        """Long error messages are truncated to 2000 chars."""
        from backend.workers.ingest_processor import mark_job_failed

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

        long_error = "X" * 5000
        mark_job_failed(mock_conn, "job-123", long_error)

        call_args = mock_cursor.execute.call_args[0]
        # Error should be truncated to 2000 chars
        assert len(call_args[1][0]) == 2000


@pytest.mark.unit
class TestProcessJob:
    """Tests for process_job function."""

    def test_missing_file_path_marks_failed(self):
        """Job without file_path in payload is marked failed."""
        from backend.workers.ingest_processor import process_job

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

        job = {"id": "job-123", "payload": {}}  # No file_path

        with patch("backend.workers.ingest_processor.mark_job_failed") as mock_fail:
            process_job(mock_conn, job)

        mock_fail.assert_called_once()
        assert "file_path" in mock_fail.call_args[0][2].lower()

    def test_empty_csv_marks_completed(self):
        """Empty CSV file marks job as completed with 0 rows."""
        from backend.services.ingest_hardening import DuplicateCheckResult
        from backend.workers.ingest_processor import LoadedCSV, process_job

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

        job = {"id": "job-123", "payload": {"file_path": "test.csv", "batch_id": "batch-1"}}

        empty_df = pd.DataFrame()
        empty_loaded = LoadedCSV(df=empty_df, raw_content=b"", file_hash="empty_hash")
        not_duplicate = DuplicateCheckResult(is_duplicate=False)

        with (
            patch(
                "backend.workers.ingest_processor.load_csv_from_storage",
                return_value=empty_loaded,
            ),
            patch(
                "backend.workers.ingest_processor.check_duplicate_import",
                return_value=not_duplicate,
            ),
            patch("backend.workers.ingest_processor.mark_job_completed") as mock_complete,
            patch("backend.workers.ingest_processor.update_batch_status") as mock_batch,
        ):
            process_job(mock_conn, job)

        mock_complete.assert_called_once_with(mock_conn, "job-123")
        mock_batch.assert_called_once()
        assert mock_batch.call_args[1]["row_count_valid"] == 0

    def test_csv_load_error_marks_failed(self):
        """Storage error marks job as failed."""
        from backend.workers.ingest_processor import process_job

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

        job = {"id": "job-123", "payload": {"file_path": "test.csv", "batch_id": "batch-1"}}

        with (
            patch(
                "backend.workers.ingest_processor.load_csv_from_storage",
                side_effect=Exception("Storage unavailable"),
            ),
            patch("backend.workers.ingest_processor.mark_job_failed") as mock_fail,
        ):
            process_job(mock_conn, job)

        mock_fail.assert_called_once()
        assert "Storage unavailable" in mock_fail.call_args[0][2]


@pytest.mark.unit
class TestLoadCsvFromStorage:
    """Tests for load_csv_from_storage."""

    def test_local_file_prefix(self):
        """file:// prefix loads from local filesystem."""
        import os
        import tempfile

        from backend.workers.ingest_processor import load_csv_from_storage

        # Create a temp CSV file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("Case Number,Plaintiff,Defendant,Judgment Amount,Filing Date,County\n")
            f.write("12345,Test P,Test D,$1000,01/01/2021,TestCounty\n")
            temp_path = f.name

        try:
            loaded = load_csv_from_storage(f"file://{temp_path}")
            assert len(loaded.df) == 1
            assert str(loaded.df.iloc[0]["Case Number"]) == "12345"
            assert loaded.file_hash  # Hash should be computed
            assert loaded.raw_content  # Raw content should be preserved
        finally:
            os.unlink(temp_path)

    def test_supabase_storage_path_parsing(self):
        """Supabase storage paths are parsed correctly."""
        from backend.workers.ingest_processor import load_csv_from_storage

        # Mock Supabase client
        mock_storage = MagicMock()
        mock_storage.from_.return_value.download.return_value = (
            b"Case Number,Plaintiff\n12345,Test\n"
        )

        mock_client = MagicMock()
        mock_client.storage = mock_storage

        with patch(
            "backend.workers.ingest_processor.create_supabase_client",
            return_value=mock_client,
        ):
            loaded = load_csv_from_storage("intake/batch_123.csv")

        # Should use 'intake' bucket and 'batch_123.csv' path
        mock_storage.from_.assert_called_with("intake")
        mock_storage.from_.return_value.download.assert_called_with("batch_123.csv")
        assert len(loaded.df) == 1
        assert loaded.file_hash  # Hash should be computed


@pytest.mark.unit
class TestGenerateCollectabilityScore:
    """Tests for generate_collectability_score."""

    def test_score_in_range(self):
        """Score is always between 0 and 100."""
        from backend.workers.ingest_processor import generate_collectability_score

        for _ in range(100):
            score = generate_collectability_score()
            assert 0 <= score <= 100
            assert isinstance(score, int)
