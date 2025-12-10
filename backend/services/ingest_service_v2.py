"""
Dragonfly Engine - Ingest Service v2

Enterprise-grade batch-based ingestion pipeline for Simplicity CSV uploads.
Handles parsing, validation, staging, and processing with full audit trail.

Version: v0.2.x
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import pandas as pd
from fastapi import UploadFile
from pydantic import BaseModel, Field, field_validator

from ..db import get_connection, get_supabase_client
from .notifications import notify_batch_completed, notify_batch_failed

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models
# =============================================================================


class SimplicityRow(BaseModel):
    """
    Normalized row from a Simplicity CSV export.

    All fields are validated and normalized for downstream processing.
    """

    plaintiff_name: str = Field(..., min_length=1, max_length=500)
    defendant_name: str = Field(..., min_length=1, max_length=500)
    case_number: str = Field(..., min_length=1, max_length=100)
    judgment_amount: Decimal = Field(..., ge=0)
    judgment_date: date
    court: str = Field(..., min_length=1, max_length=200)
    county: str | None = Field(default=None, max_length=100)
    source_batch: str | None = Field(default=None, max_length=200)

    @field_validator("case_number", mode="before")
    @classmethod
    def normalize_case_number(cls, v: Any) -> str:
        """Normalize case number: trim whitespace, uppercase."""
        if v is None:
            raise ValueError("case_number is required")
        return str(v).strip().upper()

    @field_validator("plaintiff_name", "defendant_name", "court", mode="before")
    @classmethod
    def normalize_text(cls, v: Any) -> str:
        """Normalize text fields: trim whitespace."""
        if v is None:
            raise ValueError("Field is required")
        return str(v).strip()

    @field_validator("judgment_amount", mode="before")
    @classmethod
    def parse_amount(cls, v: Any) -> Decimal:
        """Parse monetary amounts, handling currency symbols and commas."""
        if v is None:
            raise ValueError("judgment_amount is required")

        if isinstance(v, (int, float, Decimal)):
            return Decimal(str(v))

        # String parsing: remove $, commas, whitespace
        s = str(v).strip()
        s = re.sub(r"[$,\s]", "", s)

        # Handle parentheses for negative (accounting format)
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]

        try:
            return Decimal(s)
        except InvalidOperation:
            raise ValueError(f"Cannot parse amount: {v}")

    @field_validator("judgment_date", mode="before")
    @classmethod
    def parse_date(cls, v: Any) -> date:
        """Parse dates from various formats."""
        if v is None:
            raise ValueError("judgment_date is required")

        if isinstance(v, date):
            return v

        if isinstance(v, datetime):
            return v.date()

        # Pandas Timestamp
        if hasattr(v, "date"):
            return v.date()

        s = str(v).strip()
        if not s:
            raise ValueError("judgment_date is required")

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

        raise ValueError(f"Cannot parse date: {v}")


@dataclass
class ParsedBatchResult:
    """Result from parsing a CSV batch."""

    batch_id: UUID
    row_count_raw: int
    row_count_valid: int
    row_count_invalid: int
    errors_preview: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProcessResult:
    """Result from processing a batch."""

    batch_id: UUID
    status: str  # 'completed' or 'failed'
    rows_processed: int
    rows_inserted: int
    rows_updated: int
    rows_skipped: int
    error_summary: str | None = None


# =============================================================================
# Header Normalization
# =============================================================================

# Known header variants → canonical name
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
    # Case number
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


def normalize_headers(headers: list[str]) -> dict[int, str]:
    """
    Normalize CSV headers to canonical column names.

    Args:
        headers: List of raw header strings from CSV

    Returns:
        Dict mapping column index → canonical column name.
        Only recognized columns are included.
    """
    result: dict[int, str] = {}

    for idx, header in enumerate(headers):
        # Normalize: lowercase, trim, replace spaces/dashes with underscore
        normalized = header.lower().strip().replace(" ", "_").replace("-", "_")

        # Look up in variants map
        if normalized in HEADER_VARIANTS:
            canonical = HEADER_VARIANTS[normalized]
            # Only add if not already mapped (first match wins)
            if canonical not in result.values():
                result[idx] = canonical

    return result


# =============================================================================
# CSV Parsing
# =============================================================================


async def parse_simplicity_csv(
    batch_id: UUID,
    file: UploadFile,
) -> ParsedBatchResult:
    """
    Parse a Simplicity CSV file and store in staging tables.

    1. Reads CSV into DataFrame
    2. Stores raw rows as JSONB in staging_simplicity_raw
    3. Normalizes and validates each row
    4. Stores clean rows in staging_simplicity_clean

    Args:
        batch_id: UUID of the batch record
        file: Uploaded CSV file

    Returns:
        ParsedBatchResult with counts and error preview
    """
    logger.info(f"Parsing CSV for batch {batch_id}: {file.filename}")

    # Read CSV content
    content = await file.read()
    await file.seek(0)  # Reset for potential re-read

    try:
        # Read as DataFrame, all columns as string initially
        df = pd.read_csv(
            pd.io.common.BytesIO(content),
            dtype=str,
            keep_default_na=False,
        )
    except Exception as e:
        logger.error(f"Failed to parse CSV: {e}")
        raise ValueError(f"Invalid CSV format: {e}")

    if df.empty:
        logger.warning(f"Empty CSV for batch {batch_id}")
        return ParsedBatchResult(
            batch_id=batch_id,
            row_count_raw=0,
            row_count_valid=0,
            row_count_invalid=0,
        )

    # Normalize headers
    header_map = normalize_headers(list(df.columns))
    logger.info(f"Header mapping: {header_map}")

    row_count_raw = len(df)
    row_count_valid = 0
    row_count_invalid = 0
    errors_preview: list[dict[str, Any]] = []

    async with get_connection() as conn:
        async with conn.transaction():
            for row_idx, (_, row) in enumerate(df.iterrows()):
                row_dict = row.to_dict()

                # Store raw row as JSONB
                await conn.execute(
                    """
                    INSERT INTO judgments.staging_simplicity_raw
                        (batch_id, row_index, raw_json)
                    VALUES ($1, $2, $3)
                    """,
                    str(batch_id),
                    row_idx,
                    row_dict,
                )

                # Build normalized row using header map
                normalized_data: dict[str, Any] = {}
                for col_idx, canonical_name in header_map.items():
                    col_name = df.columns[col_idx]
                    value = row_dict.get(col_name)
                    if value and str(value).strip():
                        normalized_data[canonical_name] = value

                # Try to validate with Pydantic
                validation_errors: list[str] = []
                clean_row: SimplicityRow | None = None

                try:
                    # Set source_batch
                    normalized_data["source_batch"] = str(batch_id)

                    # Provide defaults for optional fields
                    if "county" not in normalized_data:
                        normalized_data["county"] = None

                    clean_row = SimplicityRow(**normalized_data)

                except Exception as e:
                    # Collect validation errors
                    error_msg = str(e)
                    validation_errors.append(error_msg)

                # Determine status
                if clean_row and not validation_errors:
                    validation_status = "valid"
                    row_count_valid += 1
                else:
                    validation_status = "invalid"
                    row_count_invalid += 1

                    # Keep first 10 errors for preview
                    if len(errors_preview) < 10:
                        errors_preview.append(
                            {
                                "row_index": row_idx,
                                "errors": validation_errors,
                                "raw_data": {k: v for k, v in row_dict.items() if v},
                            }
                        )

                # Insert into clean staging table
                await conn.execute(
                    """
                    INSERT INTO judgments.staging_simplicity_clean (
                        batch_id, row_index,
                        plaintiff_name, defendant_name, case_number,
                        judgment_amount, judgment_date, court, county,
                        source_batch, validation_status, validation_errors
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
                    )
                    """,
                    str(batch_id),
                    row_idx,
                    clean_row.plaintiff_name if clean_row else None,
                    clean_row.defendant_name if clean_row else None,
                    clean_row.case_number if clean_row else None,
                    float(clean_row.judgment_amount) if clean_row else None,
                    clean_row.judgment_date if clean_row else None,
                    clean_row.court if clean_row else None,
                    clean_row.county if clean_row else None,
                    str(batch_id),
                    validation_status,
                    validation_errors if validation_errors else None,
                )

    logger.info(
        f"Batch {batch_id} parsed: {row_count_raw} raw, "
        f"{row_count_valid} valid, {row_count_invalid} invalid"
    )

    return ParsedBatchResult(
        batch_id=batch_id,
        row_count_raw=row_count_raw,
        row_count_valid=row_count_valid,
        row_count_invalid=row_count_invalid,
        errors_preview=errors_preview,
    )


# =============================================================================
# Batch Processing
# =============================================================================


async def process_simplicity_batch(batch_id: UUID) -> ProcessResult:
    """
    Process a parsed batch: upsert valid rows into canonical table.

    This function is idempotent - reprocessing won't duplicate rows.
    Uses (case_number, court) as uniqueness key.

    Args:
        batch_id: UUID of the batch to process

    Returns:
        ProcessResult with counts and status
    """
    logger.info(f"Processing batch {batch_id}")

    rows_processed = 0
    rows_inserted = 0
    rows_updated = 0
    rows_skipped = 0
    error_summary: str | None = None

    try:
        async with get_connection() as conn:
            # Mark batch as processing
            await conn.execute(
                """
                UPDATE ops.ingest_batches
                SET status = 'processing'
                WHERE id = $1
                """,
                str(batch_id),
            )

            # Fetch valid rows
            valid_rows = await conn.fetch(
                """
                SELECT
                    case_number, court, plaintiff_name, defendant_name,
                    judgment_amount, judgment_date, county
                FROM judgments.staging_simplicity_clean
                WHERE batch_id = $1 AND validation_status = 'valid'
                ORDER BY row_index
                """,
                str(batch_id),
            )

            async with conn.transaction():
                for row in valid_rows:
                    rows_processed += 1

                    # Upsert into canonical table
                    # ON CONFLICT updates if different, otherwise skips
                    result = await conn.execute(
                        """
                        INSERT INTO judgments.imported_simplicity_cases (
                            case_number, court, plaintiff_name, defendant_name,
                            judgment_amount, judgment_date, county, source_batch_id
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        ON CONFLICT (case_number, court) DO UPDATE SET
                            plaintiff_name = EXCLUDED.plaintiff_name,
                            defendant_name = EXCLUDED.defendant_name,
                            judgment_amount = EXCLUDED.judgment_amount,
                            judgment_date = EXCLUDED.judgment_date,
                            county = EXCLUDED.county,
                            source_batch_id = EXCLUDED.source_batch_id,
                            updated_at = now()
                        WHERE (
                            judgments.imported_simplicity_cases.plaintiff_name,
                            judgments.imported_simplicity_cases.defendant_name,
                            judgments.imported_simplicity_cases.judgment_amount,
                            judgments.imported_simplicity_cases.judgment_date,
                            judgments.imported_simplicity_cases.county
                        ) IS DISTINCT FROM (
                            EXCLUDED.plaintiff_name,
                            EXCLUDED.defendant_name,
                            EXCLUDED.judgment_amount,
                            EXCLUDED.judgment_date,
                            EXCLUDED.county
                        )
                        """,
                        row["case_number"],
                        row["court"],
                        row["plaintiff_name"],
                        row["defendant_name"],
                        (float(row["judgment_amount"]) if row["judgment_amount"] else None),
                        row["judgment_date"],
                        row["county"],
                        str(batch_id),
                    )

                    # Parse result to determine action
                    if result:
                        if "INSERT 0 1" in result:
                            rows_inserted += 1
                        elif "UPDATE 1" in result:
                            rows_updated += 1
                        else:
                            rows_skipped += 1

            # Mark batch as completed
            await conn.execute(
                """
                UPDATE ops.ingest_batches
                SET
                    status = 'completed',
                    processed_at = now()
                WHERE id = $1
                """,
                str(batch_id),
            )

        logger.info(
            f"Batch {batch_id} completed: "
            f"{rows_processed} processed, {rows_inserted} inserted, "
            f"{rows_updated} updated, {rows_skipped} skipped"
        )

        # Send success notification
        # Get batch details for notification
        async with get_connection() as conn:
            batch = await conn.fetchrow(
                """
                SELECT source, row_count_valid, row_count_invalid
                FROM ops.ingest_batches WHERE id = $1
                """,
                str(batch_id),
            )
            if batch:
                await notify_batch_completed(
                    batch_id=batch_id,
                    source=batch["source"],
                    row_count_valid=batch["row_count_valid"],
                    row_count_invalid=batch["row_count_invalid"],
                )

        return ProcessResult(
            batch_id=batch_id,
            status="completed",
            rows_processed=rows_processed,
            rows_inserted=rows_inserted,
            rows_updated=rows_updated,
            rows_skipped=rows_skipped,
        )

    except Exception as e:
        error_summary = str(e)[:1000]
        logger.exception(f"Batch {batch_id} failed: {e}")

        # Mark batch as failed
        try:
            async with get_connection() as conn:
                await conn.execute(
                    """
                    UPDATE ops.ingest_batches
                    SET
                        status = 'failed',
                        error_summary = $2,
                        processed_at = now()
                    WHERE id = $1
                    """,
                    str(batch_id),
                    error_summary,
                )

                # Get source for notification
                batch = await conn.fetchrow(
                    "SELECT source FROM ops.ingest_batches WHERE id = $1",
                    str(batch_id),
                )
                if batch:
                    await notify_batch_failed(
                        batch_id=batch_id,
                        source=batch["source"],
                        error_summary=error_summary,
                    )
        except Exception as db_err:
            logger.error(f"Failed to update batch status: {db_err}")

        return ProcessResult(
            batch_id=batch_id,
            status="failed",
            rows_processed=rows_processed,
            rows_inserted=rows_inserted,
            rows_updated=rows_updated,
            rows_skipped=rows_skipped,
            error_summary=error_summary,
        )


# =============================================================================
# Batch Management
# =============================================================================


async def create_batch(
    source: str,
    filename: str,
    created_by: str | None = None,
) -> UUID:
    """
    Create a new ingest batch record.

    Args:
        source: Source system (e.g., 'simplicity')
        filename: Original filename
        created_by: User/API key identifier

    Returns:
        UUID of the new batch
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ops.ingest_batches (source, filename, created_by)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            source,
            filename,
            created_by,
        )
        batch_id = UUID(row["id"]) if row else None

    if not batch_id:
        raise RuntimeError("Failed to create batch record")

    logger.info(f"Created batch {batch_id} for {source}:{filename}")
    return batch_id


