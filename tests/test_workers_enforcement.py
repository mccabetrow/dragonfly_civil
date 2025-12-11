"""
Unit and integration tests for the Enforcement Engine Worker.

Tests cover:
- Job claiming with FOR UPDATE SKIP LOCKED
- Job completion and failure marking
- Pipeline dispatch to Orchestrator
- Logging to ops.intake_logs
- Error handling for missing payload fields

Mocking Strategy:
- Orchestrator is mocked to avoid real LLM calls
- Database operations use psycopg with real dev database
- Tests are parameterized for both job types
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Generator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

pytestmark = pytest.mark.integration


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def db_url() -> str:
    """Get database URL from environment."""
    from src.supabase_client import get_supabase_db_url

    return get_supabase_db_url()


@pytest.fixture
def conn(db_url: str) -> Generator[psycopg.Connection, None, None]:
    """Provide a database connection, rolled back after each test."""
    with psycopg.connect(db_url, row_factory=dict_row) as connection:
        yield connection
        # Rollback any uncommitted changes
        try:
            connection.rollback()
        except Exception:
            pass


@pytest.fixture
def test_judgment_id() -> str:
    """Generate a test judgment ID."""
    return str(uuid4())


@pytest.fixture
def test_job_id() -> str:
    """Generate a test job ID."""
    return str(uuid4())


# =============================================================================
# Mock Orchestrator Output
# =============================================================================


def _make_mock_output(
    judgment_id: str,
    success: bool = True,
    plan_id: str | None = None,
    packet_id: str | None = None,
    error_message: str | None = None,
) -> MagicMock:
    """Create a mock OrchestratorOutput."""
    from backend.agents.models import PipelineStage

    mock = MagicMock()
    mock.success = success
    mock.run_id = f"run_{uuid4().hex[:12]}"
    mock.persisted_plan_id = plan_id or str(uuid4())
    mock.persisted_packet_id = packet_id
    mock.stages_completed = [
        PipelineStage.EXTRACTOR,
        PipelineStage.NORMALIZER,
        PipelineStage.REASONER,
        PipelineStage.STRATEGIST,
    ]
    mock.duration_seconds = 1.5
    mock.error_message = error_message
    return mock


# =============================================================================
# Unit Tests - Module Functions
# =============================================================================


class TestJobQueueOperations:
    """Test job queue claim/mark operations."""

    def test_claim_pending_job_returns_none_when_empty(self, conn: psycopg.Connection) -> None:
        """claim_pending_job returns None when no pending enforcement jobs exist."""
        from backend.workers.enforcement_engine import claim_pending_job

        # Create a job with a different type
        job_id = str(uuid4())
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.job_queue (id, job_type, status, payload, created_at)
                VALUES (%s, 'ingest_csv', 'pending', '{}', now())
                """,
                (job_id,),
            )
            conn.commit()

        try:
            # Should not claim ingest_csv jobs
            result = claim_pending_job(conn)
            assert result is None
        finally:
            # Cleanup
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                conn.commit()

    def test_claim_pending_job_claims_strategy_job(self, conn: psycopg.Connection) -> None:
        """claim_pending_job successfully claims enforcement_strategy jobs."""
        from backend.workers.enforcement_engine import claim_pending_job

        job_id = str(uuid4())
        judgment_id = str(uuid4())
        payload = json.dumps({"judgment_id": judgment_id})

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.job_queue (id, job_type, status, payload, created_at)
                VALUES (%s, 'enforcement_strategy', 'pending', %s, now())
                """,
                (job_id, payload),
            )
            conn.commit()

        try:
            result = claim_pending_job(conn)
            assert result is not None
            assert str(result["id"]) == job_id
            assert str(result["job_type"]) == "enforcement_strategy"
            assert str(result["status"]) == "processing"
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                conn.commit()

    def test_claim_pending_job_claims_drafting_job(self, conn: psycopg.Connection) -> None:
        """claim_pending_job successfully claims enforcement_drafting jobs."""
        from backend.workers.enforcement_engine import claim_pending_job

        job_id = str(uuid4())
        judgment_id = str(uuid4())
        payload = json.dumps({"judgment_id": judgment_id, "plan_id": str(uuid4())})

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.job_queue (id, job_type, status, payload, created_at)
                VALUES (%s, 'enforcement_drafting', 'pending', %s, now())
                """,
                (job_id, payload),
            )
            conn.commit()

        try:
            result = claim_pending_job(conn)
            assert result is not None
            assert str(result["id"]) == job_id
            assert str(result["job_type"]) == "enforcement_drafting"
            assert str(result["status"]) == "processing"
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                conn.commit()

    def test_mark_job_completed(self, conn: psycopg.Connection) -> None:
        """mark_job_completed sets status to 'completed'."""
        from backend.workers.enforcement_engine import mark_job_completed

        job_id = str(uuid4())
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.job_queue (id, job_type, status, payload, created_at)
                VALUES (%s, 'enforcement_strategy', 'processing', '{}', now())
                """,
                (job_id,),
            )
            conn.commit()

        try:
            mark_job_completed(conn, job_id)

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM ops.job_queue WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert str(row["status"]) == "completed"
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                conn.commit()

    def test_mark_job_failed(self, conn: psycopg.Connection) -> None:
        """mark_job_failed sets status to 'failed' with error message."""
        from backend.workers.enforcement_engine import mark_job_failed

        job_id = str(uuid4())
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.job_queue (id, job_type, status, payload, created_at)
                VALUES (%s, 'enforcement_strategy', 'processing', '{}', now())
                """,
                (job_id,),
            )
            conn.commit()

        try:
            mark_job_failed(conn, job_id, "Test error message")

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, last_error FROM ops.job_queue WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert str(row["status"]) == "failed"
                assert row["last_error"] == "Test error message"
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                conn.commit()


