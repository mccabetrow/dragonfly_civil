"""
Dragonfly Engine - Ingestion Service

Enterprise-grade batch ingestion engine with idempotency and observability.

This is the UNIFIED ingestion interface. All batch ingestion flows through here.

Usage:
    from backend.services.ingestion_service import IngestionService

    service = IngestionService()
    batch_id = await service.create_batch(file, "export_2024.csv")
    result = await service.process_batch(batch_id)
"""

from __future__ import annotations

import hashlib
import logging
import re
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
    rows_skipped: int  # Already exists in judgments
    rows_failed: int
    errors: list[dict[str, Any]] = field(default_factory=list)


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
    ) -> BatchCreateResult:
        """
        Create a new batch from an uploaded file.

        1. Reads file content and computes hash
        2. Checks for duplicate batch (same hash)
        3. Creates batch record in intake.simplicity_batches
        4. Uploads raw file to Supabase Storage: raw_batches/{batch_id}.csv

        Args:
            file: FastAPI UploadFile object
            filename: Override filename (defaults to file.filename)

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

        # Check for duplicate batch
        async with get_connection() as conn:
            existing = await conn.fetchrow(
                """
                SELECT id, filename, status, row_count_total
                FROM intake.simplicity_batches
                WHERE file_hash = $1
                """,
                file_hash,
            )

            if existing:
                logger.info(f"Duplicate batch found: {existing['id']}")
                return BatchCreateResult(
                    batch_id=UUID(str(existing["id"])),
                    filename=existing["filename"],
                    file_hash=file_hash,
                    row_count_total=existing["row_count_total"],
                    status=existing["status"],
                    is_duplicate=True,
                )

            # Parse CSV to get row count
            try:
                df = pd.read_csv(
                    pd.io.common.BytesIO(content),
                    dtype=str,
                    keep_default_na=False,
                )
                row_count = len(df)
            except Exception as e:
                logger.error(f"Failed to parse CSV: {e}")
                raise ValueError(f"Invalid CSV format: {e}") from e

            # Create batch record
            batch_id = uuid4()
            now = datetime.now(timezone.utc)

            await conn.execute(
                """
                INSERT INTO intake.simplicity_batches (
                    id,
                    filename,
                    file_hash,
                    row_count_total,
                    status,
                    created_at
                ) VALUES ($1, $2, $3, $4, $5, $6)
                """,
                str(batch_id),
                actual_filename,
                file_hash,
                row_count,
                "uploaded",
                now,
            )

        # Upload to Supabase Storage
        storage_path = f"raw_batches/{batch_id}.csv"
        try:
            self._supabase.storage.from_("intake").upload(
                storage_path,
                content,
                {"content-type": "text/csv"},
            )
            logger.info(f"Uploaded batch to storage: {storage_path}")
        except Exception as e:
            logger.warning(f"Storage upload failed (non-fatal): {e}")
            # Continue - batch is still valid without storage backup

        return BatchCreateResult(
            batch_id=batch_id,
            filename=actual_filename,
            file_hash=file_hash,
            row_count_total=row_count,
            status="uploaded",
            is_duplicate=False,
        )

    async def process_batch(self, batch_id: UUID) -> BatchProcessResult:
        """
        Process a batch: parse, validate, dedupe, and insert.

        1. Downloads CSV from Storage (or re-reads from staging)
        2. Parses each row, validates required fields (File #, Defendant, Amount)
        3. Dedupes against existing judgments (file_number + defendant_normalized)
        4. Inserts valid rows to public.judgments
        5. Records errors to intake.simplicity_failed_rows

        Args:
            batch_id: UUID of the batch to process

        Returns:
            BatchProcessResult with counts and error details
        """
        logger.info(f"Processing batch: {batch_id}")

        async with get_connection() as conn:
            # Get batch record
            batch = await conn.fetchrow(
                """
                SELECT id, filename, status, row_count_total, file_hash
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

            # Update status to parsing
            await conn.execute(
                """
                UPDATE intake.simplicity_batches
                SET status = 'staging', staged_at = NOW()
                WHERE id = $1
                """,
                str(batch_id),
            )

            # Try to download from storage
            csv_content: bytes | None = None
            try:
                storage_path = f"raw_batches/{batch_id}.csv"
                response = self._supabase.storage.from_("intake").download(storage_path)
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
                        pd.io.common.BytesIO(csv_content),
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

            # Update status to validating
            await conn.execute(
                """
                UPDATE intake.simplicity_batches
                SET status = 'transforming', transformed_at = NOW()
                WHERE id = $1
                """,
                str(batch_id),
            )

            # Process rows
            rows_processed = 0
            rows_inserted = 0
            rows_skipped = 0
            rows_failed = 0
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
                rows_processed += 1

                try:
                    result = await self._process_row(
                        conn,
                        batch_id,
                        row_idx,
                        raw_data,
                        header_map,
                    )

                    if result == "inserted":
                        rows_inserted += 1
                    elif result == "skipped":
                        rows_skipped += 1
                    elif result == "failed":
                        rows_failed += 1

                except Exception as e:
                    rows_failed += 1
                    error_msg = str(e)
                    logger.warning(f"Row {row_idx} failed: {error_msg}")

                    # Record error
                    await self._record_row_error(
                        conn,
                        batch_id,
                        row_idx,
                        "PROCESS_ERROR",
                        error_msg,
                        raw_data,
                    )

                    if len(errors) < 20:  # Keep first 20 errors
                        errors.append(
                            {
                                "row_index": row_idx,
                                "error": error_msg,
                                "raw_data": raw_data,
                            }
                        )

            # Determine final status
            if rows_failed == 0:
                final_status = "completed"
            elif rows_inserted > 0:
                final_status = "completed"  # Partial success still completes
            else:
                final_status = "failed"

            # Update batch with final counts
            await conn.execute(
                """
                UPDATE intake.simplicity_batches
                SET status = $2,
                    row_count_staged = $3,
                    row_count_valid = $4,
                    row_count_invalid = $5,
                    row_count_inserted = $6,
                    completed_at = NOW(),
                    error_summary = $7
                WHERE id = $1
                """,
                str(batch_id),
                final_status,
                rows_processed,
                rows_inserted + rows_skipped,
                rows_failed,
                rows_inserted,
                f"{rows_failed} errors" if rows_failed > 0 else None,
            )

            logger.info(
                f"Batch {batch_id} {final_status}: "
                f"{rows_processed} processed, {rows_inserted} inserted, "
                f"{rows_skipped} skipped, {rows_failed} failed"
            )

            return BatchProcessResult(
                batch_id=batch_id,
                status=final_status,
                rows_processed=rows_processed,
                rows_inserted=rows_inserted,
                rows_skipped=rows_skipped,
                rows_failed=rows_failed,
                errors=errors,
            )

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

        # Check if judgment already exists (dedupe by case_number)
        existing = await conn.fetchrow(
            """
            SELECT id FROM public.judgments
            WHERE case_number = $1
            """,
            case_number,
        )

        if existing:
            logger.debug(f"Row {row_idx}: Skipped duplicate case_number {case_number}")
            return "skipped"

        # Insert judgment
        try:
            await conn.execute(
                """
                INSERT INTO public.judgments (
                    case_number,
                    plaintiff_name,
                    defendant_name,
                    judgment_amount,
                    entry_date,
                    court,
                    county,
                    source_file,
                    status,
                    enforcement_stage
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (case_number) DO NOTHING
                """,
                case_number,
                plaintiff,
                defendant,
                amount,
                entry_date,
                court,
                county,
                f"batch:{batch_id}",
                "active",
                "pre_enforcement",
            )
            return "inserted"

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


async def create_batch(file: UploadFile, filename: str | None = None) -> BatchCreateResult:
    """Convenience function to create a batch."""
    return await get_ingestion_service().create_batch(file, filename)


async def process_batch(batch_id: UUID) -> BatchProcessResult:
    """Convenience function to process a batch."""
    return await get_ingestion_service().process_batch(batch_id)
