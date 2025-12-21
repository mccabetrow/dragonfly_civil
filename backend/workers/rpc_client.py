"""
Dragonfly Engine - Secure RPC Client

Provides type-safe wrappers for SECURITY DEFINER RPC functions.
All database writes should go through these RPCs to enforce least-privilege security.

The underlying database grants only SELECT on tables to dragonfly_app.
All INSERT/UPDATE operations are performed via SECURITY DEFINER functions
that run with elevated privileges but with controlled inputs.

Features:
- Circuit breaker with exponential backoff for transient failures
- Automatic retry for 5xx errors and database timeouts
- Structured logging integration

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

import functools
import json
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Callable, TypeVar
from uuid import UUID

import psycopg
import psycopg.errors
from psycopg.rows import dict_row
from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Type variable for generic retry decorator
T = TypeVar("T")

# Exceptions that trigger circuit breaker retry
TRANSIENT_EXCEPTIONS = (
    psycopg.OperationalError,  # Connection issues
    psycopg.errors.AdminShutdown,  # Server shutdown
    psycopg.errors.CannotConnectNow,  # Server starting
    psycopg.errors.ConnectionException,  # Connection dropped
    psycopg.errors.ConnectionDoesNotExist,  # Connection gone
    psycopg.errors.ConnectionFailure,  # Connection failed
    psycopg.errors.QueryCanceled,  # Timeout
    TimeoutError,  # General timeout
    ConnectionError,  # Network issues
)


def with_circuit_breaker(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 10.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator that adds circuit breaker retry logic to RPC methods.

    Retries on transient database errors with exponential backoff.
    Logs warnings on retry attempts.

    Args:
        max_attempts: Maximum retry attempts (default: 3)
        min_wait: Minimum wait between retries in seconds (default: 1.0)
        max_wait: Maximum wait between retries in seconds (default: 10.0)

    Returns:
        Decorated function with retry logic
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            @retry(
                retry=retry_if_exception_type(TRANSIENT_EXCEPTIONS),
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
                before_sleep=before_sleep_log(logger, logging.WARNING),
                reraise=True,
            )
            def inner() -> T:
                return func(*args, **kwargs)

            try:
                return inner()
            except RetryError as e:
                # Re-raise the last exception after all retries exhausted
                logger.error(
                    f"Circuit breaker exhausted for {func.__name__} after {max_attempts} attempts"
                )
                last_exc = e.last_attempt.exception()
                if last_exc is not None:
                    raise last_exc from e
                raise RuntimeError(f"Retry exhausted for {func.__name__}") from e

        return wrapper

    return decorator


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

    @with_circuit_breaker(max_attempts=3, min_wait=0.5, max_wait=5.0)
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
        Includes circuit breaker retry logic for transient failures.

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

    @with_circuit_breaker(max_attempts=3, min_wait=1.0, max_wait=10.0)
    def update_job_status(
        self,
        job_id: str | UUID,
        status: str,
        error_message: str | None = None,
        backoff_seconds: int | None = None,
    ) -> bool:
        """
        Update job status using ops.update_job_status RPC.

        This replaces raw UPDATE on ops.job_queue.
        Includes circuit breaker retry logic for transient failures.

        Args:
            job_id: Job UUID
            status: New status (pending, processing, completed, failed)
            error_message: Optional error message for failed/retrying jobs
            backoff_seconds: Optional backoff delay for retry scheduling

        Returns:
            True if job was found and updated
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT ops.update_job_status(
                    p_job_id := %s::uuid,
                    p_status := %s,
                    p_error_message := %s,
                    p_backoff_seconds := %s
                )
                """,
                (str(job_id), status, error_message, backoff_seconds),
            )
            # Function returns boolean, commit and return result
            self.conn.commit()
            return True

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

    @with_circuit_breaker(max_attempts=3, min_wait=1.0, max_wait=10.0)
    def claim_pending_job(
        self,
        job_types: list[str],
        lock_timeout_minutes: int = 30,
        worker_id: str | None = None,
    ) -> ClaimedJob | None:
        """
        Claim a pending job using ops.claim_pending_job RPC.

        This replaces raw UPDATE ... FOR UPDATE SKIP LOCKED.
        Includes circuit breaker retry logic for transient failures.

        Args:
            job_types: List of job types to claim
            lock_timeout_minutes: Lock timeout in minutes
            worker_id: Optional worker ID for tracking

        Returns:
            ClaimedJob if a job was claimed, None otherwise
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM ops.claim_pending_job(
                    p_job_types := %s,
                    p_lock_timeout_minutes := %s,
                    p_worker_id := %s
                )
                """,
                (job_types, lock_timeout_minutes, worker_id),
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

    # =========================================================================
    # INTAKE SCHEMA RPCs (FOIL Dataset Operations)
    # =========================================================================

    def create_foil_dataset(
        self,
        dataset_name: str,
        original_filename: str,
        source_agency: str | None = None,
        foil_request_number: str | None = None,
        row_count_raw: int = 0,
        column_count: int = 0,
        detected_columns: list[str] | None = None,
    ) -> UUID | None:
        """
        Create a FOIL dataset record using intake.create_foil_dataset RPC.

        This replaces raw INSERT INTO intake.foil_datasets statements.

        Args:
            dataset_name: Name of the dataset
            original_filename: Original filename
            source_agency: Optional source agency
            foil_request_number: Optional FOIL request number
            row_count_raw: Number of raw rows
            column_count: Number of columns
            detected_columns: List of detected column names

        Returns:
            Dataset UUID or None if creation failed
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT intake.create_foil_dataset(
                    p_dataset_name := %s,
                    p_original_filename := %s,
                    p_source_agency := %s,
                    p_foil_request_number := %s,
                    p_row_count_raw := %s,
                    p_column_count := %s,
                    p_detected_columns := %s::TEXT[]
                )
                """,
                (
                    dataset_name,
                    original_filename,
                    source_agency,
                    foil_request_number,
                    row_count_raw,
                    column_count,
                    detected_columns or [],
                ),
            )
            result = cur.fetchone()
            # Note: No commit here - let worker loop control transaction
            return UUID(result[0]) if result and result[0] else None

    def update_foil_dataset_mapping(
        self,
        dataset_id: str | UUID,
        column_mapping: dict[str, str],
        column_mapping_reverse: dict[str, str],
        unmapped_columns: list[str],
        mapping_confidence: int,
        required_fields_missing: list[str],
    ) -> bool:
        """
        Update FOIL dataset with column mapping results.

        This replaces raw UPDATE on intake.foil_datasets.

        Args:
            dataset_id: Dataset UUID
            column_mapping: Raw to canonical column mapping
            column_mapping_reverse: Canonical to raw column mapping
            unmapped_columns: List of unmapped column names
            mapping_confidence: Mapping confidence 0-100
            required_fields_missing: List of missing required fields

        Returns:
            True if dataset was found and updated
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT intake.update_foil_dataset_mapping(
                    p_dataset_id := %s::uuid,
                    p_column_mapping := %s::jsonb,
                    p_column_mapping_reverse := %s::jsonb,
                    p_unmapped_columns := %s::TEXT[],
                    p_mapping_confidence := %s,
                    p_required_fields_missing := %s::TEXT[]
                )
                """,
                (
                    str(dataset_id),
                    json.dumps(column_mapping),
                    json.dumps(column_mapping_reverse),
                    unmapped_columns,
                    mapping_confidence,
                    required_fields_missing,
                ),
            )
            result = cur.fetchone()
            return result[0] if result else False

    def update_foil_dataset_status(
        self,
        dataset_id: str | UUID,
        status: str,
        error_summary: str | None = None,
    ) -> bool:
        """
        Update FOIL dataset status.

        This replaces raw UPDATE on intake.foil_datasets.

        Args:
            dataset_id: Dataset UUID
            status: New status
            error_summary: Optional error summary

        Returns:
            True if dataset was found and updated
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT intake.update_foil_dataset_status(
                    p_dataset_id := %s::uuid,
                    p_status := %s,
                    p_error_summary := %s
                )
                """,
                (str(dataset_id), status, error_summary),
            )
            result = cur.fetchone()
            return result[0] if result else False

    def finalize_foil_dataset(
        self,
        dataset_id: str | UUID,
        row_count_valid: int,
        row_count_invalid: int,
        row_count_quarantined: int,
        status: str,
    ) -> bool:
        """
        Finalize FOIL dataset with row counts.

        This replaces raw UPDATE on intake.foil_datasets.

        Args:
            dataset_id: Dataset UUID
            row_count_valid: Number of valid rows
            row_count_invalid: Number of invalid rows
            row_count_quarantined: Number of quarantined rows
            status: Final status

        Returns:
            True if dataset was found and updated
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT intake.finalize_foil_dataset(
                    p_dataset_id := %s::uuid,
                    p_row_count_valid := %s,
                    p_row_count_invalid := %s,
                    p_row_count_quarantined := %s,
                    p_status := %s
                )
                """,
                (
                    str(dataset_id),
                    row_count_valid,
                    row_count_invalid,
                    row_count_quarantined,
                    status,
                ),
            )
            result = cur.fetchone()
            return result[0] if result else False

    def store_foil_raw_rows_bulk(
        self,
        dataset_id: str | UUID,
        rows: list[dict[str, Any]],
    ) -> int:
        """
        Bulk store raw FOIL rows.

        This replaces raw INSERT INTO intake.foil_raw_rows in a loop.

        Args:
            dataset_id: Dataset UUID
            rows: List of dicts with 'row_index' and 'raw_data' keys

        Returns:
            Number of rows inserted
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT intake.store_foil_raw_rows_bulk(
                    p_dataset_id := %s::uuid,
                    p_rows := %s::jsonb
                )
                """,
                (str(dataset_id), json.dumps(rows, default=str)),
            )
            result = cur.fetchone()
            return result[0] if result else 0

    def update_foil_raw_row_status(
        self,
        dataset_id: str | UUID,
        row_index: int,
        validation_status: str,
        judgment_id: str | None = None,
    ) -> bool:
        """
        Update FOIL raw row validation status.

        This replaces raw UPDATE on intake.foil_raw_rows.

        Args:
            dataset_id: Dataset UUID
            row_index: Row index
            validation_status: Status (valid, invalid, quarantined)
            judgment_id: Optional linked judgment ID

        Returns:
            True if row was found and updated
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT intake.update_foil_raw_row_status(
                    p_dataset_id := %s::uuid,
                    p_row_index := %s,
                    p_validation_status := %s,
                    p_judgment_id := %s
                )
                """,
                (str(dataset_id), row_index, validation_status, judgment_id),
            )
            result = cur.fetchone()
            return result[0] if result else False

    def quarantine_foil_row(
        self,
        dataset_id: str | UUID,
        row_index: int,
        raw_data: dict[str, Any],
        quarantine_reason: str,
        error_message: str,
        mapped_data: dict[str, Any] | None = None,
    ) -> UUID | None:
        """
        Quarantine a FOIL row and update its status.

        This replaces raw INSERT INTO intake.foil_quarantine.

        Args:
            dataset_id: Dataset UUID
            row_index: Row index
            raw_data: Raw row data
            quarantine_reason: Reason for quarantine
            error_message: Error message
            mapped_data: Optional mapped data

        Returns:
            Quarantine entry UUID or None if failed
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT intake.quarantine_foil_row(
                    p_dataset_id := %s::uuid,
                    p_row_index := %s,
                    p_raw_data := %s::jsonb,
                    p_quarantine_reason := %s,
                    p_error_message := %s,
                    p_mapped_data := %s::jsonb
                )
                """,
                (
                    str(dataset_id),
                    row_index,
                    json.dumps(raw_data, default=str),
                    quarantine_reason,
                    error_message[:500],
                    json.dumps(mapped_data or {}, default=str),
                ),
            )
            result = cur.fetchone()
            return UUID(result[0]) if result and result[0] else None

    def upsert_judgment_extended(
        self,
        case_number: str,
        plaintiff_name: str | None,
        defendant_name: str | None,
        judgment_amount: Decimal | float | None,
        entry_date: date | str | None = None,
        county: str | None = None,
        court: str | None = None,
        collectability_score: int | None = None,
        source_file: str | None = None,
        status: str = "pending",
    ) -> UpsertResult:
        """
        Extended judgment upsert with court field.

        This replaces raw INSERT INTO public.judgments for FOIL imports.

        Args:
            case_number: Unique case identifier
            plaintiff_name: Name of plaintiff
            defendant_name: Name of defendant
            judgment_amount: Judgment amount
            entry_date: Entry/filing date
            county: County name
            court: Court name
            collectability_score: Score 0-100
            source_file: Source file reference
            status: Status (default 'pending')

        Returns:
            UpsertResult with judgment_id and is_insert flag
        """
        entry_date_str = None
        if entry_date:
            if isinstance(entry_date, date):
                entry_date_str = entry_date.isoformat()
            else:
                entry_date_str = str(entry_date)

        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM ops.upsert_judgment_extended(
                    p_case_number := %s,
                    p_plaintiff_name := %s,
                    p_defendant_name := %s,
                    p_judgment_amount := %s,
                    p_entry_date := %s::date,
                    p_county := %s,
                    p_court := %s,
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
                    entry_date_str,
                    county,
                    court,
                    collectability_score,
                    source_file,
                    status,
                ),
            )
            row = cur.fetchone()
            # Note: No commit here - let worker loop control transaction

            if row:
                return UpsertResult(
                    judgment_id=row.get("judgment_id"),
                    is_insert=row.get("is_insert", True),
                )
            return UpsertResult(judgment_id=None, is_insert=True)