class TestLogging:
    """Test ops.intake_logs observability."""

    def test_log_job_event_writes_to_intake_logs(self, conn: psycopg.Connection) -> None:
        """log_job_event successfully writes to ops.intake_logs."""
        from backend.workers.enforcement_engine import log_job_event

        job_id = str(uuid4())
        message = f"Test log message {uuid4().hex[:8]}"

        try:
            log_job_event(conn, job_id, "INFO", message, {"test": "payload"})

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM ops.intake_logs WHERE job_id = %s::uuid AND message = %s",
                    (job_id, message),
                )
                row = cur.fetchone()
                assert row is not None
                assert row["level"] == "INFO"
                assert row["message"] == message
                assert row["raw_payload"]["test"] == "payload"
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.intake_logs WHERE job_id = %s::uuid", (job_id,))
                conn.commit()

    def test_log_job_event_truncates_long_messages(self, conn: psycopg.Connection) -> None:
        """log_job_event truncates messages longer than 1000 chars."""
        from backend.workers.enforcement_engine import log_job_event

        job_id = str(uuid4())
        long_message = "x" * 2000

        try:
            log_job_event(conn, job_id, "ERROR", long_message)

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT message FROM ops.intake_logs WHERE job_id = %s::uuid",
                    (job_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert len(row["message"]) == 1000
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.intake_logs WHERE job_id = %s::uuid", (job_id,))
                conn.commit()


# =============================================================================
# Integration Tests - Pipeline Dispatch
# =============================================================================


class TestPipelineDispatch:
    """Test pipeline dispatch to Orchestrator."""

    @pytest.mark.asyncio
    async def test_run_strategy_pipeline_calls_orchestrator(self, test_judgment_id: str) -> None:
        """run_strategy_pipeline calls Orchestrator.run_strategy_only."""
        from backend.workers.enforcement_engine import run_strategy_pipeline

        mock_output = _make_mock_output(test_judgment_id, success=True)

        with patch("backend.agents.orchestrator.Orchestrator") as MockOrch:
            mock_instance = MockOrch.return_value
            mock_instance.run_strategy_only = AsyncMock(return_value=mock_output)

            result = await run_strategy_pipeline(test_judgment_id)

            mock_instance.run_strategy_only.assert_called_once_with(test_judgment_id)
            assert result["success"] is True
            assert result["plan_id"] is not None

    @pytest.mark.asyncio
    async def test_run_drafting_pipeline_calls_orchestrator(self, test_judgment_id: str) -> None:
        """run_drafting_pipeline calls Orchestrator.run_full."""
        from backend.workers.enforcement_engine import run_drafting_pipeline

        mock_output = _make_mock_output(test_judgment_id, success=True, packet_id=str(uuid4()))

        with patch("backend.agents.orchestrator.Orchestrator") as MockOrch:
            mock_instance = MockOrch.return_value
            mock_instance.run_full = AsyncMock(return_value=mock_output)

            result = await run_drafting_pipeline(test_judgment_id, plan_id="some-plan")

            mock_instance.run_full.assert_called_once_with(test_judgment_id)
            assert result["success"] is True
            assert result["packet_id"] is not None

    @pytest.mark.asyncio
    async def test_run_strategy_pipeline_handles_failure(self, test_judgment_id: str) -> None:
        """run_strategy_pipeline handles pipeline failure gracefully."""
        from backend.workers.enforcement_engine import run_strategy_pipeline

        mock_output = _make_mock_output(
            test_judgment_id, success=False, error_message="Strategist failed"
        )

        with patch("backend.agents.orchestrator.Orchestrator") as MockOrch:
            mock_instance = MockOrch.return_value
            mock_instance.run_strategy_only = AsyncMock(return_value=mock_output)

            result = await run_strategy_pipeline(test_judgment_id)

            assert result["success"] is False
            assert result["error_message"] == "Strategist failed"


class TestProcessJob:
    """Test full job processing flow."""

    @pytest.mark.asyncio
    async def test_process_job_strategy_success(self, conn: psycopg.Connection) -> None:
        """process_job completes strategy job on success."""
        from backend.workers.enforcement_engine import process_job

        job_id = str(uuid4())
        judgment_id = str(uuid4())
        payload = {"judgment_id": judgment_id}

        job = {
            "id": job_id,
            "job_type": "enforcement_strategy",
            "payload": payload,
        }

        mock_output = _make_mock_output(judgment_id, success=True)

        with patch("backend.agents.orchestrator.Orchestrator") as MockOrch:
            mock_instance = MockOrch.return_value
            mock_instance.run_strategy_only = AsyncMock(return_value=mock_output)

            # Insert a job to update
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ops.job_queue (id, job_type, status, payload, created_at)
                    VALUES (%s, 'enforcement_strategy', 'processing', %s, now())
                    """,
                    (job_id, json.dumps(payload)),
                )
                conn.commit()

            try:
                await process_job(conn, job)

                # Verify job marked completed
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT status FROM ops.job_queue WHERE id = %s",
                        (job_id,),
                    )
                    row = cur.fetchone()
                    assert row is not None
                    assert str(row["status"]) == "completed"
            finally:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                    cur.execute("DELETE FROM ops.intake_logs WHERE job_id = %s", (job_id,))
                    conn.commit()

    @pytest.mark.asyncio
    async def test_process_job_missing_judgment_id(self, conn: psycopg.Connection) -> None:
        """process_job fails when judgment_id is missing from payload."""
        from backend.workers.enforcement_engine import process_job

        job_id = str(uuid4())
        job = {
            "id": job_id,
            "job_type": "enforcement_strategy",
            "payload": {},  # Missing judgment_id
        }

        # Insert a job to update
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.job_queue (id, job_type, status, payload, created_at)
                VALUES (%s, 'enforcement_strategy', 'processing', '{}', now())
                """,
                (job_id,),
            )
            conn.commit()

        try:
            await process_job(conn, job)

            # Verify job marked failed
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, last_error FROM ops.job_queue WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert str(row["status"]) == "failed"
                assert "judgment_id" in row["last_error"]
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                cur.execute("DELETE FROM ops.intake_logs WHERE job_id = %s", (job_id,))
                conn.commit()

    @pytest.mark.asyncio
    async def test_process_job_drafting_success(self, conn: psycopg.Connection) -> None:
        """process_job completes drafting job on success."""
        from backend.workers.enforcement_engine import process_job

        job_id = str(uuid4())
        judgment_id = str(uuid4())
        plan_id = str(uuid4())
        payload = {"judgment_id": judgment_id, "plan_id": plan_id}

        job = {
            "id": job_id,
            "job_type": "enforcement_drafting",
            "payload": payload,
        }

        mock_output = _make_mock_output(judgment_id, success=True, packet_id=str(uuid4()))

        with patch("backend.agents.orchestrator.Orchestrator") as MockOrch:
            mock_instance = MockOrch.return_value
            mock_instance.run_full = AsyncMock(return_value=mock_output)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ops.job_queue (id, job_type, status, payload, created_at)
                    VALUES (%s, 'enforcement_drafting', 'processing', %s, now())
                    """,
                    (job_id, json.dumps(payload)),
                )
                conn.commit()

            try:
                await process_job(conn, job)

                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT status FROM ops.job_queue WHERE id = %s",
                        (job_id,),
                    )
                    row = cur.fetchone()
                    assert row is not None
                    assert str(row["status"]) == "completed"
            finally:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                    cur.execute("DELETE FROM ops.intake_logs WHERE job_id = %s", (job_id,))
                    conn.commit()

    @pytest.mark.asyncio
    async def test_process_job_handles_orchestrator_exception(
        self, conn: psycopg.Connection
    ) -> None:
        """process_job handles Orchestrator exceptions gracefully."""
        from backend.workers.enforcement_engine import process_job

        job_id = str(uuid4())
        judgment_id = str(uuid4())
        payload = {"judgment_id": judgment_id}

        job = {
            "id": job_id,
            "job_type": "enforcement_strategy",
            "payload": payload,
        }

        with patch("backend.agents.orchestrator.Orchestrator") as MockOrch:
            mock_instance = MockOrch.return_value
            mock_instance.run_strategy_only = AsyncMock(
                side_effect=RuntimeError("LLM service unavailable")
            )

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ops.job_queue (id, job_type, status, payload, created_at)
                    VALUES (%s, 'enforcement_strategy', 'processing', %s, now())
                    """,
                    (job_id, json.dumps(payload)),
                )
                conn.commit()

            try:
                await process_job(conn, job)

                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT status, last_error FROM ops.job_queue WHERE id = %s",
                        (job_id,),
                    )
                    row = cur.fetchone()
                    assert row is not None
                    assert str(row["status"]) == "failed"
                    assert "LLM service unavailable" in row["last_error"]
            finally:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                    cur.execute("DELETE FROM ops.intake_logs WHERE job_id = %s", (job_id,))
                    conn.commit()


