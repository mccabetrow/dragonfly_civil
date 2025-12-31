"""
Dragonfly Engine - Ingestion Service

Enterprise-grade batch ingestion engine with idempotency and observability.

This is the UNIFIED ingestion interface. All batch ingestion flows through here.

Features:
- Idempotent batch creation (file hash prevents duplicate uploads)
- Idempotent row insertion (insert_or_get_judgment RPC)
- Row-level error persistence with raw_data JSON
- Discord notification on batch completion
- Supabase Storage for raw CSV persistence

Usage:
    from backend.services.ingestion_service import IngestionService

    service = IngestionService()
    batch_id = await service.create_batch(file, "export_2024.csv")
    result = await service.process_batch(batch_id)
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pandas as pd

from ..db import get_connection, get_supabase_client

if TYPE_CHECKING:
    from fastapi import UploadFile

logger = logging.getLogger(__name__)

# Storage path pattern for CSV files
STORAGE_BUCKET = "intake"
STORAGE_PATH_TEMPLATE = "simplicity/{batch_id}.csv"


# =============================================================================
# RESULT DATACLASSES
# =============================================================================


@dataclass
class BatchCreateResult:
    """Result from creating a batch."""

    batch_id: UUID
    filename: str
    file_hash: str
    row_count_total: int
    status: str
    is_duplicate: bool = False


@dataclass
class BatchProcessResult:
    """Result from processing a batch."""

    batch_id: UUID
    status: str  # 'completed', 'partial', 'failed'
    rows_processed: int
    rows_inserted: int
    rows_skipped: int  # Already exists in judgments (duplicates)
    rows_failed: int
    plaintiffs_inserted: int = 0
    plaintiffs_duplicate: int = 0
    plaintiffs_failed: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Percentage of rows successfully processed (inserted + skipped)."""
        if self.rows_processed == 0:
            return 0.0
        return round((self.rows_inserted + self.rows_skipped) / self.rows_processed * 100, 1)

    def to_discord_summary(self, filename: str, duration_seconds: float | None = None) -> str:
        """Format batch result as Discord message."""
        emoji = "✅" if self.status == "completed" else "❌"

        lines = [
            f"{emoji} **Batch Ingestion {self.status.upper()}**",
            f"📄 File: `{filename}`",
            f"📊 Total: **{self.rows_processed}** rows",
            f"   ├─ ✅ Inserted: {self.rows_inserted}",
            f"   ├─ ⏭️ Duplicates: {self.rows_skipped}",
            f"   └─ ❌ Failed: {self.rows_failed}",
            (
                "👥 Plaintiffs — "
                f"created: {self.plaintiffs_inserted}, "
                f"deduped: {self.plaintiffs_duplicate}, "
                f"failed: {self.plaintiffs_failed}"
            ),
            f"📈 Success Rate: **{self.success_rate}%**",
        ]

        if duration_seconds:
            lines.append(f"⏱️ Duration: {duration_seconds:.1f}s")

        if self.errors:
            lines.append("")
            lines.append("**First Errors:**")
            for err in self.errors[:3]:
                row_idx = err.get("row_index", "?")
                error = err.get("error", "Unknown")[:80]
                lines.append(f"  • Row {row_idx}: {error}")

        return "\n".join(lines)


@dataclass
class RowError:
    """Error details for a failed row."""

    row_index: int
    error_code: str
    error_message: str
    raw_data: dict[str, Any]


# =============================================================================
# HEADER NORMALIZATION
# =============================================================================

HEADER_VARIANTS: dict[str, str] = {
    # Plaintiff
    "plaintiffname": "plaintiff_name",
    "plaintiff_name": "plaintiff_name",
    "plaintiff": "plaintiff_name",
    "creditor": "plaintiff_name",
    "creditor_name": "plaintiff_name",
    # Defendant
    "defendantname": "defendant_name",
    "defendant_name": "defendant_name",
    "defendant": "defendant_name",
    "debtor": "defendant_name",
    "debtor_name": "defendant_name",
    # Case number / File number
    "file_number": "case_number",
    "filenumber": "case_number",
    "file_#": "case_number",
    "file#": "case_number",
    "caseno": "case_number",
    "case_no": "case_number",
    "case_number": "case_number",
    "casenumber": "case_number",
    "docket": "case_number",
    "docket_number": "case_number",
    "docketnumber": "case_number",
    "index_number": "case_number",
    "indexnumber": "case_number",
    # Amount
    "amount": "judgment_amount",
    "judgmentamount": "judgment_amount",
    "judgment_amount": "judgment_amount",
    "amount_awarded": "judgment_amount",
    "total_amount": "judgment_amount",
    "principal": "judgment_amount",
    # Date
    "judgmentdate": "judgment_date",
    "judgment_date": "judgment_date",
    "date_of_judgment": "judgment_date",
    "entry_date": "judgment_date",
    "entrydate": "judgment_date",
    "filing_date": "judgment_date",
    # Court
    "court": "court",
    "court_name": "court",
    "courtname": "court",
    "venue": "court",
    # County
    "county": "county",
    "county_name": "county",
}


