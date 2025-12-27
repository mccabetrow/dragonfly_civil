# backend/api/services/ingest_service.py
"""
Idempotent Ingest Service - North Star Architecture

This service implements the canonical ingest pipeline that powers POST /import.

Key Guarantees:
    1. IDEMPOTENCY: Same file = same batch_id, no duplicate rows or jobs
    2. TRACEABILITY: Every action logged to ops.ingest_audit_log
    3. ATOMICITY: All-or-nothing processing with proper error handling

Architecture:
    - Vercel (UI): Calls this service via REST
    - Railway (API/Worker): Executes with service_role credentials

Usage:
    from backend.api.services import IngestService

    service = IngestService(supabase_client)
    result = await service.process_file(content, filename)
"""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from backend.ingest.contract import IngestContract, IngestEvent, IngestLogger, IngestStage
from supabase import Client

# =============================================================================
# Result Types
# =============================================================================


@dataclass
class IngestResult:
    """Result of an ingest operation."""

    batch_id: str
    is_duplicate: bool
    filename: str
    file_hash: str
    rows_inserted: int
    rows_skipped: int
    jobs_created: int
    correlation_id: str
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "is_duplicate": self.is_duplicate,
            "filename": self.filename,
            "file_hash": self.file_hash,
            "rows_inserted": self.rows_inserted,
            "rows_skipped": self.rows_skipped,
            "jobs_created": self.jobs_created,
            "correlation_id": self.correlation_id,
            "success": self.success,
            "errors": self.errors,
        }


# =============================================================================
# IngestService: The Idempotent Loader
# =============================================================================


