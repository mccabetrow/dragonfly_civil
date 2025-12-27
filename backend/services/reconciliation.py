"""
Dragonfly Engine - Data Reconciliation Service

Provides data integrity verification and reconciliation capabilities:
- Batch verification (CSV row count vs DB row count)
- Integrity scoring
- Discrepancy management (Dead Letter Queue)
- Audit log queries

Usage:
    from backend.services.reconciliation import ReconciliationService

    service = ReconciliationService(conn)
    result = service.verify_batch(batch_id)
    print(result.integrity_score)  # 99.999%
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS & DATA CLASSES
# =============================================================================


class RowStage(str, Enum):
    """Lifecycle stages for ingested rows."""

    RECEIVED = "received"
    PARSED = "parsed"
    VALIDATED = "validated"
    STORED = "stored"
    FAILED = "failed"


class ErrorType(str, Enum):
    """Types of data discrepancies."""

    PARSE_ERROR = "parse_error"
    VALIDATION_ERROR = "validation_error"
    TRANSFORM_ERROR = "transform_error"
    SCHEMA_MISMATCH = "schema_mismatch"
    DB_ERROR = "db_error"
    DUPLICATE = "duplicate"
    CONSTRAINT_ERROR = "constraint_error"
    UNKNOWN = "unknown"


class DiscrepancyStatus(str, Enum):
    """Resolution status for discrepancies."""

    PENDING = "pending"
    REVIEWING = "reviewing"
    RETRYING = "retrying"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


@dataclass
class BatchVerificationResult:
    """Result of batch verification."""

    batch_id: str
    csv_row_count: int
    db_row_count: int
    failed_row_count: int
    integrity_score: float
    is_complete: bool
    discrepancies: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "unknown"
    verified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_perfect(self) -> bool:
        """Check if batch has 100% integrity."""
        return self.csv_row_count == self.db_row_count and self.failed_row_count == 0


@dataclass
class IntegrityDashboard:
    """Integrity dashboard metrics."""

    total_rows_received: int
    total_rows_stored: int
    total_rows_failed: int
    total_batches: int
    integrity_score: float
    pending_discrepancies: int
    resolved_discrepancies: int
    rows_received_24h: int
    rows_stored_24h: int
    batches_pending: int
    batches_processing: int
    computed_at: datetime


@dataclass
class AuditLogEntry:
    """Single audit log entry."""

    id: str
    batch_id: str
    row_index: int
    stage: RowStage
    raw_data: Optional[Dict[str, Any]]
    parsed_data: Optional[Dict[str, Any]]
    judgment_id: Optional[str]
    case_number: Optional[str]
    error_stage: Optional[str]
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: datetime


@dataclass
class Discrepancy:
    """Data discrepancy (failed row) from Dead Letter Queue."""

    id: str
    batch_id: str
    row_index: int
    source_file: Optional[str]
    raw_data: Dict[str, Any]
    error_type: ErrorType
    error_code: Optional[str]
    error_message: str
    error_details: Optional[Dict[str, Any]]
    status: DiscrepancyStatus
    retry_count: int
    resolved_at: Optional[datetime]
    resolved_by: Optional[str]
    created_at: datetime


# =============================================================================
# RECONCILIATION SERVICE
# =============================================================================


class ReconciliationService:
    """
    Data Reconciliation Service

    Provides:
    - Batch verification (verify_batch)
    - Integrity dashboard metrics (get_dashboard)
    - Audit log management (log_row_*, get_audit_log)
    - Discrepancy management (create_discrepancy, update_discrepancy, retry_discrepancy)
    """

    def __init__(self, conn: psycopg.Connection):
        """Initialize with database connection."""
        self.conn = conn

    # =========================================================================
    # BATCH VERIFICATION
    # =========================================================================

    def verify_batch(self, batch_id: str) -> BatchVerificationResult:
        """
        Verify a batch by comparing CSV row count vs DB row count.

        This is the core reconciliation function that proves data integrity.

        Args:
            batch_id: UUID of the ingest batch to verify

        Returns:
            BatchVerificationResult with integrity metrics
        """
        logger.info(f"[Reconciliation] Verifying batch {batch_id}")

        with self.conn.cursor(row_factory=dict_row) as cur:
            # Get batch metadata
            cur.execute(
                """
                SELECT
                    id,
                    row_count_raw,
                    row_count_valid,
                    row_count_invalid,
                    status
                FROM ops.ingest_batches
                WHERE id = %s::uuid
                """,
                (batch_id,),
            )
            batch = cur.fetchone()

            if not batch:
                raise ValueError(f"Batch {batch_id} not found")

            # Count actual rows in judgments table for this batch
            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM public.judgments
                WHERE source_file = %s
                """,
                (f"batch:{batch_id}",),
            )
            db_result = cur.fetchone()
            db_row_count = db_result["count"] if db_result else 0

            # Get discrepancies for this batch
            cur.execute(
                """
                SELECT
                    id::text,
                    row_index,
                    error_type,
                    error_message,
                    status,
                    raw_data
                FROM ops.data_discrepancies
                WHERE batch_id = %s::uuid
                ORDER BY row_index
                """,
                (batch_id,),
            )
            discrepancies = [dict(row) for row in cur.fetchall()]

        csv_row_count = batch["row_count_raw"]
        failed_row_count = batch["row_count_invalid"]

        # Calculate integrity score
        if csv_row_count > 0:
            integrity_score = (db_row_count / csv_row_count) * 100
        else:
            integrity_score = 100.0

        # Determine if batch is complete
        is_complete = batch["status"] in ("completed", "failed")

        result = BatchVerificationResult(
            batch_id=batch_id,
            csv_row_count=csv_row_count,
            db_row_count=db_row_count,
            failed_row_count=failed_row_count,
            integrity_score=round(integrity_score, 3),
            is_complete=is_complete,
            discrepancies=discrepancies,
            status=batch["status"],
        )

        logger.info(
            f"[Reconciliation] Batch {batch_id}: "
            f"CSV={csv_row_count}, DB={db_row_count}, "
            f"Failed={failed_row_count}, Score={integrity_score:.3f}%"
        )

        return result

    # =========================================================================
    # INTEGRITY DASHBOARD
    # =========================================================================

    def get_dashboard(self) -> IntegrityDashboard:
        """
        Get integrity dashboard metrics.

        Returns:
            IntegrityDashboard with all vault status metrics
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM ops.v_integrity_dashboard")
            row = cur.fetchone()

        if not row:
            # Return empty dashboard if view returns no rows
            return IntegrityDashboard(
                total_rows_received=0,
                total_rows_stored=0,
                total_rows_failed=0,
                total_batches=0,
                integrity_score=100.0,
                pending_discrepancies=0,
                resolved_discrepancies=0,
                rows_received_24h=0,
                rows_stored_24h=0,
                batches_pending=0,
                batches_processing=0,
                computed_at=datetime.now(timezone.utc),
            )

        return IntegrityDashboard(
            total_rows_received=row["total_rows_received"],
            total_rows_stored=row["total_rows_stored"],
            total_rows_failed=row["total_rows_failed"],
            total_batches=row["total_batches"],
            integrity_score=float(row["integrity_score"]),
            pending_discrepancies=row["pending_discrepancies"],
            resolved_discrepancies=row["resolved_discrepancies"],
            rows_received_24h=row["rows_received_24h"],
            rows_stored_24h=row["rows_stored_24h"],
            batches_pending=row["batches_pending"],
            batches_processing=row["batches_processing"],
            computed_at=row["computed_at"],
        )

    # =========================================================================
    # AUDIT LOG OPERATIONS
    # =========================================================================

    def log_row_received(
        self,
        batch_id: str,
        row_index: int,
        raw_data: Dict[str, Any],
    ) -> str:
        """
        Log that a row was received from CSV.

        Args:
            batch_id: Batch UUID
            row_index: Row number in CSV
            raw_data: Original row data

        Returns:
            Audit log entry ID
        """
        raw_checksum = self._compute_checksum(raw_data)
        entry_id = str(uuid4())

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.ingest_audit_log (
                    id, batch_id, row_index, stage,
                    received_at, raw_data, raw_checksum
                ) VALUES (
                    %s::uuid, %s::uuid, %s, 'received',
                    now(), %s, %s
                )
                ON CONFLICT (batch_id, row_index) DO UPDATE SET
                    stage = 'received',
                    received_at = now(),
                    raw_data = EXCLUDED.raw_data,
                    raw_checksum = EXCLUDED.raw_checksum
                RETURNING id::text
                """,
                (entry_id, batch_id, row_index, json.dumps(raw_data, default=str), raw_checksum),
            )
            result = cur.fetchone()
            self.conn.commit()

        return result[0] if result else entry_id

    def log_row_parsed(
        self,
        batch_id: str,
        row_index: int,
        parsed_data: Dict[str, Any],
        case_number: Optional[str] = None,
    ) -> None:
        """Log that a row was successfully parsed."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ops.ingest_audit_log
                SET stage = 'parsed',
                    parsed_at = now(),
                    parsed_data = %s,
                    case_number = %s
                WHERE batch_id = %s::uuid AND row_index = %s
                """,
                (json.dumps(parsed_data, default=str), case_number, batch_id, row_index),
            )
            self.conn.commit()

    def log_row_validated(self, batch_id: str, row_index: int) -> None:
        """Log that a row passed validation."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ops.ingest_audit_log
                SET stage = 'validated',
                    validated_at = now()
                WHERE batch_id = %s::uuid AND row_index = %s
                """,
                (batch_id, row_index),
            )
            self.conn.commit()

    def log_row_stored(
        self,
        batch_id: str,
        row_index: int,
        judgment_id: Optional[str] = None,
    ) -> None:
        """Log that a row was successfully stored in the database."""
        with self.conn.cursor() as cur:
            if judgment_id:
                cur.execute(
                    """
                    UPDATE ops.ingest_audit_log
                    SET stage = 'stored',
                        stored_at = now(),
                        judgment_id = %s::uuid
                    WHERE batch_id = %s::uuid AND row_index = %s
                    """,
                    (judgment_id, batch_id, row_index),
                )
            else:
                cur.execute(
                    """
                    UPDATE ops.ingest_audit_log
                    SET stage = 'stored',
                        stored_at = now()
                    WHERE batch_id = %s::uuid AND row_index = %s
                    """,
                    (batch_id, row_index),
                )
            self.conn.commit()

    def log_row_failed(
        self,
        batch_id: str,
        row_index: int,
        error_stage: str,
        error_code: str,
        error_message: str,
    ) -> None:
        """Log that a row failed at some stage."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ops.ingest_audit_log
                SET stage = 'failed',
                    error_stage = %s,
                    error_code = %s,
                    error_message = %s
                WHERE batch_id = %s::uuid AND row_index = %s
                """,
                (error_stage, error_code, error_message[:1000], batch_id, row_index),
            )
            self.conn.commit()

    def get_audit_log(
        self,
        batch_id: str,
        stage: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditLogEntry]:
        """Get audit log entries for a batch."""
        query = """
            SELECT
                id::text,
                batch_id::text,
                row_index,
                stage,
                raw_data,
                parsed_data,
                judgment_id::text,
                case_number,
                error_stage,
                error_code,
                error_message,
                created_at
            FROM ops.ingest_audit_log
            WHERE batch_id = %s::uuid
        """
        params: List[Any] = [batch_id]

        if stage:
            query += " AND stage = %s"
            params.append(stage)

        query += " ORDER BY row_index LIMIT %s"
        params.append(limit)

        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        return [
            AuditLogEntry(
                id=row["id"],
                batch_id=row["batch_id"],
                row_index=row["row_index"],
                stage=RowStage(row["stage"]),
                raw_data=row["raw_data"],
                parsed_data=row["parsed_data"],
                judgment_id=row["judgment_id"],
                case_number=row["case_number"],
                error_stage=row["error_stage"],
                error_code=row["error_code"],
                error_message=row["error_message"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # =========================================================================
    # DISCREPANCY MANAGEMENT (Dead Letter Queue)
    # =========================================================================

    def create_discrepancy(
        self,
        batch_id: str,
        row_index: int,
        raw_data: Dict[str, Any],
        error_type: ErrorType,
        error_message: str,
        error_code: Optional[str] = None,
        error_details: Optional[Dict[str, Any]] = None,
        source_file: Optional[str] = None,
    ) -> str:
        """
        Create a discrepancy record (add to Dead Letter Queue).

        Args:
            batch_id: Batch UUID
            row_index: Row number that failed
            raw_data: Original row data
            error_type: Type of error
            error_message: Human-readable error message
            error_code: Machine-readable error code
            error_details: Additional error context
            source_file: Original source filename

        Returns:
            Discrepancy ID
        """
        disc_id = str(uuid4())

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.data_discrepancies (
                    id, batch_id, row_index, source_file,
                    raw_data, error_type, error_code, error_message,
                    error_details, status
                ) VALUES (
                    %s::uuid, %s::uuid, %s, %s,
                    %s, %s, %s, %s,
                    %s, 'pending'
                )
                ON CONFLICT (batch_id, row_index) DO UPDATE SET
                    raw_data = EXCLUDED.raw_data,
                    error_type = EXCLUDED.error_type,
                    error_code = EXCLUDED.error_code,
                    error_message = EXCLUDED.error_message,
                    error_details = EXCLUDED.error_details,
                    updated_at = now()
                RETURNING id::text
                """,
                (
                    disc_id,
                    batch_id,
                    row_index,
                    source_file,
                    json.dumps(raw_data, default=str),
                    error_type.value,
                    error_code,
                    error_message[:1000],
                    json.dumps(error_details, default=str) if error_details else None,
                ),
            )
            result = cur.fetchone()
            self.conn.commit()

        logger.warning(
            f"[Reconciliation] Created discrepancy {disc_id}: "
            f"batch={batch_id}, row={row_index}, type={error_type.value}"
        )

        return result[0] if result else disc_id

    def get_discrepancies(
        self,
        batch_id: Optional[str] = None,
        status: Optional[DiscrepancyStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Discrepancy]:
        """
        Get discrepancies (failed rows) from Dead Letter Queue.

        Args:
            batch_id: Filter by batch (optional)
            status: Filter by status (optional)
            limit: Max results
            offset: Pagination offset

        Returns:
            List of Discrepancy objects
        """
        query = """
            SELECT
                id::text,
                batch_id::text,
                row_index,
                source_file,
                raw_data,
                error_type,
                error_code,
                error_message,
                error_details,
                status,
                retry_count,
                resolved_at,
                resolved_by,
                created_at
            FROM ops.data_discrepancies
            WHERE 1=1
        """
        params: List[Any] = []

        if batch_id:
            query += " AND batch_id = %s::uuid"
            params.append(batch_id)

        if status:
            query += " AND status = %s"
            params.append(status.value)

        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        return [
            Discrepancy(
                id=row["id"],
                batch_id=row["batch_id"],
                row_index=row["row_index"],
                source_file=row["source_file"],
                raw_data=row["raw_data"],
                error_type=ErrorType(row["error_type"]),
                error_code=row["error_code"],
                error_message=row["error_message"],
                error_details=row["error_details"],
                status=DiscrepancyStatus(row["status"]),
                retry_count=row["retry_count"],
                resolved_at=row["resolved_at"],
                resolved_by=row["resolved_by"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def update_discrepancy(
        self,
        discrepancy_id: str,
        raw_data: Optional[Dict[str, Any]] = None,
        status: Optional[DiscrepancyStatus] = None,
        resolution_notes: Optional[str] = None,
        resolved_by: Optional[str] = None,
    ) -> bool:
        """
        Update a discrepancy (for editing before retry).

        Args:
            discrepancy_id: UUID of discrepancy
            raw_data: Updated row data (for retry)
            status: New status
            resolution_notes: Notes about resolution
            resolved_by: User who resolved

        Returns:
            True if updated, False if not found
        """
        updates = []
        params: List[Any] = []

        if raw_data is not None:
            updates.append("raw_data = %s")
            params.append(json.dumps(raw_data, default=str))

        if status is not None:
            updates.append("status = %s")
            params.append(status.value)
            if status == DiscrepancyStatus.RESOLVED:
                updates.append("resolved_at = now()")

        if resolution_notes is not None:
            updates.append("resolution_notes = %s")
            params.append(resolution_notes)

        if resolved_by is not None:
            updates.append("resolved_by = %s")
            params.append(resolved_by)

        if not updates:
            return True  # Nothing to update

        query = f"""
            UPDATE ops.data_discrepancies
            SET {", ".join(updates)}
            WHERE id = %s::uuid
        """
        params.append(discrepancy_id)

        with self.conn.cursor() as cur:
            cur.execute(query, params)
            updated = cur.rowcount > 0
            self.conn.commit()

        return updated

    def retry_discrepancy(self, discrepancy_id: str) -> Dict[str, Any]:
        """
        Retry processing a discrepancy with its (possibly edited) raw_data.

        This will:
        1. Mark status as 'retrying'
        2. Increment retry_count
        3. Attempt to process the row again
        4. Update status to 'resolved' or back to 'pending'

        Args:
            discrepancy_id: UUID of discrepancy to retry

        Returns:
            Dict with retry result
        """
        # Get the discrepancy
        self.get_discrepancies(status=None, limit=1)
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM ops.data_discrepancies WHERE id = %s::uuid
                """,
                (discrepancy_id,),
            )
            disc = cur.fetchone()

        if not disc:
            return {"success": False, "error": "Discrepancy not found"}

        # Mark as retrying
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ops.data_discrepancies
                SET status = 'retrying',
                    retry_count = retry_count + 1,
                    last_retry_at = now()
                WHERE id = %s::uuid
                """,
                (discrepancy_id,),
            )
            self.conn.commit()

        # TODO: Actually retry the row processing here
        # This would call into the ingest_processor to re-process
        # For now, just return a placeholder

        return {
            "success": False,
            "error": "Retry processing not yet implemented",
            "discrepancy_id": discrepancy_id,
            "raw_data": disc["raw_data"],
        }

    def dismiss_discrepancy(
        self,
        discrepancy_id: str,
        resolved_by: str,
        resolution_notes: Optional[str] = None,
    ) -> bool:
        """
        Dismiss a discrepancy as not fixable.

        Args:
            discrepancy_id: UUID of discrepancy
            resolved_by: User dismissing
            resolution_notes: Reason for dismissal

        Returns:
            True if dismissed
        """
        return self.update_discrepancy(
            discrepancy_id=discrepancy_id,
            status=DiscrepancyStatus.DISMISSED,
            resolved_by=resolved_by,
            resolution_notes=resolution_notes,
        )

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _compute_checksum(self, data: Dict[str, Any]) -> str:
        """Compute SHA256 checksum of data for integrity verification."""
        serialized = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]

    # =========================================================================
    # ENTITY AUDIT LOGGING
    # =========================================================================

    def log_entity_change(
        self,
        entity_id: str,
        table_name: str,
        action: str,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        worker_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        source_file: Optional[str] = None,
    ) -> str:
        """
        Log an entity-level change to ops.audit_log.

        This provides a mathematical guarantee of data changes by recording
        the before/after state of every INSERT/UPDATE/DELETE operation.

        Args:
            entity_id: Primary key of the entity (as string)
            table_name: Table name (e.g., 'public.judgments')
            action: 'INSERT', 'UPDATE', or 'DELETE'
            old_values: Previous entity state (None for INSERT)
            new_values: New entity state (None for DELETE)
            worker_id: ID of the worker/process making the change
            batch_id: Associated batch UUID (if from ingestion)
            source_file: Source file name

        Returns:
            Audit log entry ID
        """
        entry_id = str(uuid4())

        # Calculate changed fields for UPDATE
        changed_fields: Optional[List[str]] = None
        if action == "UPDATE" and old_values and new_values:
            changed_fields = [
                k for k in new_values.keys() if k in old_values and old_values[k] != new_values[k]
            ]

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.audit_log (
                    id, entity_id, table_name, action,
                    old_values, new_values, changed_fields,
                    worker_id, batch_id, source_file
                ) VALUES (
                    %s::uuid, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s::uuid, %s
                )
                RETURNING id::text
                """,
                (
                    entry_id,
                    str(entity_id),
                    table_name,
                    action,
                    json.dumps(old_values, default=str) if old_values else None,
                    json.dumps(new_values, default=str) if new_values else None,
                    changed_fields,
                    worker_id,
                    batch_id,
                    source_file,
                ),
            )
            result = cur.fetchone()
            self.conn.commit()

        logger.debug(f"[Audit] Logged {action} on {table_name}:{entity_id}")

        return result[0] if result else entry_id

    # =========================================================================
    # BATCH INTEGRITY VERIFICATION
    # =========================================================================

    def check_batch_integrity(self, batch_id: str) -> Dict[str, Any]:
        """
        Verify batch integrity using the SQL function ops.check_batch_integrity().

        This is the core reconciliation function that provides mathematical
        proof that no data was lost during ingestion.

        Algorithm:
            1. Compare intake.simplicity_raw_rows count VS public.judgments count
            2. If match → Mark batch "verified" (GREEN)
            3. If mismatch → Mark batch "discrepancy" (RED) and alert

        Args:
            batch_id: UUID of the batch to verify

        Returns:
            Dict with:
                - batch_id: UUID
                - csv_row_count: Rows in source CSV
                - db_row_count: Rows inserted into judgments
                - audit_log_count: Audit entries for this batch
                - discrepancy_count: Pending failed rows
                - integrity_score: Percentage (0-100)
                - status: 'verified' or 'discrepancy'
                - is_verified: Boolean
                - verification_message: Human-readable explanation
        """
        logger.info(f"[Integrity] Checking batch {batch_id}")

        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM ops.check_batch_integrity(%s::uuid)",
                (batch_id,),
            )
            result = cur.fetchone()

        if not result:
            raise ValueError(f"Batch {batch_id} not found or verification failed")

        verification = {
            "batch_id": str(result["batch_id"]),
            "csv_row_count": result["csv_row_count"],
            "db_row_count": result["db_row_count"],
            "audit_log_count": result["audit_log_count"],
            "discrepancy_count": result["discrepancy_count"],
            "integrity_score": float(result["integrity_score"]),
            "status": result["status"],
            "is_verified": result["is_verified"],
            "verification_message": result["verification_message"],
        }

        # Log result
        if result["is_verified"]:
            logger.info(
                f"[Integrity] Batch {batch_id[:8]} VERIFIED: "
                f"{result['csv_row_count']} rows, {result['integrity_score']:.3f}% integrity"
            )
        else:
            logger.warning(
                f"[Integrity] Batch {batch_id[:8]} DISCREPANCY: {result['verification_message']}"
            )

        return verification

    def get_batch_integrity_list(
        self,
        limit: int = 50,
        status_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get list of batches with integrity status for dashboard.

        Args:
            limit: Max batches to return
            status_filter: Filter by integrity_status ('verified', 'discrepancy', 'pending')

        Returns:
            List of batch integrity records
        """
        query = "SELECT * FROM ops.v_batch_integrity"
        params: List[Any] = []

        if status_filter:
            query += " WHERE integrity_status = %s"
            params.append(status_filter)

        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        return [dict(row) for row in rows]


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def verify_batch(conn: psycopg.Connection, batch_id: str) -> BatchVerificationResult:
    """
    Convenience function to verify a batch.

    Args:
        conn: Database connection
        batch_id: Batch UUID to verify

    Returns:
        BatchVerificationResult
    """
    service = ReconciliationService(conn)
    return service.verify_batch(batch_id)


def get_integrity_dashboard(conn: psycopg.Connection) -> IntegrityDashboard:
    """
    Convenience function to get integrity dashboard.

    Args:
        conn: Database connection

    Returns:
        IntegrityDashboard
    """
    service = ReconciliationService(conn)
    return service.get_dashboard()