def normalize_header(header: str) -> str:
    """Normalize a single header to canonical form."""
    normalized = header.lower().strip().replace(" ", "_").replace("-", "_")
    return HEADER_VARIANTS.get(normalized, normalized)


def normalize_headers(headers: list[str]) -> dict[str, str]:
    """
    Map raw headers to canonical column names.

    Returns:
        Dict mapping raw_header → canonical_name (for recognized headers)
    """
    result: dict[str, str] = {}
    used_canonical: set[str] = set()

    for header in headers:
        canonical = normalize_header(header)
        # Only add if not already mapped (first match wins)
        if canonical in HEADER_VARIANTS.values() and canonical not in used_canonical:
            result[header] = canonical
            used_canonical.add(canonical)

    return result


# =============================================================================
# PARSING HELPERS
# =============================================================================


def parse_amount(value: Any) -> float | None:
    """Parse monetary amounts, handling currency symbols and commas."""
    if pd.isna(value) or value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, Decimal):
        return float(value)

    # String parsing: remove $, commas, whitespace
    s = str(value).strip()
    if not s:
        return None

    s = re.sub(r"[$,\s]", "", s)

    # Handle parentheses for negative (accounting format)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]

    try:
        return float(Decimal(s))
    except (ValueError, InvalidOperation):
        logger.warning(f"Could not parse amount: {value}")
        return None


def parse_date(value: Any) -> date | None:
    """Parse dates from various formats."""
    if pd.isna(value) or value is None:
        return None

    if isinstance(value, date):
        return value

    if isinstance(value, datetime):
        return value.date()

    if hasattr(value, "date"):  # pandas Timestamp
        return value.date()

    s = str(value).strip()
    if not s:
        return None

    # Try common formats
    for fmt in [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%m/%d/%y",
        "%d-%b-%Y",
    ]:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    logger.warning(f"Could not parse date: {value}")
    return None


def normalize_defendant(value: Any) -> str | None:
    """Normalize defendant name for deduplication key."""
    if pd.isna(value) or value is None:
        return None

    s = str(value).strip().upper()
    # Remove common suffixes for matching
    s = re.sub(r"\s+(LLC|INC|CORP|CO|LTD)\.?$", "", s, flags=re.IGNORECASE)
    # Remove extra whitespace
    s = re.sub(r"\s+", " ", s)
    return s if s else None


def compute_file_hash(content: bytes) -> str:
    """Compute SHA-256 hash of file content."""
    return hashlib.sha256(content).hexdigest()


def build_dedupe_key(case_number: str, defendant_normalized: str | None) -> str:
    """Build a stable deduplication key for a judgment."""
    parts = [case_number.upper().strip()]
    if defendant_normalized:
        parts.append(defendant_normalized)
    return "|".join(parts)


# =============================================================================
# INGESTION SERVICE
# =============================================================================


