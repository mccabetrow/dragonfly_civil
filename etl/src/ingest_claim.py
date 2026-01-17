"""Ingestion claim client for atomic batch claiming.

This module provides the Python interface to the ingest.claim_import_run() and
related RPC functions in the database. It implements the "ingestion moat" pattern:

1. claim_import_run() - Atomically claim a batch before processing
2. finalize_import_run() - Update counts after processing
3. reconcile_import_run() - Verify row counts match
4. rollback_import_run() - Soft-delete a run if needed
5. heartbeat_import_run() - Keep claim alive during long imports

Usage:
    from etl.src.ingest_claim import IngestClaimClient, ClaimStatus

    with psycopg.connect(dsn) as conn:
        client = IngestClaimClient(conn)

        # Claim the batch
        result = client.claim(
            source_system="simplicity",
            source_batch_id="2026-01-15-batch-001",
            file_hash="abc123...",
            filename="plaintiffs.csv",
        )

        if result.status == ClaimStatus.DUPLICATE:
            print("Already imported - skipping")
            sys.exit(0)

        if result.status == ClaimStatus.IN_PROGRESS:
            print("Another worker is processing - retry later")
            sys.exit(1)

        # Process the file...
        try:
            rows_inserted = process_csv(...)

            # Finalize with counts
            client.finalize(
                run_id=result.run_id,
                rows_fetched=total_rows,
                rows_inserted=rows_inserted,
                rows_skipped=0,
                rows_errored=0,
            )

        except Exception as e:
            client.finalize(
                run_id=result.run_id,
                rows_fetched=0,
                rows_inserted=0,
                rows_skipped=0,
                rows_errored=1,
                error_details={"fatal": True, "message": str(e)},
            )
            raise
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row


class ClaimStatus(Enum):
    """Result of a claim attempt."""

    CLAIMED = "claimed"  # Successfully claimed - proceed with import
    DUPLICATE = "duplicate"  # Already completed - skip
    IN_PROGRESS = "in_progress"  # Another worker has it - retry later


@dataclass(frozen=True)
class ClaimResult:
    """Result of claim_import_run()."""

    run_id: uuid.UUID
    status: ClaimStatus

    @property
    def is_claimed(self) -> bool:
        return self.status == ClaimStatus.CLAIMED

    @property
    def is_duplicate(self) -> bool:
        return self.status == ClaimStatus.DUPLICATE

    @property
    def is_in_progress(self) -> bool:
        return self.status == ClaimStatus.IN_PROGRESS


@dataclass(frozen=True)
class ReconcileResult:
    """Result of reconcile_import_run()."""

    is_valid: bool
    expected_count: int
    actual_count: int
    delta: int


@dataclass(frozen=True)
class RollbackResult:
    """Result of rollback_import_run()."""

    success: bool
    rows_affected: int


class IngestClaimClient:
    """Client for ingestion claim RPC functions.

    This client provides atomic, concurrency-safe batch claiming for the
    plaintiff ingestion pipeline. It wraps the ingest.* RPC functions.
    """

    def __init__(self, conn: Connection, worker_id: Optional[str] = None):
        """Initialize the claim client.

        Args:
            conn: Database connection (must be open).
            worker_id: Unique identifier for this worker. Auto-generated if None.
        """
        self.conn = conn
        self.worker_id = worker_id or self._generate_worker_id()

    @staticmethod
    def _generate_worker_id() -> str:
        """Generate a unique worker ID from hostname and PID."""
        hostname = socket.gethostname()[:32]
        pid = os.getpid()
        return f"{hostname}-{pid}-{uuid.uuid4().hex[:8]}"

    def claim(
        self,
        source_system: str,
        source_batch_id: str,
        file_hash: str,
        filename: Optional[str] = None,
        import_kind: str = "plaintiff",
    ) -> ClaimResult:
        """Atomically claim an import batch.

        This is the first step in the ingestion moat. Call this before
        processing any rows. If the result is not CLAIMED, do not proceed.

        Args:
            source_system: Source system identifier (e.g., 'simplicity', 'jbi').
            source_batch_id: Unique batch identifier from the source.
            file_hash: SHA-256 hash of the source file.
            filename: Original filename (optional, for display).
            import_kind: Type of import (default: 'plaintiff').

        Returns:
            ClaimResult with run_id and status.

        Example:
            result = client.claim(
                source_system="simplicity",
                source_batch_id="batch-2026-01-15",
                file_hash=compute_file_hash(csv_path),
            )

            if result.is_duplicate:
                sys.exit(0)  # Already done

            if result.is_in_progress:
                sys.exit(1)  # Retry later

            # Proceed with import using result.run_id
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM ingest.claim_import_run(
                    %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    source_system,
                    source_batch_id,
                    file_hash,
                    filename,
                    import_kind,
                    self.worker_id,
                ),
            )
            row = cur.fetchone()

        if row is None:
            raise RuntimeError("claim_import_run returned no result")

        return ClaimResult(
            run_id=uuid.UUID(str(row["run_id"])),
            status=ClaimStatus(row["claim_status"]),
        )

    def finalize(
        self,
        run_id: uuid.UUID,
        rows_fetched: int,
        rows_inserted: int,
        rows_skipped: int,
        rows_errored: int,
        error_details: Optional[dict[str, Any]] = None,
        mark_completed: bool = True,
    ) -> bool:
        """Finalize an import run with final counts.

        Call this after processing is complete (success or failure).

        Args:
            run_id: The run ID from claim().
            rows_fetched: Total rows read from source.
            rows_inserted: Rows successfully inserted.
            rows_skipped: Rows skipped (duplicates, etc.).
            rows_errored: Rows that failed.
            error_details: Optional error information (set 'fatal': True for failures).
            mark_completed: Whether to mark run as completed (default: True).

        Returns:
            True if run was updated, False if not found.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT ingest.finalize_import_run(
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    str(run_id),
                    rows_fetched,
                    rows_inserted,
                    rows_skipped,
                    rows_errored,
                    json.dumps(error_details) if error_details else None,
                    mark_completed,
                ),
            )
            result = cur.fetchone()
            return bool(result and result[0])

    def reconcile(
        self,
        run_id: uuid.UUID,
        expected_count: Optional[int] = None,
    ) -> ReconcileResult:
        """Reconcile import run by verifying row counts.

        Call this after inserting rows to verify the count matches expectations.
        The run will be marked as completed or failed based on the result.

        Args:
            run_id: The run ID from claim().
            expected_count: Expected row count (optional, uses rows_fetched if None).

        Returns:
            ReconcileResult with validation details.
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM ingest.reconcile_import_run(%s, %s)
                """,
                (str(run_id), expected_count),
            )
            row = cur.fetchone()

        if row is None:
            raise RuntimeError("reconcile_import_run returned no result")

        return ReconcileResult(
            is_valid=bool(row["is_valid"]),
            expected_count=int(row["expected_count"]),
            actual_count=int(row["actual_count"]),
            delta=int(row["delta"]),
        )

    def rollback(
        self,
        run_id: uuid.UUID,
        reason: str = "manual_rollback",
    ) -> RollbackResult:
        """Soft-delete an import run.

        This marks the run as rolled_back and updates associated rows.
        No data is deleted - full audit trail is preserved.

        Args:
            run_id: The run ID to rollback.
            reason: Reason for rollback (stored in audit trail).

        Returns:
            RollbackResult with success status and affected row count.
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM ingest.rollback_import_run(%s, %s)
                """,
                (str(run_id), reason),
            )
            row = cur.fetchone()

        if row is None:
            raise RuntimeError("rollback_import_run returned no result")

        return RollbackResult(
            success=bool(row["success"]),
            rows_affected=int(row["rows_affected"]),
        )

    def heartbeat(self, run_id: uuid.UUID) -> bool:
        """Send heartbeat to keep claim alive.

        Call this periodically during long-running imports to prevent
        the stale lock takeover mechanism from reclaiming the run.

        Args:
            run_id: The run ID from claim().

        Returns:
            True if heartbeat was recorded, False if run not found or not processing.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT ingest.heartbeat_import_run(%s)
                """,
                (str(run_id),),
            )
            result = cur.fetchone()
            return bool(result and result[0])


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def compute_file_hash(file_path: Path | str) -> str:
    """Compute SHA-256 hash of a file.

    Args:
        file_path: Path to the file.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_batch_id(source_system: str, filename: str, date_suffix: Optional[str] = None) -> str:
    """Generate a deterministic batch ID.

    Args:
        source_system: Source system name.
        filename: Original filename.
        date_suffix: Optional date suffix (e.g., '2026-01-15').

    Returns:
        Batch ID string.
    """
    stem = Path(filename).stem
    if date_suffix:
        return f"{source_system}/{stem}/{date_suffix}"
    return f"{source_system}/{stem}"
