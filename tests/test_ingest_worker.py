"""
tests/test_ingest_worker.py
============================
Unit tests for workers/ingest_worker.py

Tests the transactional claim pattern, idempotency, and edge cases.

NOTE: These tests are standalone and do not require backend imports.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from workers.ingest_worker import (
    ClaimResult,
    DuplicateBatchError,
    ImportRunStatus,
    IngestError,
    IngestWorker,
    JobAlreadyRunningError,
    compute_file_hash,
)

# =============================================================================
# Unit tests for compute_file_hash
# =============================================================================


class TestComputeFileHash:
    """Tests for compute_file_hash function."""

    def test_compute_hash_empty_content(self) -> None:
        """Empty content should produce a valid SHA-256 hash."""
        result = compute_file_hash(b"")
        assert result.startswith("sha256:")
        # SHA-256 of empty string is e3b0c44...
        assert result == "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_compute_hash_simple_content(self) -> None:
        """Simple content should produce deterministic hash."""
        content = b"hello world"
        result = compute_file_hash(content)
        assert result.startswith("sha256:")
        # Verify it's deterministic
        assert compute_file_hash(content) == result

    def test_compute_hash_different_content(self) -> None:
        """Different content should produce different hashes."""
        hash1 = compute_file_hash(b"content A")
        hash2 = compute_file_hash(b"content B")
        assert hash1 != hash2


# =============================================================================
# Unit tests for ClaimResult enum
# =============================================================================


class TestClaimResult:
    """Tests for ClaimResult enum values."""

    def test_claim_result_values(self) -> None:
        """Verify all expected claim result values exist."""
        assert ClaimResult.CLAIMED.value == "claimed"
        assert ClaimResult.ALREADY_RUNNING.value == "already_running"
        assert ClaimResult.ALREADY_COMPLETED.value == "already_completed"
        assert ClaimResult.ALREADY_FAILED.value == "already_failed"
        assert ClaimResult.STALE_TAKEOVER.value == "stale_takeover"


# =============================================================================
# Unit tests for ImportRunStatus enum
# =============================================================================


class TestImportRunStatus:
    """Tests for ImportRunStatus enum values."""

    def test_status_values(self) -> None:
        """Verify all expected status values exist."""
        assert ImportRunStatus.PENDING.value == "pending"
        assert ImportRunStatus.PROCESSING.value == "processing"
        assert ImportRunStatus.COMPLETED.value == "completed"
        assert ImportRunStatus.FAILED.value == "failed"


# =============================================================================
# Unit tests for exception classes
# =============================================================================


class TestExceptions:
    """Tests for custom exception classes."""

    def test_duplicate_batch_error(self) -> None:
        """DuplicateBatchError should include source_batch_id."""
        err = DuplicateBatchError("test_batch_123")
        assert err.source_batch_id == "test_batch_123"
        assert "test_batch_123" in str(err)
        assert "already completed" in str(err)

    def test_job_already_running_error(self) -> None:
        """JobAlreadyRunningError should include source_batch_id."""
        err = JobAlreadyRunningError("running_batch_456")
        assert err.source_batch_id == "running_batch_456"
        assert "running_batch_456" in str(err)
        assert "being processed" in str(err)


# =============================================================================
# Integration-style tests (mocked DB)
# =============================================================================


def make_mock_cursor(fetchone_results: list) -> AsyncMock:
    """Create a mock cursor with proper async context manager support."""
    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.fetchone = AsyncMock(side_effect=fetchone_results)
    return mock_cursor


def make_mock_connection(cursor_mock: AsyncMock) -> AsyncMock:
    """Create a mock connection with proper async context manager support."""
    mock_conn = AsyncMock()
    mock_conn.commit = AsyncMock()

    # cursor() returns an async context manager that yields the cursor
    cursor_cm = AsyncMock()
    cursor_cm.__aenter__ = AsyncMock(return_value=cursor_mock)
    cursor_cm.__aexit__ = AsyncMock(return_value=None)
    mock_conn.cursor = lambda: cursor_cm

    return mock_conn


class TestIngestWorkerDoubleSubmit:
    """Tests for double-submit prevention."""

    @pytest.mark.asyncio
    async def test_double_submit_raises_duplicate_error(self) -> None:
        """Submitting a completed batch should raise DuplicateBatchError."""
        worker = IngestWorker(db_url="postgresql://test:test@localhost:6543/test?sslmode=require")

        completed_job = {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "source_batch_id": "test_batch",
            "file_hash": "sha256:abc",
            "status": "completed",
            "started_at": None,
            "completed_at": "2026-01-13T10:00:00Z",
            "record_count": 100,
            "error_details": None,
            "created_at": "2026-01-13T09:00:00Z",
            "updated_at": "2026-01-13T10:00:00Z",
        }

        mock_cursor = make_mock_cursor(
            [
                completed_job,  # _create_or_get_job returns a job
                None,  # _try_claim_job: UPDATE returns nothing (job not pending)
                completed_job,  # _try_claim_job: SELECT returns the completed job
            ]
        )
        mock_conn = make_mock_connection(mock_cursor)

        # Make mock_conn work as async context manager
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        async def dummy_processor(batch_id: str, file_hash: str) -> int:
            return 0

        async def mock_get_connection():
            return mock_conn

        with patch.object(worker, "_get_connection", mock_get_connection):
            with pytest.raises(DuplicateBatchError) as exc_info:
                await worker.process_batch(
                    source_batch_id="test_batch",
                    file_hash="sha256:abc",
                    processor=dummy_processor,
                )

            assert exc_info.value.source_batch_id == "test_batch"

    @pytest.mark.asyncio
    async def test_completed_batch_skip_without_raise(self) -> None:
        """With raise_on_duplicate=False, should return skip status."""
        worker = IngestWorker(db_url="postgresql://test:test@localhost:6543/test?sslmode=require")

        completed_job = {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "source_batch_id": "test_batch",
            "file_hash": "sha256:abc",
            "status": "completed",
            "started_at": None,
            "completed_at": "2026-01-13T10:00:00Z",
            "record_count": 100,
            "error_details": None,
            "created_at": "2026-01-13T09:00:00Z",
            "updated_at": "2026-01-13T10:00:00Z",
        }

        mock_cursor = make_mock_cursor([completed_job, None, completed_job])
        mock_conn = make_mock_connection(mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        async def dummy_processor(batch_id: str, file_hash: str) -> int:
            return 0

        async def mock_get_connection():
            return mock_conn

        with patch.object(worker, "_get_connection", mock_get_connection):
            result = await worker.process_batch(
                source_batch_id="test_batch",
                file_hash="sha256:abc",
                processor=dummy_processor,
                raise_on_duplicate=False,
            )

            assert result["status"] == "skipped"
            assert result["reason"] == "already_completed"


class TestIngestWorkerStaleTakeover:
    """Tests for stale job takeover."""

    @pytest.mark.asyncio
    async def test_stale_job_takeover_success(self) -> None:
        """A stale processing job should be taken over."""
        from datetime import datetime, timedelta, timezone

        worker = IngestWorker(db_url="postgresql://test:test@localhost:6543/test?sslmode=require")

        job_id = "550e8400-e29b-41d4-a716-446655440000"
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=10)

        stale_job = {
            "id": job_id,
            "source_batch_id": "stale_batch",
            "file_hash": "sha256:stale",
            "status": "processing",
            "started_at": stale_time,
            "completed_at": None,
            "record_count": None,
            "error_details": None,
            "created_at": stale_time,
            "updated_at": stale_time,  # Stale - older than threshold
        }

        taken_over_job = {**stale_job, "updated_at": datetime.now(timezone.utc)}

        mock_cursor = make_mock_cursor(
            [
                stale_job,  # _create_or_get_job returns existing job
                None,  # _try_claim_job: UPDATE pending returns nothing
                stale_job,  # _try_claim_job: SELECT returns stale job
                taken_over_job,  # _try_claim_job: UPDATE stale returns taken job
            ]
        )
        mock_conn = make_mock_connection(mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        processor_called = False

        async def dummy_processor(batch_id: str, file_hash: str) -> int:
            nonlocal processor_called
            processor_called = True
            return 50

        async def mock_get_connection():
            return mock_conn

        with patch.object(worker, "_get_connection", mock_get_connection):
            with patch.object(worker, "_start_heartbeat", new_callable=AsyncMock):
                with patch.object(worker, "_stop_heartbeat_task", new_callable=AsyncMock):
                    with patch.object(worker, "_mark_completed", new_callable=AsyncMock):
                        result = await worker.process_batch(
                            source_batch_id="stale_batch",
                            file_hash="sha256:stale",
                            processor=dummy_processor,
                        )

        assert result["claim_result"] == "stale_takeover"
        assert processor_called


class TestIngestWorkerJobAlreadyRunning:
    """Tests for job already running prevention."""

    @pytest.mark.asyncio
    async def test_active_job_raises_already_running(self) -> None:
        """An actively running job should raise JobAlreadyRunningError."""
        from datetime import datetime, timezone

        worker = IngestWorker(db_url="postgresql://test:test@localhost:6543/test?sslmode=require")

        recent_time = datetime.now(timezone.utc)

        active_job = {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "source_batch_id": "active_batch",
            "file_hash": "sha256:active",
            "status": "processing",
            "started_at": recent_time,
            "completed_at": None,
            "record_count": None,
            "error_details": None,
            "created_at": recent_time,
            "updated_at": recent_time,  # Recent - not stale
        }

        mock_cursor = make_mock_cursor(
            [
                active_job,  # _create_or_get_job returns existing job
                None,  # _try_claim_job: UPDATE pending returns nothing
                active_job,  # _try_claim_job: SELECT returns active job
                None,  # _try_claim_job: UPDATE stale returns nothing (not stale)
            ]
        )
        mock_conn = make_mock_connection(mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        async def dummy_processor(batch_id: str, file_hash: str) -> int:
            return 0

        async def mock_get_connection():
            return mock_conn

        with patch.object(worker, "_get_connection", mock_get_connection):
            with pytest.raises(JobAlreadyRunningError) as exc_info:
                await worker.process_batch(
                    source_batch_id="active_batch",
                    file_hash="sha256:active",
                    processor=dummy_processor,
                )

            assert exc_info.value.source_batch_id == "active_batch"
