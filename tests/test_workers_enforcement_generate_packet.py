"""
Tests for enforcement_generate_packet job type handling.

Tests the complete flow:
1. POST /generate-packet queues a job in ops.job_queue
2. Worker claims and processes enforcement_generate_packet jobs
3. GET /job-status/{job_id} returns status and packet_id when complete
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# Job Type Registration Tests
# =============================================================================


class TestJobTypeRegistration:
    """Tests that enforcement_generate_packet is properly registered."""

    def test_job_type_in_worker_tuple(self):
        """Verify enforcement_generate_packet is in the worker's JOB_TYPES tuple."""
        from backend.workers.enforcement_engine import JOB_TYPES

        assert "enforcement_generate_packet" in JOB_TYPES


# =============================================================================
# Endpoint Tests
# =============================================================================


class TestGeneratePacketEndpoint:
    """Tests for POST /generate-packet endpoint."""

    @pytest.fixture
    def mock_supabase(self):
        """Create a mock Supabase client."""
        client = MagicMock()

        # Mock judgments table lookup
        judgments_response = MagicMock()
        judgments_response.data = [{"id": 123, "case_number": "2024-CV-001234"}]
        client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            judgments_response
        )

        # Mock job_queue insert
        job_response = MagicMock()
        job_response.data = [{"id": "test-job-id", "status": "pending"}]
        client.schema.return_value.table.return_value.insert.return_value.execute.return_value = (
            job_response
        )

        return client

    @pytest.fixture
    def mock_auth(self):
        """Create a mock AuthContext."""
        from backend.core.security import AuthContext

        return AuthContext(subject="test-user", via="api_key")

    @pytest.mark.asyncio
    async def test_generate_packet_queues_job(self, mock_supabase, mock_auth):
        """Verify that generate_packet creates a job in ops.job_queue."""
        from backend.routers.enforcement import GeneratePacketRequest, generate_enforcement_packet

        with patch(
            "backend.routers.enforcement.get_supabase_client",
            return_value=mock_supabase,
        ):
            with patch(
                "backend.routers.enforcement.get_current_user",
                return_value=mock_auth,
            ):
                request = GeneratePacketRequest(
                    judgment_id="123",
                    strategy="wage_garnishment",
                )

                response = await generate_enforcement_packet(request, mock_auth)

                # Verify job was inserted
                assert response.status == "queued"
                assert response.job_id is not None
                assert response.packet_id is None  # Not yet generated

                # Verify the insert call was made to ops.job_queue
                mock_supabase.schema.assert_called_with("ops")
                insert_call = mock_supabase.schema.return_value.table.return_value.insert
                assert insert_call.called

    @pytest.mark.asyncio
    async def test_generate_packet_validates_judgment(self, mock_supabase, mock_auth):
        """Verify that generate_packet returns 404 for non-existent judgment."""
        from fastapi import HTTPException

        from backend.routers.enforcement import GeneratePacketRequest, generate_enforcement_packet

        # Mock empty judgment result
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = (
            []
        )

        with patch(
            "backend.routers.enforcement.get_supabase_client",
            return_value=mock_supabase,
        ):
            request = GeneratePacketRequest(
                judgment_id="999",
                strategy="wage_garnishment",
            )

            with pytest.raises(HTTPException) as exc_info:
                await generate_enforcement_packet(request, mock_auth)

            assert exc_info.value.status_code == 404


