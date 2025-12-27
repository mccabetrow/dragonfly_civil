# backend/ingest/contract.py
"""
North Star Ingest Contract & Logger

This module defines the canonical contract for the Dragonfly ingest system
and provides the IngestLogger for full traceability.

The "Law":
    1. BATCH IDEMPOTENCY: Same file hash = same batch
    2. ROW IDEMPOTENCY: Same (batch_id, row_index) = same row
    3. JOB IDEMPOTENCY: Same (job_type, dedup_key) = same job
    4. TRACEABILITY: Every action logged with correlation_id

Usage:
    from backend.ingest.contract import IngestContract, IngestLogger

    logger = IngestLogger(supabase_client)
    logger.log(batch_id, "upload", "started", {"filename": "data.csv"})
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from supabase import Client

# =============================================================================
# Pipeline Stages
# =============================================================================


class IngestStage(str, Enum):
    """Pipeline stages for audit logging."""

    UPLOAD = "upload"
    PARSE = "parse"
    VALIDATE = "validate"
    ENQUEUE = "enqueue"
    PROCESS = "process"


class IngestEvent(str, Enum):
    """Event types for audit logging."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"
    ROWS_INSERTED = "rows_inserted"
    JOBS_CREATED = "jobs_created"


# =============================================================================
# IngestContract: The "Law"
# =============================================================================


class IngestContract:
    """
    Defines the canonical rules for ingest operations.

    This class enforces the "North Star" architecture:
    - Batch idempotency via file_hash
    - Row idempotency via (batch_id, row_index)
    - Job idempotency via (job_type, dedup_key)
    """

    # Required columns for a valid row
    REQUIRED_COLS = [
        "case_number",
        "defendant_name",
        "judgment_amount",
    ]

    # Optional but recognized columns
    OPTIONAL_COLS = [
        "plaintiff_name",
        "entry_date",
        "judgment_date",
        "court",
        "county",
    ]

    @staticmethod
    def compute_file_hash(content: bytes) -> str:
        """
        Compute SHA-256 hash of file content for batch idempotency.

        Args:
            content: Raw bytes of the uploaded file

        Returns:
            Hex-encoded SHA-256 hash
        """
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def compute_row_hash(row: dict[str, Any]) -> str:
        """
        Compute hash of row content for deduplication.

        Args:
            row: Dictionary of row data

        Returns:
            Hex-encoded SHA-256 hash of sorted row content
        """
        # Sort keys for deterministic hashing
        sorted_items = sorted(row.items())
        content = str(sorted_items).encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def compute_dedup_key(batch_id: str, row_index: int, stage: str = "validation") -> str:
        """
        Compute dedup_key for job queue idempotency.

        Format: {stage}-{batch_id}-{row_index}

        Args:
            batch_id: UUID of the batch
            row_index: 0-based row index
            stage: Pipeline stage (default: "validation")

        Returns:
            Deduplication key string
        """
        return f"{stage}-{batch_id}-{row_index}"

    @classmethod
    def validate_row(cls, row: dict[str, Any]) -> list[str]:
        """
        Validate a row against the contract.

        Args:
            row: Dictionary with column names as keys

        Returns:
            List of error messages. Empty list = valid.
        """
        errors = []

        # Check required columns
        for col in cls.REQUIRED_COLS:
            if col not in row:
                errors.append(f"Missing required column: {col}")
            elif row[col] is None or str(row[col]).strip() == "":
                errors.append(f"Empty value for required column: {col}")

        # Validate judgment_amount if present
        if "judgment_amount" in row and row["judgment_amount"] is not None:
            try:
                amount = float(str(row["judgment_amount"]).replace(",", "").replace("$", ""))
                if amount < 0:
                    errors.append("Judgment amount cannot be negative")
            except (ValueError, TypeError):
                errors.append(f"Invalid judgment amount: {row['judgment_amount']}")

        return errors


# =============================================================================
# IngestLogger: Full Traceability
# =============================================================================