class IngestionService:
    """
    Unified batch ingestion engine.

    Features:
    - Idempotent batch creation (file hash prevents duplicates)
    - Row-level error tracking to intake.row_errors equivalent
    - Deduplication against existing judgments
    - Full audit trail in intake.simplicity_raw_rows
    """

    def __init__(self) -> None:
        """Initialize the ingestion service."""
        self._supabase = get_supabase_client()

    async def create_batch(
        self,
        file: UploadFile,
        filename: str | None = None,
        force: bool = False,
    ) -> BatchCreateResult:
        """
        Create a new batch from an uploaded file.

        1. Reads file content and computes hash
        2. Checks for duplicate batch (same hash) unless force=True
        3. Creates batch record in intake.simplicity_batches
        4. Uploads raw file to Supabase Storage: raw_batches/{batch_id}.csv

        Args:
            file: FastAPI UploadFile object
            filename: Override filename (defaults to file.filename)
            force: If True, skip idempotency check and re-process same file

        Returns:
            BatchCreateResult with batch_id, counts, and duplicate flag

        Raises:
            ValueError: If file is empty or invalid
        """
        actual_filename = filename or file.filename or f"batch_{uuid4().hex[:8]}.csv"
        logger.info(f"Creating batch for file: {actual_filename}")

        # Read file content
        content = await file.read()
        await file.seek(0)  # Reset for potential re-read

        if not content:
            raise ValueError("Empty file")

        # Compute hash for idempotency
        file_hash = compute_file_hash(content)

        # Check for duplicate batch (unless force=True)
        async with get_connection() as conn:
            if not force:
                existing = await conn.fetchrow(
                    """
                    SELECT id, filename, status, row_count_total
                    FROM intake.simplicity_batches
                    WHERE file_hash = $1
                    """,
                    file_hash,
                )

                if existing:
                    logger.info(
                        f"Duplicate batch found: {existing['id']} (use force=True to override)"
                    )
                    return BatchCreateResult(
                        batch_id=UUID(str(existing["id"])),
                        filename=existing["filename"],
                        file_hash=file_hash,
                        row_count_total=existing["row_count_total"],
                        status=existing["status"],
                        is_duplicate=True,
                    )
            else:
                logger.info(f"force=True: Skipping idempotency check for hash {file_hash[:12]}...")

            # Parse CSV to get row count
            try:
                df = pd.read_csv(
                    io.BytesIO(content),
                    dtype=str,
                    keep_default_na=False,
                )
                row_count = len(df)
            except Exception as e:
                logger.error(f"Failed to parse CSV: {e}")
                raise ValueError(f"Invalid CSV format: {e}") from e

            # Create batch record with storage path
            batch_id = uuid4()
            now = datetime.now(timezone.utc)
            storage_path = STORAGE_PATH_TEMPLATE.format(batch_id=batch_id)

            await conn.execute(
                """
                INSERT INTO intake.simplicity_batches (
                    id,
                    filename,
                    file_hash,
                    storage_path,
                    row_count_total,
                    status,
                    error_threshold_percent,
                    created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                str(batch_id),
                actual_filename,
                file_hash if not force else None,  # Clear hash if forced to allow future re-upload
                storage_path,
                row_count,
                "pending",
                10,  # Default error threshold: 10%
                now,
            )

        # Upload to Supabase Storage: intake/simplicity/{batch_id}.csv
        try:
            self._supabase.storage.from_(STORAGE_BUCKET).upload(
                storage_path,
                content,
                {"content-type": "text/csv"},
            )
            logger.info(f"Uploaded batch to storage: {STORAGE_BUCKET}/{storage_path}")
        except Exception as e:
            logger.warning(f"Storage upload failed (non-fatal): {e}")
            # Continue - batch is still valid without storage backup

        return BatchCreateResult(
            batch_id=batch_id,
            filename=actual_filename,
            file_hash=file_hash,
            row_count_total=row_count,
            status="pending",
            is_duplicate=False,
        )

    async def process_batch(self, batch_id: UUID, *, force: bool = False) -> BatchProcessResult:
        """
        Process a batch: parse, validate, dedupe, and insert.

        1. Downloads CSV from Storage (or re-reads from staging)
        2. Parses each row, validates required fields (File #, Defendant, Amount)
        3. Dedupes against existing judgments (file_number + defendant_normalized)
        4. Inserts valid rows to public.judgments
        5. Records errors to intake.simplicity_failed_rows

        Args:
            batch_id: UUID of the batch to process
            force: Allow reprocessing even if another worker already claimed the batch

        Returns:
            BatchProcessResult with counts and error details
        """
        logger.info(f"Processing batch: {batch_id}")

        # Timing metrics
        parse_start = time.perf_counter()
        parse_duration_ms: int | None = None
        db_duration_ms: int | None = None

        async with get_connection() as conn:
            # Get batch record (including error threshold)
            batch = await conn.fetchrow(
                """
                SELECT id, filename, status, row_count_total, file_hash,
                       COALESCE(error_threshold_percent, 10) AS error_threshold_percent
                FROM intake.simplicity_batches
                WHERE id = $1
                """,
                str(batch_id),
            )

            if not batch:
                raise ValueError(f"Batch not found: {batch_id}")

            if batch["status"] in ("completed", "failed"):
                logger.warning(f"Batch {batch_id} already processed: {batch['status']}")
                return BatchProcessResult(
                    batch_id=batch_id,
                    status=batch["status"],
                    rows_processed=batch["row_count_total"],
                    rows_inserted=0,
                    rows_skipped=0,
                    rows_failed=0,
                )

            batch_file_hash = batch["file_hash"]

            allowed_statuses = ["pending", "uploaded"]
            if force:
                allowed_statuses.extend(["staging", "transforming"])

            claimed = await conn.fetchrow(
                """
                UPDATE intake.simplicity_batches
                SET status = 'staging', staged_at = NOW()
                WHERE id = $1
                  AND status = ANY($2::text[])
                RETURNING id
                """,
                str(batch_id),
                allowed_statuses,
            )

            if not claimed:
                logger.warning(
                    "Batch %s is already being processed (status=%s, force=%s)",
                    batch_id,
                    batch["status"],
                    force,
                )
                raise RuntimeError(
                    "Batch is locked by another worker. Pass force=True to override if safe."
                )

            # Try to download from storage
            csv_content: bytes | None = None
            storage_path = STORAGE_PATH_TEMPLATE.format(batch_id=batch_id)
            try:
                response = self._supabase.storage.from_(STORAGE_BUCKET).download(storage_path)
                csv_content = response
                logger.info(f"Downloaded batch from storage: {storage_path}")
            except Exception as e:
                logger.warning(f"Storage download failed: {e}")
                # Fall back to checking if raw rows exist
                raw_rows = await conn.fetch(
                    """
                    SELECT row_index, raw_data
                    FROM intake.simplicity_raw_rows
                    WHERE batch_id = $1
                    ORDER BY row_index
                    """,
                    str(batch_id),
                )
                if raw_rows:
                    logger.info(f"Found {len(raw_rows)} raw rows in staging")
                else:
                    raise ValueError(f"No CSV content found for batch {batch_id}") from e

            # Parse CSV
            if csv_content:
                try:
                    df = pd.read_csv(
                        io.BytesIO(csv_content),
                        dtype=str,
                        keep_default_na=False,
                    )
                except Exception as e:
                    await self._fail_batch(conn, batch_id, f"CSV parse error: {e}")
                    raise ValueError(f"Failed to parse CSV: {e}") from e

                # Normalize headers
                header_map = normalize_headers(list(df.columns))
                logger.info(f"Header mapping: {header_map}")

                # Store raw rows for audit
                for row_idx, (_, row) in enumerate(df.iterrows()):
                    row_dict = row.to_dict()
                    await conn.execute(
                        """
                        INSERT INTO intake.simplicity_raw_rows
                            (batch_id, row_index, raw_data)
                        VALUES ($1, $2, $3::jsonb)
                        ON CONFLICT (batch_id, row_index) DO NOTHING
                        """,
                        str(batch_id),
                        row_idx,
                        row_dict,
                    )
            else:
                # Use pre-staged raw rows
                df = None
                header_map = {}

            # Capture parse duration
            parse_duration_ms = int((time.perf_counter() - parse_start) * 1000)
            logger.info(f"Parse phase complete: {parse_duration_ms}ms")

            # Update status to validating
            await conn.execute(
                """
                UPDATE intake.simplicity_batches
                SET status = 'transforming', transformed_at = NOW()
                WHERE id = $1
                """,
                str(batch_id),
            )

            # =================================================================
            # PHASE 1: VALIDATE ALL ROWS (no inserts yet)
            # This allows us to check error budget BEFORE committing any data
            # =================================================================
            valid_rows: list[tuple[int, dict[str, Any], dict[str, Any]]] = (
                []
            )  # (row_idx, raw_data, normalized)
            invalid_rows: list[tuple[int, str, str, dict[str, Any]]] = (
                []
            )  # (row_idx, code, msg, raw_data)
            errors: list[dict[str, Any]] = []

            # Get raw rows to process
            raw_rows = await conn.fetch(
                """
                SELECT row_index, raw_data
                FROM intake.simplicity_raw_rows
                WHERE batch_id = $1
                ORDER BY row_index
                """,
                str(batch_id),
            )

            for raw_row in raw_rows:
                row_idx = raw_row["row_index"]
                raw_data = raw_row["raw_data"]

                validation_result = self._validate_row(raw_data, header_map)

                if validation_result["valid"]:
                    valid_rows.append((row_idx, raw_data, validation_result["normalized"]))
                else:
                    invalid_rows.append(
                        (
                            row_idx,
                            validation_result["error_code"],
                            validation_result["error_message"],
                            raw_data,
                        )
                    )
                    if len(errors) < 20:  # Keep first 20 errors
                        errors.append(
                            {
                                "row_index": row_idx,
                                "error": validation_result["error_message"],
                                "raw_data": raw_data,
                            }
                        )

            # Capture validation duration (part of parse phase)
            parse_duration_ms = int((time.perf_counter() - parse_start) * 1000)
            logger.info(
                f"Validation phase complete: {parse_duration_ms}ms, {len(valid_rows)} valid, {len(invalid_rows)} invalid"
            )

            # =================================================================
            # ERROR BUDGET CHECK (BEFORE any inserts)
            # If error rate exceeds threshold, fail the batch entirely
            # =================================================================
            error_threshold = batch["error_threshold_percent"]
            total_rows = len(raw_rows)
            rejection_reason: str | None = None

            if total_rows > 0:
                error_rate = (len(invalid_rows) / total_rows) * 100
                if error_rate > error_threshold:
                    rejection_reason = (
                        f"Error rate {error_rate:.1f}% exceeded limit {error_threshold}%"
                    )
                    logger.warning(
                        f"Batch {batch_id} REJECTED: {rejection_reason} "
                        f"({len(invalid_rows)}/{total_rows} rows failed validation)"
                    )

                    # Record all validation errors before failing
                    for row_idx, error_code, error_message, raw_data in invalid_rows:
                        await self._record_row_error(
                            conn, batch_id, row_idx, error_code, error_message, raw_data
                        )

                    # Update batch with rejection (NO inserts happened)
                    await conn.execute(
                        """
                        UPDATE intake.simplicity_batches
                        SET status = 'failed',
                            row_count_staged = $2,
                            row_count_valid = 0,
                            row_count_invalid = $3,
                            row_count_inserted = 0,
                            row_count_duplicate = 0,
                            plaintiff_inserted = 0,
                            plaintiff_duplicate = 0,
                            plaintiff_failed = 0,
                            rejection_reason = $4,
                            parse_duration_ms = $5,
                            db_duration_ms = 0,
                            completed_at = NOW(),
                            error_summary = $6
                        WHERE id = $1
                        """,
                        str(batch_id),
                        total_rows,
                        len(invalid_rows),
                        rejection_reason,
                        parse_duration_ms,
                        rejection_reason,
                    )

                    return BatchProcessResult(
                        batch_id=batch_id,
                        status="failed",
                        rows_processed=total_rows,
                        rows_inserted=0,
                        rows_skipped=0,
                        rows_failed=len(invalid_rows),
                        errors=errors,
                    )

            # Record validation errors (but continue processing valid rows)
            for row_idx, error_code, error_message, raw_data in invalid_rows:
                await self._record_row_error(
                    conn, batch_id, row_idx, error_code, error_message, raw_data
                )

            # =================================================================
            # PHASE 2: INSERT VALID ROWS (error budget passed)
            # =================================================================
            rows_inserted = 0
            rows_skipped = 0
            rows_failed_insert = 0
            plaintiffs_inserted = 0
            plaintiffs_duplicate = 0
            plaintiffs_failed = 0

            # Start DB phase timing
            db_start = time.perf_counter()

            for row_idx, raw_data, normalized in valid_rows:
                try:
                    plaintiff_id, plaintiff_inserted_flag = await self._insert_plaintiff(
                        conn,
                        batch_id,
                        row_idx,
                        normalized,
                        batch_file_hash,
                    )
                    if plaintiff_inserted_flag:
                        plaintiffs_inserted += 1
                    else:
                        plaintiffs_duplicate += 1
                except Exception as e:
                    plaintiffs_failed += 1
                    rows_failed_insert += 1
                    error_msg = f"Plaintiff insert failed: {e}"
                    logger.warning(f"Row {row_idx} plaintiff insert failed: {error_msg}")
                    await self._record_row_error(
                        conn,
                        batch_id,
                        row_idx,
                        "PLAINTIFF_INSERT_ERROR",
                        error_msg,
                        raw_data,
                    )
                    if len(errors) < 20:
                        errors.append(
                            {"row_index": row_idx, "error": error_msg, "raw_data": raw_data}
                        )
                    continue

                try:
                    result = await self._insert_judgment(
                        conn, batch_id, row_idx, normalized, plaintiff_id
                    )

                    if result == "inserted":
                        rows_inserted += 1
                    elif result == "skipped":
                        rows_skipped += 1
                    else:
                        rows_failed_insert += 1

                except Exception as e:
                    rows_failed_insert += 1
                    error_msg = str(e)
                    logger.warning(f"Row {row_idx} insert failed: {error_msg}")
                    await self._record_row_error(
                        conn, batch_id, row_idx, "INSERT_ERROR", error_msg, raw_data
                    )
                    if len(errors) < 20:
                        errors.append(
                            {"row_index": row_idx, "error": error_msg, "raw_data": raw_data}
                        )

            # Capture DB duration
            db_duration_ms = int((time.perf_counter() - db_start) * 1000)
            logger.info(
                f"Insert phase complete: {db_duration_ms}ms, {rows_inserted} inserted, {rows_skipped} skipped"
            )

            # Total failed = validation + insert failures
            rows_failed = len(invalid_rows) + rows_failed_insert
            rows_processed = total_rows

            # Determine final status
            if rows_failed == 0:
                final_status = "completed"
            elif rows_inserted > 0:
                final_status = "completed"  # Partial success still completes
            else:
                final_status = "failed"

            # Update batch with final counts and timing
            await conn.execute(
                """
                UPDATE intake.simplicity_batches
                SET status = $2,
                    row_count_staged = $3,
                    row_count_valid = $4,
                    row_count_invalid = $5,
                    row_count_inserted = $6,
                    row_count_duplicate = $7,
                    parse_duration_ms = $8,
                    db_duration_ms = $9,
                    completed_at = NOW(),
                    error_summary = $10,
                    plaintiff_inserted = $11,
                    plaintiff_duplicate = $12,
                    plaintiff_failed = $13
                WHERE id = $1
                """,
                str(batch_id),
                final_status,
                rows_processed,
                rows_inserted + rows_skipped,
                rows_failed,
                rows_inserted,
                rows_skipped,
                parse_duration_ms,
                db_duration_ms,
                f"{rows_failed} errors" if rows_failed > 0 else None,
                plaintiffs_inserted,
                plaintiffs_duplicate,
                plaintiffs_failed,
            )

            # Calculate duration
            duration_seconds: float | None = None
            batch_info = await conn.fetchrow(
                "SELECT filename, created_at, completed_at FROM intake.simplicity_batches WHERE id = $1",
                str(batch_id),
            )
            if batch_info and batch_info["completed_at"] and batch_info["created_at"]:
                duration_seconds = (
                    batch_info["completed_at"] - batch_info["created_at"]
                ).total_seconds()

            logger.info(
                f"Batch {batch_id} {final_status}: "
                f"{rows_processed} processed, {rows_inserted} inserted, "
                f"{rows_skipped} skipped, {rows_failed} failed"
            )

            result = BatchProcessResult(
                batch_id=batch_id,
                status=final_status,
                rows_processed=rows_processed,
                rows_inserted=rows_inserted,
                rows_skipped=rows_skipped,
                rows_failed=rows_failed,
                plaintiffs_inserted=plaintiffs_inserted,
                plaintiffs_duplicate=plaintiffs_duplicate,
                plaintiffs_failed=plaintiffs_failed,
                errors=errors,
            )

            # Send Discord notification
            await self._send_discord_notification(
                result,
                batch_info["filename"] if batch_info else str(batch_id),
                duration_seconds,
            )

            # Mark as notified
            await conn.execute(
                "UPDATE intake.simplicity_batches SET discord_notified = true WHERE id = $1",
                str(batch_id),
            )

            return result

    async def _process_row(
        self,
        conn: Any,
        batch_id: UUID,
        row_idx: int,
        raw_data: dict[str, Any],
        header_map: dict[str, str],
    ) -> str:
        """
        Process a single row: validate, dedupe, insert.

        Returns:
            'inserted', 'skipped', or 'failed'
        """
        # Normalize raw data using header map
        normalized: dict[str, Any] = {}
        for raw_key, value in raw_data.items():
            canonical = header_map.get(raw_key) or normalize_header(raw_key)
            if canonical:
                normalized[canonical] = value

        # Extract required fields
        case_number = normalized.get("case_number")
        defendant = normalized.get("defendant_name")
        amount_raw = normalized.get("judgment_amount")
        plaintiff_raw = normalized.get("plaintiff_name")

        # Validate required: File #, Defendant, Amount
        validation_errors: list[str] = []

        if not case_number or not str(case_number).strip():
            validation_errors.append("Missing required field: case_number/File #")

        if not defendant or not str(defendant).strip():
            validation_errors.append("Missing required field: defendant_name")

        if not amount_raw:
            validation_errors.append("Missing required field: judgment_amount")

        if validation_errors:
            # Record validation error
            await self._record_row_error(
                conn,
                batch_id,
                row_idx,
                "VALIDATION_FAILED",
                "; ".join(validation_errors),
                raw_data,
            )
            return "failed"

        # Parse fields
        case_number = str(case_number).strip().upper()
        defendant = str(defendant).strip()
        defendant_normalized = normalize_defendant(defendant)
        amount = parse_amount(amount_raw)

        if amount is None:
            await self._record_row_error(
                conn,
                batch_id,
                row_idx,
                "INVALID_AMOUNT",
                f"Could not parse amount: {amount_raw}",
                raw_data,
            )
            return "failed"

        # Optional fields
        plaintiff = normalized.get("plaintiff_name")
        if plaintiff:
            plaintiff = str(plaintiff).strip()

        entry_date = parse_date(normalized.get("judgment_date"))
        court = normalized.get("court")
        if court:
            court = str(court).strip()

        county = normalized.get("county")
        if county:
            county = str(county).strip()

        # Build dedupe key (for future: compound key matching)
        # Currently we just check case_number, but the key allows defendant matching
        _ = build_dedupe_key(case_number, defendant_normalized)  # noqa: F841

        # Use idempotent RPC: insert_or_get_judgment
        # This handles race conditions and returns (id, was_inserted)
        try:
            result = await conn.fetchrow(
                """
                SELECT * FROM public.insert_or_get_judgment(
                    $1, $2, $3, $4, $5, $6, $7, $8
                )
                """,
                case_number,
                plaintiff,
                defendant,
                amount,
                entry_date,
                court,
                county,
                f"batch:{batch_id}",
            )

            if result and result["was_inserted"]:
                logger.debug(f"Row {row_idx}: Inserted judgment {result['id']}")
                return "inserted"
            else:
                logger.debug(f"Row {row_idx}: Skipped duplicate case_number {case_number}")
                return "skipped"

        except Exception as e:
            await self._record_row_error(
                conn,
                batch_id,
                row_idx,
                "INSERT_FAILED",
                str(e),
                raw_data,
            )
            return "failed"

    def _validate_row(
        self,
        raw_data: dict[str, Any],
        header_map: dict[str, str],
    ) -> dict[str, Any]:
        """
        Validate a single row without inserting.

        Returns:
            {"valid": True, "normalized": {...}} or
            {"valid": False, "error_code": "...", "error_message": "..."}
        """
        # Normalize raw data using header map
        normalized: dict[str, Any] = {}
        for raw_key, value in raw_data.items():
            canonical = header_map.get(raw_key) or normalize_header(raw_key)
            if canonical:
                normalized[canonical] = value

        # Extract required fields
        case_number = normalized.get("case_number")
        defendant = normalized.get("defendant_name")
        amount_raw = normalized.get("judgment_amount")
        plaintiff_raw = normalized.get("plaintiff_name")

        # Validate required: File #, Defendant, Amount
        validation_errors: list[str] = []

        if not case_number or not str(case_number).strip():
            validation_errors.append("Missing: case_number")

        if not defendant or not str(defendant).strip():
            validation_errors.append("Missing: defendant_name")

        if not plaintiff_raw or not str(plaintiff_raw).strip():
            validation_errors.append("Missing: plaintiff_name")

        if not amount_raw:
            validation_errors.append("Missing: judgment_amount")

        if validation_errors:
            return {
                "valid": False,
                "error_code": "VALIDATION_FAILED",
                "error_message": "; ".join(validation_errors),
            }

        # Parse fields
        case_number = str(case_number).strip().upper()
        defendant = str(defendant).strip()
        defendant_normalized = normalize_defendant(defendant)
        amount = parse_amount(amount_raw)

        if amount is None:
            return {
                "valid": False,
                "error_code": "INVALID_AMOUNT",
                "error_message": f"Could not parse amount: {amount_raw}",
            }

        # Optional fields
        plaintiff = str(plaintiff_raw).strip() if plaintiff_raw else None

        entry_date = parse_date(normalized.get("judgment_date"))
        court = normalized.get("court")
        if court:
            court = str(court).strip()

        county = normalized.get("county")
        if county:
            county = str(county).strip()

        # Build normalized record for insert
        return {
            "valid": True,
            "normalized": {
                "case_number": case_number,
                "defendant_name": defendant,
                "defendant_normalized": defendant_normalized,
                "plaintiff_name": plaintiff,
                "judgment_amount": amount,
                "judgment_date": entry_date,
                "court": court,
                "county": county,
            },
        }

    async def _insert_judgment(
        self,
        conn: Any,
        batch_id: UUID,
        row_idx: int,
        normalized: dict[str, Any],
        plaintiff_id: int | None = None,
    ) -> str:
        """
        Insert a validated row to public.judgments.

        Returns:
            'inserted', 'skipped', or 'failed'
        """
        try:
            result = await conn.fetchrow(
                """
                SELECT * FROM public.insert_or_get_judgment(
                    $1, $2, $3, $4, $5, $6, $7, $8, $9
                )
                """,
                normalized["case_number"],
                normalized.get("plaintiff_name"),
                normalized["defendant_name"],
                normalized["judgment_amount"],
                normalized.get("judgment_date"),
                normalized.get("court"),
                normalized.get("county"),
                f"batch:{batch_id}",
                plaintiff_id,
            )

            if result and result["was_inserted"]:
                logger.debug(f"Row {row_idx}: Inserted judgment {result['id']}")
                return "inserted"
            else:
                logger.debug(
                    f"Row {row_idx}: Skipped duplicate case_number {normalized['case_number']}"
                )
                return "skipped"

        except Exception as e:
            logger.warning(f"Row {row_idx} insert failed: {e}")
            raise

    async def _insert_plaintiff(
        self,
        conn: Any,
        batch_id: UUID,
        row_idx: int,
        normalized: dict[str, Any],
        file_hash: str | None,
    ) -> tuple[int, bool]:
        """Insert or reuse a plaintiff record for the current row."""
        name = normalized.get("plaintiff_name")
        if not name:
            raise ValueError("Missing plaintiff_name")

        source_system = normalized.get("source_system") or "simplicity"

        result = await conn.fetchrow(
            """
            SELECT * FROM public.insert_or_get_plaintiff(
                $1, $2, $3, $4, $5
            )
            """,
            name,
            source_system,
            str(batch_id),
            row_idx,
            file_hash,
        )

        if not result:
            raise ValueError("insert_or_get_plaintiff returned no result")

        return int(result["id"]), bool(result["was_inserted"])

    async def _record_row_error(
        self,
        conn: Any,
        batch_id: UUID,
        row_idx: int,
        error_code: str,
        error_message: str,
        raw_data: dict[str, Any],
    ) -> None:
        """Record an error for a failed row."""
        try:
            await conn.execute(
                """
                INSERT INTO intake.simplicity_failed_rows (
                    batch_id,
                    row_index,
                    error_stage,
                    error_code,
                    error_message,
                    raw_data
                ) VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                """,
                str(batch_id),
                row_idx,
                "validate",  # error_stage
                error_code,
                error_message,
                raw_data,
            )
        except Exception as e:
            logger.error(f"Failed to record row error: {e}")

    async def _fail_batch(
        self,
        conn: Any,
        batch_id: UUID,
        error_summary: str,
    ) -> None:
        """Mark a batch as failed."""
        await conn.execute(
            """
            UPDATE intake.simplicity_batches
            SET status = 'failed',
                error_summary = $2,
                completed_at = NOW()
            WHERE id = $1
            """,
            str(batch_id),
            error_summary,
        )

    async def _send_discord_notification(
        self,
        result: BatchProcessResult,
        filename: str,
        duration_seconds: float | None = None,
    ) -> None:
        """Send Discord notification for batch completion."""
        try:
            from .discord_service import DiscordService

            async with DiscordService() as discord:
                if not discord.is_configured:
                    logger.debug("Discord webhook not configured, skipping notification")
                    return

                message = result.to_discord_summary(filename, duration_seconds)
                success = await discord.send_message(
                    content=message,
                    username="Dragonfly Intake",
                )
                if success:
                    logger.info(f"Discord notification sent for batch {result.batch_id}")
                else:
                    logger.warning(
                        f"Failed to send Discord notification for batch {result.batch_id}"
                    )

        except ImportError:
            logger.debug("Discord service not available")
        except Exception as e:
            logger.warning(f"Discord notification failed: {e}")

    async def get_batch_status(self, batch_id: UUID) -> dict[str, Any] | None:
        """Get current status of a batch."""
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    id,
                    filename,
                    status,
                    row_count_total,
                    row_count_staged,
                    row_count_valid,
                    row_count_invalid,
                    row_count_inserted,
                    error_summary,
                    created_at,
                    staged_at,
                    transformed_at,
                    completed_at
                FROM intake.simplicity_batches
                WHERE id = $1
                """,
                str(batch_id),
            )

            if not row:
                return None

            return dict(row)

    async def get_batch_errors(
        self,
        batch_id: UUID,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get errors for a batch."""
        async with get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    row_index,
                    error_code,
                    error_message,
                    raw_data,
                    created_at
                FROM intake.simplicity_failed_rows
                WHERE batch_id = $1
                ORDER BY row_index
                LIMIT $2
                """,
                str(batch_id),
                limit,
            )

            return [dict(row) for row in rows]


# =============================================================================
# MODULE-LEVEL CONVENIENCE FUNCTIONS
# =============================================================================

# Singleton instance for convenience
_service: IngestionService | None = None


def get_ingestion_service() -> IngestionService:
    """Get or create the singleton IngestionService instance."""
    global _service
    if _service is None:
        _service = IngestionService()
    return _service


async def create_batch(
    file: UploadFile,
    filename: str | None = None,
    force: bool = False,
) -> BatchCreateResult:
    """Convenience function to create a batch."""
    return await get_ingestion_service().create_batch(file, filename, force=force)


async def process_batch(batch_id: UUID, *, force: bool = False) -> BatchProcessResult:
    """Convenience function to process a batch."""
    return await get_ingestion_service().process_batch(batch_id, force=force)
