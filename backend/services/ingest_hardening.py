"""
Dragonfly Engine - Ingest Hardening Service

Provides hardened ingest capabilities:
- File hash computation for duplicate detection
- Row-level error tracking with ops.import_errors
- Duplicate batch prevention

Usage:
    from backend.services.ingest_hardening import (
        compute_file_hash,
        check_duplicate_import,
        record_import_error,
        ImportErrorRecorder,
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# =============================================================================
# FILE HASH UTILITIES
# =============================================================================


def compute_file_hash(content: bytes) -> str:
    """
    Compute SHA-256 hash of file content.

    Args:
        content: Raw bytes of the file

    Returns:
        Hex-encoded SHA-256 hash string
    """
    return hashlib.sha256(content).hexdigest()


def compute_file_hash_from_path(path: str) -> str:
    """
    Compute SHA-256 hash of a local file.

    Args:
        path: Path to local file

    Returns:
        Hex-encoded SHA-256 hash string
    """
    with open(path, "rb") as f:
        return compute_file_hash(f.read())


# =============================================================================
# DUPLICATE DETECTION
# =============================================================================


@dataclass
class DuplicateCheckResult:
    """Result of checking for duplicate file imports."""

    is_duplicate: bool
    existing_batch_id: Optional[str] = None
    existing_status: Optional[str] = None
    existing_created_at: Optional[datetime] = None

    @property
    def message(self) -> str:
        if not self.is_duplicate:
            return "No duplicate found"
        return (
            f"File already imported in batch {self.existing_batch_id} "
            f"(status={self.existing_status}, created={self.existing_created_at})"
        )


def check_duplicate_import(
    conn: psycopg.Connection,
    file_hash: str,
    force: bool = False,
) -> DuplicateCheckResult:
    """
    Check if a file with the same hash has already been imported.

    Uses the ops.check_duplicate_file_hash SQL function if available,
    otherwise falls back to direct query.

    Args:
        conn: Database connection
        file_hash: SHA-256 hash of the file
        force: If True, skip duplicate check and return not-duplicate

    Returns:
        DuplicateCheckResult indicating if this is a duplicate import
    """
    if force:
        return DuplicateCheckResult(is_duplicate=False)

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            # Try the SQL function first
            try:
                cur.execute(
                    "SELECT * FROM ops.check_duplicate_file_hash(%s, %s)",
                    (file_hash, force),
                )
                row = cur.fetchone()
                if row and row.get("is_duplicate"):
                    return DuplicateCheckResult(
                        is_duplicate=True,
                        existing_batch_id=(
                            str(row["existing_batch_id"]) if row.get("existing_batch_id") else None
                        ),
                        existing_status=row.get("existing_status"),
                        existing_created_at=row.get("existing_created_at"),
                    )
                return DuplicateCheckResult(is_duplicate=False)
            except psycopg.errors.UndefinedFunction:
                # Function doesn't exist, use direct query
                conn.rollback()
                pass

            # Fallback: direct query
            cur.execute(
                """
                SELECT id, status, created_at
                FROM ops.ingest_batches
                WHERE file_hash = %s
                  AND status IN ('completed', 'processing')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (file_hash,),
            )
            row = cur.fetchone()
            if row:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    existing_batch_id=str(row["id"]),
                    existing_status=row["status"],
                    existing_created_at=row["created_at"],
                )
            return DuplicateCheckResult(is_duplicate=False)

    except Exception as e:
        logger.warning(f"Duplicate check failed, proceeding with import: {e}")
        return DuplicateCheckResult(is_duplicate=False)