class IngestLogger:
    """
    Logs all ingest operations to ops.ingest_audit_log.

    Every action is logged with:
    - batch_id: Which batch this relates to
    - correlation_id: Links all operations in a single request
    - stage: Pipeline stage (upload, parse, validate, etc.)
    - event: What happened (started, completed, failed, etc.)
    - metadata: Additional context as JSONB
    """

    def __init__(self, client: Client, correlation_id: Optional[str] = None):
        """
        Initialize the logger.

        Args:
            client: Supabase client with service_role key
            correlation_id: Optional correlation ID. Generated if not provided.
        """
        self.client = client
        self.correlation_id = correlation_id or str(uuid.uuid4())

    def log(
        self,
        batch_id: Optional[str],
        stage: str | IngestStage,
        event: str | IngestEvent,
        metadata: Optional[dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Log an ingest event.

        Args:
            batch_id: UUID of the batch (can be None for pre-batch events)
            stage: Pipeline stage
            event: Event type
            metadata: Additional context
            correlation_id: Override the logger's correlation_id

        Returns:
            The inserted log record
        """
        stage_str = stage.value if isinstance(stage, IngestStage) else stage
        event_str = event.value if isinstance(event, IngestEvent) else event

        record = {
            "batch_id": batch_id,
            "correlation_id": correlation_id or self.correlation_id,
            "stage": stage_str,
            "event": event_str,
            "metadata": metadata or {},
        }

        result = self.client.table("ingest_event_log").insert(record).execute()
        return result.data[0] if result.data else record

    def log_upload_started(self, filename: str, file_size: int) -> dict[str, Any]:
        """Log that an upload has started."""
        return self.log(
            batch_id=None,
            stage=IngestStage.UPLOAD,
            event=IngestEvent.STARTED,
            metadata={"filename": filename, "file_size": file_size},
        )

    def log_batch_created(self, batch_id: str, filename: str, file_hash: str) -> dict[str, Any]:
        """Log that a new batch was created."""
        return self.log(
            batch_id=batch_id,
            stage=IngestStage.UPLOAD,
            event=IngestEvent.COMPLETED,
            metadata={"filename": filename, "file_hash": file_hash},
        )

    def log_duplicate_batch(self, batch_id: str, file_hash: str) -> dict[str, Any]:
        """Log that a duplicate batch was detected."""
        return self.log(
            batch_id=batch_id,
            stage=IngestStage.UPLOAD,
            event=IngestEvent.DUPLICATE,
            metadata={"file_hash": file_hash, "message": "Batch already exists"},
        )

    def log_rows_inserted(self, batch_id: str, count: int, skipped: int = 0) -> dict[str, Any]:
        """Log that rows were inserted."""
        return self.log(
            batch_id=batch_id,
            stage=IngestStage.PARSE,
            event=IngestEvent.ROWS_INSERTED,
            metadata={"inserted": count, "skipped": skipped},
        )

    def log_jobs_created(self, batch_id: str, count: int) -> dict[str, Any]:
        """Log that jobs were created."""
        return self.log(
            batch_id=batch_id,
            stage=IngestStage.ENQUEUE,
            event=IngestEvent.JOBS_CREATED,
            metadata={"job_count": count},
        )

    def log_error(
        self,
        batch_id: Optional[str],
        stage: str | IngestStage,
        error: str,
        details: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Log an error."""
        metadata = {"error": error}
        if details:
            metadata.update(details)
        return self.log(
            batch_id=batch_id,
            stage=stage,
            event=IngestEvent.FAILED,
            metadata=metadata,
        )


# =============================================================================
# Convenience Functions
# =============================================================================


def validate_row(row: dict[str, Any]) -> list[str]:
    """Validate a row against the contract. Convenience wrapper."""
    return IngestContract.validate_row(row)


def compute_file_hash(content: bytes) -> str:
    """Compute file hash. Convenience wrapper."""
    return IngestContract.compute_file_hash(content)


def compute_dedup_key(batch_id: str, row_index: int, stage: str = "validation") -> str:
    """Compute dedup key. Convenience wrapper."""
    return IngestContract.compute_dedup_key(batch_id, row_index, stage)