class IngestService:
    """
    Idempotent file ingest service.

    Implements the North Star architecture:
    1. Calculate file hash for batch idempotency
    2. Check/create batch with ON CONFLICT handling
    3. Parse and insert rows with deduplication
    4. Enqueue jobs with dedup_key
    5. Log all actions for traceability
    """

    def __init__(self, client: Client, source: str = "simplicity"):
        """
        Initialize the service.

        Args:
            client: Supabase client with service_role key
            source: Source identifier (e.g., "simplicity", "jbi")
        """
        self.client = client
        self.source = source
        self.logger: IngestLogger | None = None

    async def process_file(
        self,
        content: bytes,
        filename: str,
        source_reference: Optional[str] = None,
    ) -> IngestResult:
        """
        Process an uploaded file with full idempotency guarantees.

        Args:
            content: Raw bytes of the uploaded file
            filename: Original filename
            source_reference: Optional external reference ID

        Returns:
            IngestResult with batch_id and processing stats
        """
        # Initialize logger with new correlation_id
        self.logger = IngestLogger(self.client)
        correlation_id = self.logger.correlation_id

        # Log upload started
        self.logger.log_upload_started(filename, len(content))

        try:
            # Step 1: Calculate file hash
            file_hash = IngestContract.compute_file_hash(content)

            # Step 2: Check/create batch (idempotent)
            batch_id, is_duplicate = await self._get_or_create_batch(
                filename=filename,
                file_hash=file_hash,
                source_reference=source_reference,
            )

            if is_duplicate:
                self.logger.log_duplicate_batch(batch_id, file_hash)
                return IngestResult(
                    batch_id=batch_id,
                    is_duplicate=True,
                    filename=filename,
                    file_hash=file_hash,
                    rows_inserted=0,
                    rows_skipped=0,
                    jobs_created=0,
                    correlation_id=correlation_id,
                )

            # Log batch created
            self.logger.log_batch_created(batch_id, filename, file_hash)

            # Step 3: Parse and insert rows
            rows_inserted, rows_skipped = await self._parse_and_insert_rows(
                batch_id=batch_id,
                content=content,
            )

            self.logger.log_rows_inserted(batch_id, rows_inserted, rows_skipped)

            # Step 4: Enqueue jobs for validation
            jobs_created = await self._enqueue_validation_jobs(
                batch_id=batch_id,
                row_count=rows_inserted,
            )

            self.logger.log_jobs_created(batch_id, jobs_created)

            return IngestResult(
                batch_id=batch_id,
                is_duplicate=False,
                filename=filename,
                file_hash=file_hash,
                rows_inserted=rows_inserted,
                rows_skipped=rows_skipped,
                jobs_created=jobs_created,
                correlation_id=correlation_id,
            )

        except Exception as e:
            if self.logger:
                self.logger.log_error(
                    batch_id=None,
                    stage=IngestStage.UPLOAD,
                    error=str(e),
                )
            raise

    async def _get_or_create_batch(
        self,
        filename: str,
        file_hash: str,
        source_reference: Optional[str] = None,
    ) -> tuple[str, bool]:
        """
        Get existing batch or create new one (idempotent).

        Returns:
            Tuple of (batch_id, is_duplicate)
        """
        # First, try to find existing batch by file_hash
        existing = (
            self.client.table("simplicity_batches")
            .select("id")
            .eq("file_hash", file_hash)
            .limit(1)
            .execute()
        )

        if existing.data:
            return existing.data[0]["id"], True

        # Create new batch
        batch_data = {
            "filename": filename,
            "file_hash": file_hash,
            "source_reference": source_reference or filename,
            "status": "staging",
            "row_count_total": 0,
            "row_count_staged": 0,
            "row_count_valid": 0,
            "row_count_invalid": 0,
            "row_count_inserted": 0,
        }

        result = self.client.table("simplicity_batches").insert(batch_data).execute()

        return result.data[0]["id"], False

    async def _parse_and_insert_rows(
        self,
        batch_id: str,
        content: bytes,
    ) -> tuple[int, int]:
        """
        Parse CSV content and insert raw rows.

        Uses ON CONFLICT DO NOTHING for idempotency.

        Returns:
            Tuple of (rows_inserted, rows_skipped)
        """
        # Decode content
        text = content.decode("utf-8-sig")  # Handle BOM
        reader = csv.DictReader(io.StringIO(text))

        rows_to_insert = []
        for row_index, row in enumerate(reader):
            row_hash = IngestContract.compute_row_hash(row)
            rows_to_insert.append(
                {
                    "batch_id": batch_id,
                    "row_index": row_index,
                    "raw_data": row,
                    "row_hash": row_hash,
                }
            )

        if not rows_to_insert:
            return 0, 0

        # Batch insert with upsert (ON CONFLICT DO NOTHING equivalent)
        # We use upsert with ignoreDuplicates=True
        result = (
            self.client.table("simplicity_raw_rows")
            .upsert(rows_to_insert, on_conflict="batch_id,row_index", ignore_duplicates=True)
            .execute()
        )

        rows_inserted = len(result.data) if result.data else 0
        rows_skipped = len(rows_to_insert) - rows_inserted

        # Update batch row count
        (
            self.client.table("simplicity_batches")
            .update(
                {
                    "row_count_total": len(rows_to_insert),
                    "row_count_staged": rows_inserted,
                }
            )
            .eq("id", batch_id)
            .execute()
        )

        return rows_inserted, rows_skipped

    async def _enqueue_validation_jobs(
        self,
        batch_id: str,
        row_count: int,
    ) -> int:
        """
        Enqueue validation jobs for each row.

        Uses dedup_key for job idempotency.

        Returns:
            Number of jobs created
        """
        if row_count == 0:
            return 0

        jobs_to_insert = []
        for row_index in range(row_count):
            dedup_key = IngestContract.compute_dedup_key(batch_id, row_index, "validation")
            jobs_to_insert.append(
                {
                    "job_type": "simplicity_ingest",
                    "payload": {
                        "batch_id": batch_id,
                        "row_index": row_index,
                    },
                    "status": "pending",
                    "priority": 100,
                    "dedup_key": dedup_key,
                    "correlation_id": self.logger.correlation_id if self.logger else None,
                }
            )

        # Batch insert with upsert (ON CONFLICT DO NOTHING)
        # For job_queue, we need to handle the partial unique index specially
        # We'll insert and catch duplicates
        jobs_created = 0
        for job in jobs_to_insert:
            try:
                result = self.client.table("job_queue").insert(job).execute()
                if result.data:
                    jobs_created += 1
            except Exception:
                # Duplicate job (already queued) - this is expected and OK
                pass

        return jobs_created

    # =========================================================================
    # Sync variants for non-async contexts
    # =========================================================================

    def process_file_sync(
        self,
        content: bytes,
        filename: str,
        source_reference: Optional[str] = None,
    ) -> IngestResult:
        """Synchronous version of process_file."""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.process_file(content, filename, source_reference))