class TestJobStatusEndpoint:
    """Tests for GET /job-status/{job_id} endpoint."""

    @pytest.fixture
    def mock_auth(self):
        """Create a mock AuthContext."""
        from backend.core.security import AuthContext

        return AuthContext(subject="test-user", via="api_key")

    @pytest.mark.asyncio
    async def test_job_status_returns_pending(self, mock_auth):
        """Verify job_status returns correct pending state."""
        from backend.routers.enforcement import get_job_status

        mock_client = MagicMock()
        job_data = {
            "id": "test-job-id",
            "status": "pending",
            "payload": {"judgment_id": "123"},
            "last_error": None,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        mock_client.schema.return_value.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            job_data
        ]

        with patch(
            "backend.routers.enforcement.get_supabase_client",
            return_value=mock_client,
        ):
            response = await get_job_status("test-job-id", mock_auth)

            assert response.job_id == "test-job-id"
            assert response.status == "pending"
            assert response.packet_id is None

    @pytest.mark.asyncio
    async def test_job_status_returns_completed_with_packet(self, mock_auth):
        """Verify job_status returns packet_id when job is completed."""
        from backend.routers.enforcement import get_job_status

        mock_client = MagicMock()

        # Mock job lookup
        job_data = {
            "id": "test-job-id",
            "status": "completed",
            "payload": {"judgment_id": "123"},
            "last_error": None,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:01Z",
        }

        # First call: job_queue lookup
        mock_job_response = MagicMock()
        mock_job_response.data = [job_data]

        # Second call: draft_packets lookup
        mock_packet_response = MagicMock()
        mock_packet_response.data = [{"id": "PKT-001"}]

        mock_client.schema.return_value.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.side_effect = [
            mock_job_response,
            mock_packet_response,
        ]

        with patch(
            "backend.routers.enforcement.get_supabase_client",
            return_value=mock_client,
        ):
            response = await get_job_status("test-job-id", mock_auth)

            assert response.job_id == "test-job-id"
            assert response.status == "completed"
            assert response.packet_id == "PKT-001"

    @pytest.mark.asyncio
    async def test_job_status_returns_404_for_missing_job(self, mock_auth):
        """Verify job_status returns 404 for non-existent job."""
        from fastapi import HTTPException

        from backend.routers.enforcement import get_job_status

        mock_client = MagicMock()
        mock_client.schema.return_value.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = (
            []
        )

        with patch(
            "backend.routers.enforcement.get_supabase_client",
            return_value=mock_client,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_job_status("nonexistent-job-id", mock_auth)

            assert exc_info.value.status_code == 404


# =============================================================================
# Worker Processing Tests
# =============================================================================


class TestWorkerProcessing:
    """Tests for worker processing of enforcement_generate_packet jobs."""

    @pytest.mark.asyncio
    async def test_process_job_calls_drafting_pipeline(self):
        """Verify process_job calls run_drafting_pipeline for generate_packet jobs."""
        from unittest.mock import MagicMock

        job = {
            "id": "test-job-id",
            "job_type": "enforcement_generate_packet",
            "payload": {
                "judgment_id": "test-judgment-id",
                "strategy": "wage_garnishment",
                "case_number": "2024-CV-001234",
            },
        }

        mock_conn = MagicMock()
        mock_result = {
            "success": True,
            "run_id": "run-123",
            "plan_id": "plan-456",
            "packet_id": "PKT-789",
            "stages_completed": [],
            "duration_seconds": 1.5,
            "error_message": None,
        }

        with patch(
            "backend.workers.enforcement_engine.run_drafting_pipeline",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_pipeline:
            with patch("backend.workers.enforcement_engine.mark_job_completed") as mock_complete:
                with patch("backend.workers.enforcement_engine.log_job_event") as mock_log:
                    from backend.workers.enforcement_engine import process_job

                    await process_job(mock_conn, job)

                    # Verify pipeline was called with judgment_id
                    mock_pipeline.assert_called_once_with("test-judgment-id")

                    # Verify job was marked completed
                    mock_complete.assert_called_once()

                    # Verify log event for packet generation
                    # Should log "Packet Generated for Case {case_number}"
                    log_calls = mock_log.call_args_list
                    assert any("Packet Generated for Case" in str(call) for call in log_calls)

    @pytest.mark.asyncio
    async def test_process_job_handles_failure(self):
        """Verify process_job marks job as failed on pipeline error."""
        job = {
            "id": "test-job-id",
            "job_type": "enforcement_generate_packet",
            "payload": {
                "judgment_id": "test-judgment-id",
                "strategy": "wage_garnishment",
                "case_number": "2024-CV-001234",
            },
        }

        mock_conn = MagicMock()
        mock_result = {
            "success": False,
            "error_message": "Pipeline failed",
        }

        with patch(
            "backend.workers.enforcement_engine.run_drafting_pipeline",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            with patch("backend.workers.enforcement_engine.mark_job_failed") as mock_fail:
                with patch("backend.workers.enforcement_engine.log_job_event"):
                    from backend.workers.enforcement_engine import process_job

                    await process_job(mock_conn, job)

                    # Verify job was marked failed
                    mock_fail.assert_called_once()
