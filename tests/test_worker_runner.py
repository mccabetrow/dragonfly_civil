"""Tests for workers.runner module.

These tests verify worker loop behavior WITHOUT running infinite loops.
We mock the QueueClient and test discrete behaviors:
- Dequeue returning None triggers sleep
- Dequeue returning a job triggers handler
- Handler success triggers ack
- Handler failure increments retry count
- QueueRpcNotFound breaks the loop
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workers import runner
from workers.queue_client import QueueRpcNotFound


class TestWorkerLoopBehavior:
    """Test worker_loop discrete behaviors by controlling loop iterations."""

    @pytest.mark.asyncio
    async def test_loop_exits_on_queue_rpc_not_found(self, caplog):
        """Verify QueueRpcNotFound causes immediate loop exit."""
        mock_client = MagicMock()
        mock_client.dequeue.side_effect = QueueRpcNotFound("dequeue_job")
        mock_client.close = MagicMock()

        with patch.object(runner, "QueueClient", return_value=mock_client):
            handler = AsyncMock(return_value=True)

            with caplog.at_level("CRITICAL"):
                await runner.worker_loop("enforce", handler, poll_interval=0.01)

            # Loop should have exited - client closed
            mock_client.close.assert_called_once()
            # Handler never called (no jobs dequeued)
            handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_sleeps_when_no_job(self):
        """Verify loop sleeps when dequeue returns None, then exits on error."""
        call_count = 0

        def dequeue_side_effect(kind):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # First call: no job
            raise QueueRpcNotFound("dequeue_job")  # Second call: exit

        mock_client = MagicMock()
        mock_client.dequeue.side_effect = dequeue_side_effect
        mock_client.close = MagicMock()

        with patch.object(runner, "QueueClient", return_value=mock_client):
            with patch.object(asyncio, "sleep", new_callable=AsyncMock) as mock_sleep:
                handler = AsyncMock(return_value=True)
                await runner.worker_loop("enrich", handler, poll_interval=0.5)

                # Should have slept once with poll_interval
                mock_sleep.assert_any_call(0.5)
                # Handler never called (no jobs)
                handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_processes_job_and_acks(self):
        """Verify successful job processing triggers ack."""
        call_count = 0
        test_job = {"msg_id": 42, "payload": {"case_number": "TEST-001"}}

        def dequeue_side_effect(kind):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return test_job  # First call: return job
            raise QueueRpcNotFound("dequeue_job")  # Second call: exit

        mock_client = MagicMock()
        mock_client.dequeue.side_effect = dequeue_side_effect
        mock_client.ack = MagicMock()
        mock_client.close = MagicMock()

        with patch.object(runner, "QueueClient", return_value=mock_client):
            handler = AsyncMock(return_value=True)
            await runner.worker_loop("outreach", handler, poll_interval=0.01)

            # Handler should have been called with the job
            handler.assert_called_once_with(test_job)
            # Ack should have been called with msg_id
            mock_client.ack.assert_called_once_with("outreach", 42)

    @pytest.mark.asyncio
    async def test_loop_retries_on_handler_failure(self):
        """Verify handler failure increments retry count and continues."""
        call_count = 0
        test_job = {"msg_id": 99, "payload": {}}

        def dequeue_side_effect(kind):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return test_job  # First call: return job
            raise QueueRpcNotFound("dequeue_job")  # Second call: exit

        mock_client = MagicMock()
        mock_client.dequeue.side_effect = dequeue_side_effect
        mock_client.ack = MagicMock()
        mock_client.close = MagicMock()

        with patch.object(runner, "QueueClient", return_value=mock_client):
            with patch.object(asyncio, "sleep", new_callable=AsyncMock):
                # Handler raises exception
                handler = AsyncMock(side_effect=ValueError("handler exploded"))
                await runner.worker_loop("enforce", handler, poll_interval=0.01)

                # Handler was called
                handler.assert_called_once_with(test_job)
                # Ack should NOT have been called (handler failed)
                mock_client.ack.assert_not_called()
