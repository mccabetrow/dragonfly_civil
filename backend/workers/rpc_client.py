"""
Dragonfly Engine - Secure RPC Client

Provides type-safe wrappers for SECURITY DEFINER RPC functions.
All database writes should go through these RPCs to enforce least-privilege security.

The underlying database grants only SELECT on tables to dragonfly_app.
All INSERT/UPDATE operations are performed via SECURITY DEFINER functions
that run with elevated privileges but with controlled inputs.

Usage:
    from backend.workers.rpc_client import RPCClient

    rpc = RPCClient(conn)
    judgment_id, is_insert = rpc.upsert_judgment(
        case_number="2024-001",
        plaintiff_name="Acme Corp",
        ...
    )
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


@dataclass
class UpsertResult:
    """Result of an upsert operation."""

    judgment_id: int | None
    is_insert: bool


@dataclass
class ClaimedJob:
    """A job claimed from the queue."""

    job_id: UUID
    job_type: str
    payload: dict[str, Any]
    attempts: int


class RPCClient:
    """
    Type-safe wrapper for SECURITY DEFINER RPC functions.

    All database writes go through these methods, ensuring:
    1. No raw INSERT/UPDATE/DELETE statements in worker code
    2. SQL injection protection via parameterized queries
    3. Audit trail via RPC function logging
    4. Consistent error handling
    """

    def __init__(self, conn: psycopg.Connection):
        """
        Initialize RPC client with a database connection.

        Args:
            conn: Active psycopg connection (will use same transaction context)
        """
        self.conn = conn

    def upsert_judgment(
        self,
        case_number: str,
        plaintiff_name: str,
        defendant_name: str,
        judgment_amount: Decimal | float,
        filing_date: date | str | None = None,
        county: str | None = None,
        collectability_score: int | None = None,
        source_file: str | None = None,
        status: str = "pending",
    ) -> UpsertResult:
        """
        Upsert a judgment record using ops.upsert_judgment RPC.

        This replaces raw INSERT INTO public.judgments statements.
        The RPC runs as SECURITY DEFINER with elevated privileges.

        Args:
            case_number: Unique case identifier
            plaintiff_name: Name of plaintiff
            defendant_name: Name of defendant
            judgment_amount: Judgment amount as Decimal
            filing_date: Optional filing/entry date
            county: Optional county name
            collectability_score: Optional score 0-100
            source_file: Optional source file reference
            status: Status (default 'pending')

        Returns:
            UpsertResult with judgment_id and is_insert flag
        """
        # Convert date to ISO string if needed
        filing_date_str = None
        if filing_date:
            if isinstance(filing_date, date):
                filing_date_str = filing_date.isoformat()
            else:
                filing_date_str = str(filing_date)

        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM ops.upsert_judgment(
                    p_case_number := %s,
                    p_plaintiff_name := %s,
                    p_defendant_name := %s,
                    p_judgment_amount := %s,
                    p_filing_date := %s::date,
                    p_county := %s,
                    p_collectability_score := %s,
                    p_source_file := %s,
                    p_status := %s
                )
                """,
                (
                    case_number,
                    plaintiff_name,
                    defendant_name,
                    float(judgment_amount) if judgment_amount else None,
                    filing_date_str,
                    county,
                    collectability_score,
                    source_file,
                    status,
                ),
            )
            row = cur.fetchone()
            self.conn.commit()

            if row:
                return UpsertResult(
                    judgment_id=row.get("judgment_id"),
                    is_insert=row.get("is_insert", True),
                )
            return UpsertResult(judgment_id=None, is_insert=True)

    def log_intake_event(
        self,
        message: str,
        level: str = "INFO",
        batch_id: str | UUID | None = None,
        job_id: str | UUID | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> UUID | None:
        """
        Log an intake event using ops.log_intake_event RPC.

        This replaces raw INSERT INTO ops.intake_logs statements.

        Args:
            message: Log message (truncated to 1000 chars)
            level: Log level (INFO, WARNING, ERROR)
            batch_id: Optional batch UUID
            job_id: Optional job UUID
            raw_payload: Optional JSON payload

        Returns:
            Log entry UUID or None if logging failed
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ops.log_intake_event(
                        p_batch_id := %s::uuid,
                        p_job_id := %s::uuid,
                        p_level := %s,
                        p_message := %s,
                        p_raw_payload := %s::jsonb
                    )
                    """,
                    (
                        str(batch_id) if batch_id else None,
                        str(job_id) if job_id else None,
                        level,
                        message[:1000],
                        json.dumps(raw_payload, default=str) if raw_payload else None,
                    ),
                )
                result = cur.fetchone()
                self.conn.commit()
                return UUID(result[0]) if result and result[0] else None
        except Exception as e:
            logger.debug(f"Failed to log intake event: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            return None

    def register_heartbeat(
        self,
        worker_id: str,
        worker_type: str,
        hostname: str | None = None,
        status: str = "running",
    ) -> str | None:
        """
        Register a worker heartbeat using ops.register_heartbeat RPC.

        This replaces raw INSERT/UPDATE on ops.worker_heartbeats.

        Args:
            worker_id: Unique worker identifier
            worker_type: Type of worker (e.g., 'ingest_processor')
            hostname: Optional hostname
            status: Worker status (running, stopped, etc.)

        Returns:
            Worker ID string or None if failed
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ops.register_heartbeat(
                        p_worker_id := %s,
                        p_worker_type := %s,
                        p_hostname := %s,
                        p_status := %s
                    )
                    """,
                    (worker_id, worker_type, hostname, status),
                )
                result = cur.fetchone()
                self.conn.commit()
                return str(result[0]) if result and result[0] else None
        except Exception as e:
            logger.debug(f"Failed to register heartbeat: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            return None

    def update_job_status(
        self,
        job_id: str | UUID,
        status: str,
        error: str | None = None,
    ) -> bool:
        """
        Update job status using ops.update_job_status RPC.

        This replaces raw UPDATE on ops.job_queue.

        Args:
            job_id: Job UUID
            status: New status (processing, completed, failed)
            error: Optional error message for failed jobs

        Returns:
            True if job was found and updated
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT ops.update_job_status(
                    p_job_id := %s::uuid,
                    p_status := %s,
                    p_error := %s
                )
                """,
                (str(job_id), status, error),
            )
            result = cur.fetchone()
            self.conn.commit()
            return result[0] if result else False

    def queue_job(
        self,
        job_type: str,
        payload: dict[str, Any] | None = None,
        priority: int = 0,
        run_at: str | None = None,
    ) -> UUID | None:
        """
        Queue a job using ops.queue_job RPC (canonical method).

        This is the preferred method for enqueuing jobs. It replaces raw
        INSERT INTO ops.job_queue statements and supports priority and
        scheduled execution.

        Args:
            job_type: Type of job (must be valid ops.job_type_enum value)
            payload: Optional JSON payload for the job
            priority: Job priority (higher = more urgent, default: 0)
            run_at: Optional ISO timestamp for delayed execution

        Returns:
            UUID of the created job, or None on failure
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ops.queue_job(
                        p_type := %s,
                        p_payload := %s::jsonb,
                        p_priority := %s,
                        p_run_at := COALESCE(%s::timestamptz, now())
                    )
                    """,
                    (job_type, json.dumps(payload or {}), priority, run_at),
                )
                result = cur.fetchone()
                self.conn.commit()
                return UUID(str(result[0])) if result and result[0] else None
        except Exception as e:
            logger.warning(f"Failed to queue job: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            return None

    def enqueue_job(
        self,
        job_type: str,
        payload: dict[str, Any] | None = None,
        status: str = "pending",
    ) -> UUID | None:
        """
        DEPRECATED: Use queue_job() instead.

        Enqueue a job using ops.enqueue_job RPC.

        This replaces raw INSERT INTO ops.job_queue statements.
        The RPC runs as SECURITY DEFINER with elevated privileges.

        Args:
            job_type: Type of job (must be valid ops.job_type_enum value)
            payload: Optional JSON payload for the job
            status: Initial status (default: 'pending')

        Returns:
            UUID of the created job, or None on failure
        """
        # Delegate to queue_job for forward compatibility
        return self.queue_job(job_type=job_type, payload=payload, priority=0)

    def claim_pending_job(
        self,
        job_types: list[str],
        lock_timeout_minutes: int = 30,
    ) -> ClaimedJob | None:
        """
        Claim a pending job using ops.claim_pending_job RPC.

        This replaces raw UPDATE ... FOR UPDATE SKIP LOCKED.

        Args:
            job_types: List of job types to claim
            lock_timeout_minutes: Lock timeout in minutes

        Returns:
            ClaimedJob if a job was claimed, None otherwise
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM ops.claim_pending_job(
                    p_job_types := %s,
                    p_lock_timeout_minutes := %s
                )
                """,
                (job_types, lock_timeout_minutes),
            )
            row = cur.fetchone()
            self.conn.commit()

            if row and row.get("job_id"):
                payload = row.get("payload") or {}
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except json.JSONDecodeError:
                        payload = {}

                return ClaimedJob(
                    job_id=row["job_id"],
                    job_type=row.get("job_type", ""),
                    payload=payload,
                    attempts=row.get("attempts", 1),
                )
            return None

    def record_outcome(
        self,
        judgment_id: str | UUID,
        outcome_type: str,
        strategy_type: str | None = None,
        strategy_reason: str | None = None,
        plan_id: str | UUID | None = None,
        packet_id: str | UUID | None = None,
        success: bool = True,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UUID | None:
        """
        Record enforcement outcome using enforcement.record_outcome RPC.

        This replaces raw INSERT into enforcement tables.

        Args:
            judgment_id: Judgment UUID
            outcome_type: Type of outcome (strategy_selected, packet_generated, etc.)
            strategy_type: Optional strategy type
            strategy_reason: Optional reason for strategy selection
            plan_id: Optional plan UUID
            packet_id: Optional packet UUID
            success: Whether the operation succeeded
            error_message: Optional error message
            metadata: Optional additional metadata

        Returns:
            Event UUID or None if failed
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT enforcement.record_outcome(
                        p_judgment_id := %s::uuid,
                        p_outcome_type := %s,
                        p_strategy_type := %s,
                        p_strategy_reason := %s,
                        p_plan_id := %s::uuid,
                        p_packet_id := %s::uuid,
                        p_success := %s,
                        p_error_message := %s,
                        p_metadata := %s::jsonb
                    )
                    """,
                    (
                        str(judgment_id),
                        outcome_type,
                        strategy_type,
                        strategy_reason,
                        str(plan_id) if plan_id else None,
                        str(packet_id) if packet_id else None,
                        success,
                        error_message,
                        json.dumps(metadata, default=str) if metadata else None,
                    ),
                )
                result = cur.fetchone()
                self.conn.commit()
                return UUID(result[0]) if result and result[0] else None
        except Exception as e:
            logger.debug(f"Failed to record outcome: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            return None

    def create_ingest_batch(
        self,
        source: str,
        file_path: str,
        file_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UUID | None:
        """
        Create an ingest batch using ops.create_ingest_batch RPC.

        This replaces raw INSERT INTO ops.ingest_batches.

        Args:
            source: Source identifier (e.g., 'simplicity', 'foil')
            file_path: Path to source file
            file_hash: Optional file hash for deduplication
            metadata: Optional metadata dict

        Returns:
            Batch UUID or None if failed
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT ops.create_ingest_batch(
                    p_source := %s,
                    p_file_path := %s,
                    p_file_hash := %s,
                    p_metadata := %s::jsonb
                )
                """,
                (
                    source,
                    file_path,
                    file_hash,
                    json.dumps(metadata, default=str) if metadata else None,
                ),
            )
            result = cur.fetchone()
            self.conn.commit()
            return UUID(result[0]) if result and result[0] else None

    def finalize_ingest_batch(
        self,
        batch_id: str | UUID,
        status: str,
        rows_processed: int = 0,
        rows_failed: int = 0,
        file_hash: str | None = None,
    ) -> bool:
        """
        Finalize an ingest batch using ops.finalize_ingest_batch RPC.

        This replaces raw UPDATE on ops.ingest_batches.

        Args:
            batch_id: Batch UUID
            status: Final status (completed, failed)
            rows_processed: Number of rows processed
            rows_failed: Number of rows that failed
            file_hash: Optional file hash

        Returns:
            True if batch was found and updated
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT ops.finalize_ingest_batch(
                    p_batch_id := %s::uuid,
                    p_status := %s,
                    p_rows_processed := %s,
                    p_rows_failed := %s,
                    p_file_hash := %s
                )
                """,
                (str(batch_id), status, rows_processed, rows_failed, file_hash),
            )
            result = cur.fetchone()
            self.conn.commit()
            return result[0] if result else False
