"""
Tests for ingest pipeline hardening features.

Tests:
- File hash computation
- Duplicate import detection
- ImportErrorRecorder batch operations
- Integration with ingest worker
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from backend.services.ingest_hardening import (
    DuplicateCheckResult,
    ImportError,
    ImportErrorRecorder,
    check_duplicate_import,
    compute_file_hash,
    compute_file_hash_from_path,
    record_import_error,
    update_batch_file_hash,
)

# =============================================================================
# FILE HASH TESTS
# =============================================================================


class TestFileHash:
    """Tests for file hash computation."""

    def test_compute_file_hash_empty(self):
        """Empty content produces consistent hash."""
        h = compute_file_hash(b"")
        assert len(h) == 64  # SHA-256 produces 64 hex characters
        # SHA-256 of empty string is known
        assert h == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_compute_file_hash_content(self):
        """Same content produces same hash."""
        content = b"Case Number,Plaintiff,Defendant\n123,Alice,Bob"
        h1 = compute_file_hash(content)
        h2 = compute_file_hash(content)
        assert h1 == h2
        assert len(h1) == 64

    def test_compute_file_hash_different_content(self):
        """Different content produces different hash."""
        h1 = compute_file_hash(b"content1")
        h2 = compute_file_hash(b"content2")
        assert h1 != h2

    def test_compute_file_hash_from_path(self, tmp_path: Path):
        """Hash from file path matches hash from content."""
        content = b"test file content\nwith multiple lines"
        file_path = tmp_path / "test.csv"
        file_path.write_bytes(content)

        h_path = compute_file_hash_from_path(str(file_path))
        h_content = compute_file_hash(content)
        assert h_path == h_content

    def test_compute_file_hash_deterministic(self):
        """Hash is deterministic across calls."""
        content = b"deterministic test"
        hashes = [compute_file_hash(content) for _ in range(100)]
        assert len(set(hashes)) == 1


# =============================================================================
# DUPLICATE CHECK TESTS
# =============================================================================


class TestDuplicateCheck:
    """Tests for duplicate import detection."""

    def test_duplicate_check_result_not_duplicate(self):
        """DuplicateCheckResult for non-duplicate."""
        result = DuplicateCheckResult(is_duplicate=False)
        assert not result.is_duplicate
        assert result.existing_batch_id is None
        assert "No duplicate found" in result.message

    def test_duplicate_check_result_is_duplicate(self):
        """DuplicateCheckResult for duplicate."""
        from datetime import datetime, timezone

        result = DuplicateCheckResult(
            is_duplicate=True,
            existing_batch_id="abc-123",
            existing_status="completed",
            existing_created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        assert result.is_duplicate
        assert "abc-123" in result.message
        assert "completed" in result.message

    def test_check_duplicate_force_bypass(self):
        """Force flag bypasses duplicate check."""
        mock_conn = MagicMock()
        result = check_duplicate_import(mock_conn, "somehash", force=True)
        assert not result.is_duplicate
        # No DB call should be made
        mock_conn.cursor.assert_not_called()

    def test_check_duplicate_no_match(self):
        """No duplicate when file_hash not found."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # Simulate SQL function not existing, fallback query returns None
        mock_cursor.execute.side_effect = [
            Exception("function not found"),  # SQL function fails
            None,  # Fallback query succeeds
        ]
        mock_cursor.fetchone.return_value = None

        result = check_duplicate_import(mock_conn, "newhash", force=False)
        # Should return not duplicate due to exception handling
        assert not result.is_duplicate


# =============================================================================
# IMPORT ERROR TESTS
# =============================================================================


class TestImportError:
    """Tests for ImportError dataclass."""

    def test_import_error_minimal(self):
        """ImportError with required fields only."""
        err = ImportError(
            row_number=5,
            error_type="validation",
            error_message="Missing required field",
        )
        assert err.row_number == 5
        assert err.error_type == "validation"
        assert err.raw_data is None

    def test_import_error_full(self):
        """ImportError with all fields."""
        err = ImportError(
            row_number=10,
            error_type="parse",
            error_message="Invalid date format",
            raw_data={"date": "not-a-date"},
            field_name="date",
            field_value="not-a-date",
        )
        assert err.row_number == 10
        assert err.field_name == "date"
        assert err.raw_data["date"] == "not-a-date"