def update_batch_file_hash(
    conn: psycopg.Connection,
    batch_id: str,
    file_hash: str,
    force_reimport: bool = False,
) -> None:
    """
    Update the file_hash column on an ingest batch.

    Args:
        conn: Database connection
        batch_id: UUID of the ingest batch
        file_hash: SHA-256 hash of the file
        force_reimport: Whether this is a forced re-import
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ops.ingest_batches
                SET file_hash = %s,
                    force_reimport = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (file_hash, force_reimport, batch_id),
            )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to update batch file_hash: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


# =============================================================================
# IMPORT ERROR RECORDING
# =============================================================================


@dataclass
class ImportError:
    """A single row-level import error."""

    row_number: int
    error_type: str
    error_message: str
    raw_data: Optional[Dict[str, Any]] = None
    field_name: Optional[str] = None
    field_value: Optional[str] = None


def record_import_error(
    conn: psycopg.Connection,
    batch_id: str,
    error: ImportError,
) -> Optional[str]:
    """
    Record a single import error to ops.import_errors.

    Args:
        conn: Database connection
        batch_id: UUID of the ingest batch
        error: The error to record

    Returns:
        UUID of the created error record, or None if failed
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.import_errors (
                    batch_id,
                    row_number,
                    error_type,
                    error_message,
                    raw_data,
                    field_name,
                    field_value,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (
                    batch_id,
                    error.row_number,
                    error.error_type,
                    error.error_message[:2000] if error.error_message else None,
                    json.dumps(error.raw_data, default=str) if error.raw_data else None,
                    error.field_name,
                    (error.field_value[:500] if error.field_value else None),
                ),
            )
            result = cur.fetchone()
            conn.commit()
            return str(result[0]) if result else None
    except psycopg.errors.UndefinedTable:
        # Table doesn't exist yet - migration not applied
        try:
            conn.rollback()
        except Exception:
            pass
        logger.debug("ops.import_errors table not found, skipping error logging")
        return None
    except Exception as e:
        logger.debug(f"Failed to record import error: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return None


class ImportErrorRecorder:
    """
    Batch recorder for import errors.

    Collects errors during processing and flushes them to the database
    periodically or on demand. More efficient than individual inserts.

    Usage:
        recorder = ImportErrorRecorder(conn, batch_id)
        recorder.add_error(row_num=1, error_type="validation", message="Bad value")
        recorder.add_error(row_num=5, error_type="parse", message="Invalid date")
        recorder.flush()  # Write all to DB
    """

    def __init__(
        self,
        conn: psycopg.Connection,
        batch_id: str,
        flush_threshold: int = 100,
    ):
        self.conn = conn
        self.batch_id = batch_id
        self.flush_threshold = flush_threshold
        self._errors: List[ImportError] = []
        self._total_recorded = 0

    def add_error(
        self,
        row_number: int,
        error_type: str,
        error_message: str,
        raw_data: Optional[Dict[str, Any]] = None,
        field_name: Optional[str] = None,
        field_value: Optional[str] = None,
    ) -> None:
        """Add an error to the buffer."""
        self._errors.append(
            ImportError(
                row_number=row_number,
                error_type=error_type,
                error_message=error_message,
                raw_data=raw_data,
                field_name=field_name,
                field_value=field_value,
            )
        )

        if len(self._errors) >= self.flush_threshold:
            self.flush()

    def flush(self) -> int:
        """
        Write all buffered errors to the database.

        Returns:
            Number of errors successfully written
        """
        if not self._errors:
            return 0

        written = 0
        try:
            with self.conn.cursor() as cur:
                # Use executemany for batch insert
                cur.executemany(
                    """
                    INSERT INTO ops.import_errors (
                        batch_id,
                        row_number,
                        error_type,
                        error_message,
                        raw_data,
                        field_name,
                        field_value,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    """,
                    [
                        (
                            self.batch_id,
                            e.row_number,
                            e.error_type,
                            e.error_message[:2000] if e.error_message else None,
                            json.dumps(e.raw_data, default=str) if e.raw_data else None,
                            e.field_name,
                            (e.field_value[:500] if e.field_value else None),
                        )
                        for e in self._errors
                    ],
                )
            self.conn.commit()
            written = len(self._errors)
            self._total_recorded += written
            self._errors.clear()
        except psycopg.errors.UndefinedTable:
            # Table doesn't exist yet
            try:
                self.conn.rollback()
            except Exception:
                pass
            logger.debug("ops.import_errors table not found, clearing error buffer")
            self._errors.clear()
        except Exception as e:
            logger.warning(f"Failed to flush import errors: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass

        return written

    @property
    def total_recorded(self) -> int:
        """Total number of errors written to DB."""
        return self._total_recorded

    @property
    def pending_count(self) -> int:
        """Number of errors waiting to be flushed."""
        return len(self._errors)

    def __enter__(self) -> "ImportErrorRecorder":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.flush()