# =============================================================================
# Integration Tests - run_once
# =============================================================================


class TestRunOnce:
    """Test run_once worker cycle."""

    def test_run_once_returns_false_when_no_jobs(self, conn: psycopg.Connection) -> None:
        """run_once returns False when no jobs are available."""
        from backend.workers.enforcement_engine import run_once

        # Ensure no enforcement jobs exist
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM ops.job_queue
                WHERE job_type::text IN ('enforcement_strategy', 'enforcement_drafting')
                  AND status::text = 'pending'
                """
            )
            conn.commit()

        result = run_once(conn)
        assert result is False

    def test_run_once_processes_pending_job(self, conn: psycopg.Connection) -> None:
        """run_once claims and processes a pending job."""
        from backend.workers.enforcement_engine import run_once

        job_id = str(uuid4())
        judgment_id = str(uuid4())
        payload = json.dumps({"judgment_id": judgment_id})

        mock_output = _make_mock_output(judgment_id, success=True)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.job_queue (id, job_type, status, payload, created_at)
                VALUES (%s, 'enforcement_strategy', 'pending', %s, now())
                """,
                (job_id, payload),
            )
            conn.commit()

        try:
            with patch("backend.agents.orchestrator.Orchestrator") as MockOrch:
                mock_instance = MockOrch.return_value
                mock_instance.run_strategy_only = AsyncMock(return_value=mock_output)

                result = run_once(conn)

                assert result is True

            # Verify job was processed
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM ops.job_queue WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert str(row["status"]) == "completed"
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                cur.execute("DELETE FROM ops.intake_logs WHERE job_id = %s", (job_id,))
                conn.commit()


