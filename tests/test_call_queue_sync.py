"""Unit tests for the call queue sync handler.

Tests:
- Payload extraction from various PGMQ job formats
- Task upsert idempotency
- Batch vs single plaintiff mode
- Error handling and notify_ops queueing
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Any, Dict


# Import handlers to test
from workers.call_queue_sync_handler import (
    _extract_plaintiff_id,
    _is_batch_job,
    fetch_plaintiffs_needing_calls,
    fetch_single_plaintiff,
    upsert_call_task,
    queue_notify_ops,
    handle_call_queue_sync,
    sync_all_call_tasks,
)


class TestExtractPlaintiffId:
    """Tests for _extract_plaintiff_id helper."""

    def test_direct_plaintiff_id(self):
        """Extract plaintiff_id from top-level job."""
        job = {"plaintiff_id": "abc-123"}
        assert _extract_plaintiff_id(job) == "abc-123"

    def test_nested_payload(self):
        """Extract from single-nested payload."""
        job = {"payload": {"plaintiff_id": "def-456"}}
        assert _extract_plaintiff_id(job) == "def-456"

    def test_double_nested_payload(self):
        """Extract from double-nested payload (queue_job RPC format)."""
        job = {"payload": {"payload": {"plaintiff_id": "ghi-789"}}}
        assert _extract_plaintiff_id(job) == "ghi-789"

    def test_missing_plaintiff_id(self):
        """Return None when plaintiff_id is missing."""
        job = {"kind": "call_queue_sync"}
        assert _extract_plaintiff_id(job) is None

    def test_empty_job(self):
        """Return None for empty job."""
        assert _extract_plaintiff_id({}) is None

    def test_non_dict_job(self):
        """Return None for non-dict job."""
        assert _extract_plaintiff_id(None) is None
        assert _extract_plaintiff_id("string") is None

    def test_whitespace_trimming(self):
        """Trim whitespace from plaintiff_id."""
        job = {"plaintiff_id": "  abc-123  "}
        assert _extract_plaintiff_id(job) == "abc-123"


class TestIsBatchJob:
    """Tests for _is_batch_job helper."""

    def test_direct_batch_true(self):
        """Detect batch=True at top level."""
        job = {"batch": True}
        assert _is_batch_job(job) is True

    def test_nested_batch(self):
        """Detect batch=True in nested payload."""
        job = {"payload": {"batch": True}}
        assert _is_batch_job(job) is True

    def test_double_nested_batch(self):
        """Detect batch=True in double-nested payload."""
        job = {"payload": {"payload": {"batch": True}}}
        assert _is_batch_job(job) is True

    def test_batch_false(self):
        """Return False when batch is False."""
        job = {"batch": False}
        assert _is_batch_job(job) is False

    def test_batch_missing(self):
        """Return False when batch is missing."""
        job = {"plaintiff_id": "abc-123"}
        assert _is_batch_job(job) is False

    def test_non_dict(self):
        """Return False for non-dict input."""
        assert _is_batch_job(None) is False
        assert _is_batch_job("batch") is False


class TestFetchPlaintiffsNeedingCalls:
    """Tests for fetch_plaintiffs_needing_calls."""

    def test_returns_plaintiffs_list(self):
        """Should return list of plaintiff dicts."""
        mock_client = MagicMock()

        # Mock v_plaintiff_call_queue response
        mock_client.table.return_value.select.return_value.execute.return_value.data = [
            {"plaintiff_id": "p1"},
            {"plaintiff_id": "p2"},
        ]

        # Mock plaintiffs table response (for call-worthy statuses)
        plaintiffs_mock = MagicMock()
        plaintiffs_mock.select.return_value.in_.return_value.execute.return_value.data = [
            {"id": "p1", "name": "John Doe", "status": "new"},
            {"id": "p3", "name": "Jane Doe", "status": "contacted"},
        ]

        def table_side_effect(table_name):
            if table_name == "v_plaintiff_call_queue":
                return mock_client.table.return_value
            elif table_name == "plaintiffs":
                return plaintiffs_mock
            return MagicMock()

        mock_client.table.side_effect = table_side_effect

        result = fetch_plaintiffs_needing_calls(mock_client)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["plaintiff_id"] == "p1"
        assert result[0]["has_existing_task"] is True
        assert result[1]["plaintiff_id"] == "p3"
        assert result[1]["has_existing_task"] is False


class TestFetchSinglePlaintiff:
    """Tests for fetch_single_plaintiff."""

    def test_found_plaintiff(self):
        """Should return plaintiff dict when found."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "p1", "name": "John Doe", "status": "new"}
        ]

        result = fetch_single_plaintiff(mock_client, "p1")

        assert result is not None
        assert result["plaintiff_id"] == "p1"
        assert result["plaintiff_name"] == "John Doe"

    def test_not_found(self):
        """Should return None when not found."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = (
            []
        )

        result = fetch_single_plaintiff(mock_client, "nonexistent")

        assert result is None


class TestUpsertCallTask:
    """Tests for upsert_call_task."""

    def test_successful_upsert(self):
        """Should return success response from RPC."""
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value.data = {
            "success": True,
            "task_id": "task-123",
            "plaintiff_id": "p1",
            "kind": "call",
            "is_new": True,
        }

        result = upsert_call_task(mock_client, "p1")

        assert result["success"] is True
        assert result["task_id"] == "task-123"
        assert result["is_new"] is True

        # Verify RPC was called with correct params
        mock_client.rpc.assert_called_once()
        call_args = mock_client.rpc.call_args
        assert call_args[0][0] == "upsert_plaintiff_task"
        assert call_args[0][1]["p_plaintiff_id"] == "p1"
        assert call_args[0][1]["p_kind"] == "call"

    def test_custom_due_at(self):
        """Should use provided due_at."""
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value.data = {"success": True}

        custom_due = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        upsert_call_task(mock_client, "p1", due_at=custom_due)

        call_args = mock_client.rpc.call_args
        assert "2025-01-15" in call_args[0][1]["p_due_at"]

    def test_rpc_exception(self):
        """Should return error dict on exception."""
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.side_effect = Exception("RPC failed")

        result = upsert_call_task(mock_client, "p1")

        assert result["success"] is False
        assert "RPC failed" in result["error"]


class TestQueueNotifyOps:
    """Tests for queue_notify_ops."""

    def test_successful_queue(self):
        """Should queue notify_ops job."""
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value.data = None

        result = queue_notify_ops(mock_client, "Test message", {"plaintiff_id": "p1"})

        assert result is True
        mock_client.rpc.assert_called_once()

    def test_queue_failure(self):
        """Should return False on failure (but not raise)."""
        mock_client = MagicMock()
        mock_client.rpc.side_effect = Exception("Queue failed")

        result = queue_notify_ops(mock_client, "Test message", {})

        assert result is False


class TestHandleCallQueueSync:
    """Tests for handle_call_queue_sync async handler."""

    @pytest.mark.asyncio
    async def test_invalid_payload_returns_true(self):
        """Invalid payload should return True (don't retry)."""
        job = {"msg_id": "123", "kind": "call_queue_sync"}

        with patch("workers.call_queue_sync_handler.create_supabase_client"):
            result = await handle_call_queue_sync(job)

        assert result is True

    @pytest.mark.asyncio
    async def test_single_plaintiff_sync(self):
        """Should sync single plaintiff when plaintiff_id provided."""
        job = {"msg_id": "123", "plaintiff_id": "p1"}

        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "p1", "name": "John", "status": "new"}
        ]
        mock_client.rpc.return_value.execute.return_value.data = {
            "success": True,
            "task_id": "t1",
            "is_new": True,
        }

        with patch(
            "workers.call_queue_sync_handler.create_supabase_client",
            return_value=mock_client,
        ):
            result = await handle_call_queue_sync(job)

        assert result is True

    @pytest.mark.asyncio
    async def test_missing_plaintiff_returns_true(self):
        """Should return True for missing plaintiff (don't retry)."""
        job = {"msg_id": "123", "plaintiff_id": "nonexistent"}

        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = (
            []
        )

        with patch(
            "workers.call_queue_sync_handler.create_supabase_client",
            return_value=mock_client,
        ):
            result = await handle_call_queue_sync(job)

        assert result is True

    @pytest.mark.asyncio
    async def test_batch_sync(self):
        """Should sync all plaintiffs in batch mode."""
        job = {"msg_id": "123", "batch": True}

        mock_client = MagicMock()

        # Setup mock for fetch_plaintiffs_needing_calls
        call_queue_mock = MagicMock()
        call_queue_mock.select.return_value.execute.return_value.data = []

        plaintiffs_mock = MagicMock()
        plaintiffs_mock.select.return_value.in_.return_value.execute.return_value.data = [
            {"id": "p1", "name": "John", "status": "new"},
            {"id": "p2", "name": "Jane", "status": "contacted"},
        ]

        def table_side_effect(name):
            if name == "v_plaintiff_call_queue":
                return call_queue_mock
            return plaintiffs_mock

        mock_client.table.side_effect = table_side_effect
        mock_client.rpc.return_value.execute.return_value.data = {
            "success": True,
            "task_id": "t1",
            "is_new": True,
        }

        with patch(
            "workers.call_queue_sync_handler.create_supabase_client",
            return_value=mock_client,
        ):
            result = await handle_call_queue_sync(job)

        assert result is True


class TestSyncAllCallTasks:
    """Tests for sync_all_call_tasks entry point."""

    @pytest.mark.asyncio
    async def test_returns_summary(self):
        """Should return summary dict with counts."""
        mock_client = MagicMock()

        # Mock fetch
        call_queue_mock = MagicMock()
        call_queue_mock.select.return_value.execute.return_value.data = []

        plaintiffs_mock = MagicMock()
        plaintiffs_mock.select.return_value.in_.return_value.execute.return_value.data = [
            {"id": "p1", "name": "John", "status": "new"},
        ]

        def table_side_effect(name):
            if name == "v_plaintiff_call_queue":
                return call_queue_mock
            return plaintiffs_mock

        mock_client.table.side_effect = table_side_effect
        mock_client.rpc.return_value.execute.return_value.data = {
            "success": True,
            "task_id": "t1",
            "is_new": True,
        }

        with patch(
            "workers.call_queue_sync_handler.create_supabase_client",
            return_value=mock_client,
        ):
            result = await sync_all_call_tasks()

        assert "total_plaintiffs" in result
        assert "success_count" in result
        assert "failure_count" in result
        assert "created_count" in result
        assert "updated_count" in result