class TestImportErrorRecorder:
    """Tests for batch error recording."""

    def test_recorder_add_error(self):
        """Errors are buffered before flush."""
        mock_conn = MagicMock()
        recorder = ImportErrorRecorder(mock_conn, "batch-123", flush_threshold=10)

        recorder.add_error(
            row_number=1,
            error_type="validation",
            error_message="Bad value",
        )

        assert recorder.pending_count == 1
        assert recorder.total_recorded == 0

    def test_recorder_auto_flush_at_threshold(self):
        """Recorder auto-flushes at threshold."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        recorder = ImportErrorRecorder(mock_conn, "batch-123", flush_threshold=3)

        # Add 2 errors - no flush yet
        recorder.add_error(row_number=1, error_type="a", error_message="err1")
        recorder.add_error(row_number=2, error_type="b", error_message="err2")
        assert recorder.pending_count == 2
        mock_cursor.executemany.assert_not_called()

        # Add 3rd error - should trigger flush
        recorder.add_error(row_number=3, error_type="c", error_message="err3")
        assert recorder.pending_count == 0
        assert recorder.total_recorded == 3
        mock_cursor.executemany.assert_called_once()

    def test_recorder_context_manager_flushes(self):
        """Context manager flushes on exit."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with ImportErrorRecorder(mock_conn, "batch-123", flush_threshold=100) as recorder:
            recorder.add_error(row_number=1, error_type="a", error_message="err")
            recorder.add_error(row_number=2, error_type="b", error_message="err")

        # Should have flushed on context exit
        mock_cursor.executemany.assert_called_once()

    def test_recorder_handles_missing_table(self):
        """Recorder handles missing ops.import_errors table gracefully."""
        import psycopg.errors

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.executemany.side_effect = psycopg.errors.UndefinedTable("table not found")

        recorder = ImportErrorRecorder(mock_conn, "batch-123", flush_threshold=1)
        recorder.add_error(row_number=1, error_type="a", error_message="err")

        # Should not raise, just clear the buffer
        assert recorder.pending_count == 0


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestIngestWorkerIntegration:
    """Integration tests for ingest worker with hardening features."""

    def test_loaded_csv_dataclass(self):
        """LoadedCSV dataclass from ingest worker."""
        import pandas as pd

        from backend.workers.ingest_processor import LoadedCSV

        df = pd.DataFrame({"col": [1, 2, 3]})
        content = b"col\n1\n2\n3"
        hash_val = compute_file_hash(content)

        loaded = LoadedCSV(df=df, raw_content=content, file_hash=hash_val)
        assert len(loaded.df) == 3
        assert loaded.file_hash == hash_val
        assert loaded.raw_content == content

    def test_load_csv_from_storage_local_with_hash(self, tmp_path: Path):
        """load_csv_from_storage computes hash for local files."""
        from backend.workers.ingest_processor import load_csv_from_storage

        csv_content = b"Case Number,Plaintiff,Defendant,Judgment Amount,Filing Date,County\n123,Alice,Bob,1000.00,01/01/2024,Test County"
        csv_file = tmp_path / "test.csv"
        csv_file.write_bytes(csv_content)

        loaded = load_csv_from_storage(f"file://{csv_file}")

        assert len(loaded.df) == 1
        assert loaded.file_hash == compute_file_hash(csv_content)
        assert loaded.raw_content == csv_content


# =============================================================================
# BATCH FILE HASH UPDATE TESTS
# =============================================================================


class TestBatchFileHashUpdate:
    """Tests for updating batch with file hash."""

    def test_update_batch_file_hash_success(self):
        """Successfully update batch with file hash."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        update_batch_file_hash(mock_conn, "batch-123", "abc123hash", force_reimport=False)

        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_update_batch_file_hash_with_force(self):
        """Update batch with force_reimport flag."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        update_batch_file_hash(mock_conn, "batch-456", "xyz789hash", force_reimport=True)

        # Verify the execute was called with correct params
        call_args = mock_cursor.execute.call_args
        assert "xyz789hash" in call_args[0][1]
        assert True in call_args[0][1]  # force_reimport=True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