# =============================================================================
# Schema Validation Tests
# =============================================================================


class TestSchemaRequirements:
    """Validate required database schema exists."""

    def test_job_queue_has_enforcement_job_types(self, conn: psycopg.Connection) -> None:
        """ops.job_type_enum includes enforcement job types."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT enumlabel
                FROM pg_enum
                WHERE enumtypid = 'ops.job_type_enum'::regtype
                """
            )
            labels = {row["enumlabel"] for row in cur.fetchall()}

        assert "enforcement_strategy" in labels
        assert "enforcement_drafting" in labels

    def test_intake_logs_table_exists(self, conn: psycopg.Connection) -> None:
        """ops.intake_logs table exists with required columns."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'ops' AND table_name = 'intake_logs'
                """
            )
            columns = {row["column_name"] for row in cur.fetchall()}

        assert "id" in columns
        assert "job_id" in columns
        assert "level" in columns
        assert "message" in columns
        assert "raw_payload" in columns
        assert "created_at" in columns

    def test_enforcement_activity_view_exists(self, conn: psycopg.Connection) -> None:
        """analytics.v_enforcement_activity view exists."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) as cnt
                FROM information_schema.views
                WHERE table_schema = 'analytics' AND table_name = 'v_enforcement_activity'
                """
            )
            row = cur.fetchone()
            assert row is not None
            assert row["cnt"] == 1

    def test_enforcement_activity_rpc_exists(self, conn: psycopg.Connection) -> None:
        """public.enforcement_activity_metrics() RPC function exists."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) as cnt
                FROM information_schema.routines
                WHERE routine_schema = 'public'
                  AND routine_name = 'enforcement_activity_metrics'
                """
            )
            row = cur.fetchone()
            assert row is not None
            assert row["cnt"] == 1