async def update_batch_counts(
    batch_id: UUID,
    row_count_raw: int,
    row_count_valid: int,
    row_count_invalid: int,
) -> None:
    """Update batch with parsing results."""
    async with get_connection() as conn:
        await conn.execute(
            """
            UPDATE ops.ingest_batches
            SET
                row_count_raw = $2,
                row_count_valid = $3,
                row_count_invalid = $4
            WHERE id = $1
            """,
            str(batch_id),
            row_count_raw,
            row_count_valid,
            row_count_invalid,
        )


async def get_pending_batches() -> list[UUID]:
    """Get all batches with status='pending'."""
    async with get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT id FROM ops.ingest_batches
            WHERE status = 'pending'
            ORDER BY created_at ASC
            """
        )
    return [UUID(row["id"]) for row in rows]


async def get_batch_details(batch_id: UUID) -> dict[str, Any] | None:
    """Get full batch details."""
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                id, source, filename,
                row_count_raw, row_count_valid, row_count_invalid,
                status, error_summary,
                created_at, processed_at, created_by
            FROM ops.ingest_batches
            WHERE id = $1
            """,
            str(batch_id),
        )

    if not row:
        return None

    return {
        "id": row["id"],
        "source": row["source"],
        "filename": row["filename"],
        "row_count_raw": row["row_count_raw"],
        "row_count_valid": row["row_count_valid"],
        "row_count_invalid": row["row_count_invalid"],
        "status": row["status"],
        "error_summary": row["error_summary"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "processed_at": (row["processed_at"].isoformat() if row["processed_at"] else None),
        "created_by": row["created_by"],
    }


async def get_batch_errors(batch_id: UUID, limit: int = 100) -> list[dict[str, Any]]:
    """Get invalid rows for a batch."""
    async with get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT row_index, validation_errors, plaintiff_name, defendant_name,
                   case_number, judgment_amount, judgment_date, court
            FROM judgments.staging_simplicity_clean
            WHERE batch_id = $1 AND validation_status = 'invalid'
            ORDER BY row_index
            LIMIT $2
            """,
            str(batch_id),
            limit,
        )

    return [
        {
            "row_index": row["row_index"],
            "validation_errors": row["validation_errors"],
            "plaintiff_name": row["plaintiff_name"],
            "defendant_name": row["defendant_name"],
            "case_number": row["case_number"],
            "judgment_amount": (float(row["judgment_amount"]) if row["judgment_amount"] else None),
            "judgment_date": (row["judgment_date"].isoformat() if row["judgment_date"] else None),
            "court": row["court"],
        }
        for row in rows
    ]


async def list_batches(limit: int = 50) -> list[dict[str, Any]]:
    """List recent batches."""
    async with get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, source, filename,
                row_count_raw, row_count_valid, row_count_invalid,
                status, error_summary,
                created_at, processed_at, created_by
            FROM ops.ingest_batches
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )

    return [
        {
            "id": row["id"],
            "source": row["source"],
            "filename": row["filename"],
            "row_count_raw": row["row_count_raw"],
            "row_count_valid": row["row_count_valid"],
            "row_count_invalid": row["row_count_invalid"],
            "status": row["status"],
            "error_summary": row["error_summary"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "processed_at": (row["processed_at"].isoformat() if row["processed_at"] else None),
            "created_by": row["created_by"],
        }
        for row in rows
    ]


# =============================================================================
# Legacy compatibility - keep old functions working
# =============================================================================


async def ingest_simplicity_csv(path: str) -> dict[str, int]:
    """
    Legacy function for backward compatibility.

    Wraps the new batch-based pipeline for code that still uses the old API.
    """
    import aiofiles

    logger.info(f"Legacy ingest from path: {path}")

    # Create a mock UploadFile-like object
    filename = path.split("/")[-1].split("\\")[-1]

    # Create batch
    batch_id = await create_batch(
        source="simplicity",
        filename=filename,
        created_by="legacy_path_ingest",
    )

    # Read file and create a simple file wrapper
    class FileWrapper:
        def __init__(self, content: bytes, name: str):
            self._content = content
            self._position = 0
            self.filename = name

        async def read(self) -> bytes:
            result = self._content[self._position :]
            self._position = len(self._content)
            return result

        async def seek(self, pos: int) -> None:
            self._position = pos

    async with aiofiles.open(path, "rb") as f:
        content = await f.read()

    file_wrapper = FileWrapper(content, filename)

    # Parse and process
    parse_result = await parse_simplicity_csv(batch_id, file_wrapper)  # type: ignore
    await update_batch_counts(
        batch_id,
        parse_result.row_count_raw,
        parse_result.row_count_valid,
        parse_result.row_count_invalid,
    )

    process_result = await process_simplicity_batch(batch_id)

    return {
        "rows": parse_result.row_count_raw,
        "inserted": process_result.rows_inserted,
        "failed": parse_result.row_count_invalid,
    }


async def log_ingest_result(summary: dict[str, int], source: str) -> None:
    """
    Legacy function - now a no-op since batch system handles logging.
    """
    logger.info(f"Legacy log_ingest_result called: {source} - {summary}")
    # No-op: the new batch system tracks everything in ops.ingest_batches
