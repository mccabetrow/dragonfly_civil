"""
Dragonfly Engine - Intake Service (Fortress Edition)

Enterprise-grade intake processing for the 900-plaintiff asset.
Handles CSV ingestion with:
  - Stream processing (chunked pandas reads)
  - Column normalization (multiple naming conventions)
  - Atomic writes with per-row error isolation
  - Integration with The Brain (enrichment) and The Intelligence (graph)
  - Full audit trail via ops.intake_logs

Usage:
    from backend.services.intake_service import IntakeService

    service = IntakeService(pool)
    batch_id = await service.process_simplicity_upload(file_path, source="simplicity")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

import pandas as pd
import psycopg
from psycopg.rows import dict_row

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHUNK_SIZE = 500  # Rows per chunk for memory efficiency
MAX_ERRORS_BEFORE_ABORT = 100  # Abort batch if too many consecutive errors

# Column mapping: Various source formats -> canonical judgments columns
COLUMN_ALIASES: dict[str, list[str]] = {
    "case_number": [
        "case_number",
        "case #",
        "case#",
        "caseno",
        "case_no",
        "index_number",
        "index number",
        "index #",
        "index#",
        "docket_number",
        "docket",
        "matter_id",
    ],
    "plaintiff_name": [
        "plaintiff_name",
        "plaintiff",
        "creditor",
        "creditor_name",
        "title",
        "petitioner",
    ],
    "defendant_name": [
        "defendant_name",
        "defendant",
        "debtor",
        "debtor_name",
        "respondent",
    ],
    "judgment_amount": [
        "judgment_amount",
        "amount_awarded",
        "amount",
        "total_amount",
        "judgment_amt",
        "principal",
        "principal_amount",
    ],
    "judgment_date": [
        "judgment_date",
        "entry_date",
        "filing_date",
        "date_filed",
        "date_entered",
        "decision_date",
    ],
    "court": [
        "court",
        "court_name",
        "court_type",
        "venue",
    ],
    "county": [
        "county",
        "county_name",
        "jurisdiction",
    ],
}


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class IntakeResult:
    """Result of processing a single row."""

    success: bool
    row_index: int
    judgment_id: Optional[UUID] = None
    error_code: Optional[str] = None
    error_details: Optional[str] = None
    processing_time_ms: int = 0


@dataclass
class BatchResult:
    """Result of processing an entire batch."""

    batch_id: UUID
    total_rows: int = 0
    valid_rows: int = 0
    error_rows: int = 0
    duplicate_rows: int = 0
    skipped_rows: int = 0
    duration_seconds: float = 0.0
    errors: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalization Helpers
# ---------------------------------------------------------------------------


def normalize_column_name(col: str) -> str:
    """Normalize column name: lowercase, strip, replace spaces/dashes."""
    return col.lower().strip().replace(" ", "_").replace("-", "_").replace("#", "")


def find_column(df: pd.DataFrame, canonical: str) -> Optional[str]:
    """
    Find a column in the DataFrame matching the canonical name.

    Checks aliases and normalized names.
    """
    aliases = COLUMN_ALIASES.get(canonical, [canonical])
    normalized_columns = {normalize_column_name(c): c for c in df.columns}

    for alias in aliases:
        normalized_alias = normalize_column_name(alias)
        if normalized_alias in normalized_columns:
            return normalized_columns[normalized_alias]

    return None


def parse_amount(value: Any) -> Optional[float]:
    """Parse monetary amount, handling various formats."""
    if pd.isna(value) or value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if not s:
        return None

    # Remove currency symbols, commas, parentheses (for negatives)
    s = s.replace("$", "").replace(",", "").replace("(", "-").replace(")", "").strip()

    try:
        return float(s)
    except ValueError:
        logger.warning(f"Could not parse amount: {value}")
        return None


def parse_date(value: Any) -> Optional[date]:
    """Parse date value to datetime.date."""
    if pd.isna(value) or value is None:
        return None

    if isinstance(value, date):
        return value

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, pd.Timestamp):
        return value.date()

    s = str(value).strip()
    if not s:
        return None

    # Try common formats
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%m/%d/%y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    logger.warning(f"Could not parse date: {value}")
    return None


def clean_text(value: Any) -> Optional[str]:
    """Clean and normalize text value."""
    if pd.isna(value) or value is None:
        return None

    s = str(value).strip()
    return s if s else None


# ---------------------------------------------------------------------------
# Intake Service
# ---------------------------------------------------------------------------


class IntakeService:
    """
    Enterprise intake processing service.

    Handles CSV ingestion with full audit trail and error isolation.
    """

    def __init__(self, pool: "AsyncConnectionPool"):
        self.pool = pool
        self._enrichment_service: Any = None
        self._graph_service: Any = None

    async def _get_enrichment_service(self) -> Any:
        """Lazy load enrichment service to avoid circular imports."""
        if self._enrichment_service is None:
            try:
                from .enrichment_service import queue_enrichment_job

                self._enrichment_service = queue_enrichment_job
            except ImportError:
                logger.warning("Enrichment service not available")
                self._enrichment_service = False
        return self._enrichment_service if self._enrichment_service else None

    async def _get_graph_service(self) -> Any:
        """Lazy load graph service to avoid circular imports."""
        if self._graph_service is None:
            try:
                from .graph_service import upsert_entities_from_judgment

                self._graph_service = upsert_entities_from_judgment
            except ImportError:
                logger.warning("Graph service not available")
                self._graph_service = False
        return self._graph_service if self._graph_service else None

    async def create_batch(
        self,
        filename: str,
        source: str = "simplicity",
        created_by: Optional[str] = None,
    ) -> UUID:
        """Create a new intake batch record."""
        async with self.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    INSERT INTO ops.ingest_batches (
                        filename, source, status, created_by, stats
                    ) VALUES (
                        %s, %s, 'pending', %s, 
                        jsonb_build_object('total', 0, 'valid', 0, 'error', 0)
                    )
                    RETURNING id
                    """,
                    (filename, source, created_by),
                )
                row = await cur.fetchone()
                return UUID(str(row["id"]))

    async def start_batch(
        self, batch_id: UUID, worker_id: Optional[str] = None
    ) -> None:
        """Mark batch as processing."""
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                UPDATE ops.ingest_batches 
                SET status = 'processing', started_at = now(), worker_id = %s
                WHERE id = %s
                """,
                (worker_id, str(batch_id)),
            )

    async def finalize_batch(
        self,
        batch_id: UUID,
        result: BatchResult,
        status: str = "completed",
    ) -> None:
        """Finalize batch with computed stats."""
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                UPDATE ops.ingest_batches SET
                    status = %s,
                    row_count_raw = %s,
                    row_count_valid = %s,
                    row_count_invalid = %s,
                    completed_at = now(),
                    stats = %s::jsonb
                WHERE id = %s
                """,
                (
                    status,
                    result.total_rows,
                    result.valid_rows,
                    result.error_rows,
                    {
                        "total": result.total_rows,
                        "valid": result.valid_rows,
                        "error": result.error_rows,
                        "duplicates": result.duplicate_rows,
                        "skipped": result.skipped_rows,
                        "duration_seconds": result.duration_seconds,
                    },
                    str(batch_id),
                ),
            )

    async def log_row_result(
        self,
        batch_id: UUID,
        result: IntakeResult,
    ) -> None:
        """Log processing result for a single row."""
        status = "success" if result.success else "error"
        if result.error_code == "DUPLICATE":
            status = "duplicate"
        elif result.error_code == "VALIDATION_SKIPPED":
            status = "skipped"

        async with self.pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO ops.intake_logs (
                    batch_id, row_index, status, judgment_id,
                    error_code, error_details, processing_time_ms
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (batch_id, row_index) DO UPDATE SET
                    status = EXCLUDED.status,
                    judgment_id = EXCLUDED.judgment_id,
                    error_code = EXCLUDED.error_code,
                    error_details = EXCLUDED.error_details,
                    processing_time_ms = EXCLUDED.processing_time_ms
                """,
                (
                    str(batch_id),
                    result.row_index,
                    status,
                    str(result.judgment_id) if result.judgment_id else None,
                    result.error_code,
                    result.error_details,
                    result.processing_time_ms,
                ),
            )

    async def process_row(
        self,
        conn: psycopg.AsyncConnection,
        row: dict[str, Any],
        row_index: int,
        batch_id: UUID,
        source_batch: str,
    ) -> IntakeResult:
        """
        Process a single row: validate, insert judgment, trigger downstream.

        Returns IntakeResult with success/error status.
        """
        start_time = time.perf_counter()

        try:
            # Extract and validate required fields
            case_number = clean_text(row.get("case_number"))
            if not case_number:
                return IntakeResult(
                    success=False,
                    row_index=row_index,
                    error_code="VALIDATION_ERROR",
                    error_details="Missing required field: case_number",
                    processing_time_ms=int((time.perf_counter() - start_time) * 1000),
                )

            # Extract optional fields
            plaintiff_name = clean_text(row.get("plaintiff_name"))
            defendant_name = clean_text(row.get("defendant_name"))
            judgment_amount = parse_amount(row.get("judgment_amount"))
            judgment_date = parse_date(row.get("judgment_date"))
            court = clean_text(row.get("court"))
            county = clean_text(row.get("county"))

            # Insert into public.judgments with UPSERT
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    INSERT INTO public.judgments (
                        case_number,
                        plaintiff_name,
                        defendant_name,
                        judgment_amount,
                        entry_date,
                        source_file,
                        court,
                        county,
                        created_at,
                        updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, now(), now()
                    )
                    ON CONFLICT (case_number) DO UPDATE SET
                        plaintiff_name = COALESCE(EXCLUDED.plaintiff_name, judgments.plaintiff_name),
                        defendant_name = COALESCE(EXCLUDED.defendant_name, judgments.defendant_name),
                        judgment_amount = COALESCE(EXCLUDED.judgment_amount, judgments.judgment_amount),
                        entry_date = COALESCE(EXCLUDED.entry_date, judgments.entry_date),
                        court = COALESCE(EXCLUDED.court, judgments.court),
                        county = COALESCE(EXCLUDED.county, judgments.county),
                        updated_at = now()
                    RETURNING id, (xmax = 0) AS inserted
                    """,
                    (
                        case_number,
                        plaintiff_name,
                        defendant_name,
                        judgment_amount,
                        judgment_date,
                        source_batch,
                        court,
                        county,
                    ),
                )
                result_row = await cur.fetchone()
                judgment_id = UUID(str(result_row["id"]))
                was_inserted = result_row["inserted"]

            # Trigger downstream services (non-blocking, errors don't fail the row)
            try:
                # Queue enrichment job (The Brain)
                enrichment_fn = await self._get_enrichment_service()
                if enrichment_fn and was_inserted:
                    await enrichment_fn(conn, judgment_id)
            except Exception as e:
                logger.warning(f"Enrichment queue failed for {judgment_id}: {e}")

            try:
                # Update intelligence graph (The Intelligence)
                graph_fn = await self._get_graph_service()
                if graph_fn and was_inserted:
                    await graph_fn(conn, judgment_id)
            except Exception as e:
                logger.warning(f"Graph update failed for {judgment_id}: {e}")

            processing_time = int((time.perf_counter() - start_time) * 1000)

            return IntakeResult(
                success=True,
                row_index=row_index,
                judgment_id=judgment_id,
                processing_time_ms=processing_time,
            )

        except psycopg.errors.UniqueViolation:
            return IntakeResult(
                success=False,
                row_index=row_index,
                error_code="DUPLICATE",
                error_details=f"Duplicate case_number: {row.get('case_number')}",
                processing_time_ms=int((time.perf_counter() - start_time) * 1000),
            )

        except Exception as e:
            logger.exception(f"Error processing row {row_index}")
            return IntakeResult(
                success=False,
                row_index=row_index,
                error_code="DB_ERROR",
                error_details=str(e)[:500],
                processing_time_ms=int((time.perf_counter() - start_time) * 1000),
            )

    def normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize DataFrame columns to canonical names.

        Maps various column naming conventions to standard schema.
        """
        column_map = {}

        for canonical, aliases in COLUMN_ALIASES.items():
            source_col = find_column(df, canonical)
            if source_col:
                column_map[source_col] = canonical

        # Rename columns that we found
        df = df.rename(columns=column_map)

        return df

    async def process_simplicity_upload(
        self,
        file_path: str | Path,
        batch_id: Optional[UUID] = None,
        source: str = "simplicity",
        created_by: Optional[str] = None,
        worker_id: Optional[str] = None,
    ) -> BatchResult:
        """
        Process a Simplicity CSV upload with streaming and error isolation.

        Args:
            file_path: Path to the CSV file
            batch_id: Existing batch ID, or create new if None
            source: Source identifier (simplicity, jbi, manual, etc.)
            created_by: User/system that initiated the upload
            worker_id: ID of the processing worker

        Returns:
            BatchResult with processing statistics
        """
        file_path = Path(file_path)
        start_time = time.perf_counter()

        # Create or use provided batch
        if batch_id is None:
            batch_id = await self.create_batch(
                filename=file_path.name,
                source=source,
                created_by=created_by,
            )

        await self.start_batch(batch_id, worker_id)
        source_batch = f"{source}:{batch_id}"

        result = BatchResult(batch_id=batch_id)
        consecutive_errors = 0

        try:
            # Stream CSV in chunks
            for chunk_idx, chunk_df in enumerate(
                pd.read_csv(file_path, chunksize=CHUNK_SIZE, dtype=str)
            ):
                logger.info(
                    f"Processing chunk {chunk_idx + 1} "
                    f"({len(chunk_df)} rows) for batch {batch_id}"
                )

                # Normalize column names
                chunk_df = self.normalize_dataframe(chunk_df)

                # Process each row in the chunk
                async with self.pool.connection() as conn:
                    for local_idx, row in chunk_df.iterrows():
                        row_index = chunk_idx * CHUNK_SIZE + int(local_idx)
                        result.total_rows += 1

                        # Process the row
                        row_result = await self.process_row(
                            conn=conn,
                            row=row.to_dict(),
                            row_index=row_index,
                            batch_id=batch_id,
                            source_batch=source_batch,
                        )

                        # Log the result
                        await self.log_row_result(batch_id, row_result)

                        # Update counters
                        if row_result.success:
                            result.valid_rows += 1
                            consecutive_errors = 0
                        elif row_result.error_code == "DUPLICATE":
                            result.duplicate_rows += 1
                            consecutive_errors = 0
                        elif row_result.error_code == "VALIDATION_SKIPPED":
                            result.skipped_rows += 1
                        else:
                            result.error_rows += 1
                            consecutive_errors += 1
                            result.errors.append(
                                {
                                    "row": row_index,
                                    "code": row_result.error_code,
                                    "message": row_result.error_details,
                                }
                            )

                        # Check for too many consecutive errors
                        if consecutive_errors >= MAX_ERRORS_BEFORE_ABORT:
                            logger.error(
                                f"Aborting batch {batch_id}: "
                                f"{consecutive_errors} consecutive errors"
                            )
                            result.duration_seconds = time.perf_counter() - start_time
                            await self.finalize_batch(batch_id, result, status="failed")
                            return result

            # Success
            result.duration_seconds = time.perf_counter() - start_time
            await self.finalize_batch(batch_id, result, status="completed")

            logger.info(
                f"Batch {batch_id} completed: "
                f"{result.valid_rows}/{result.total_rows} valid, "
                f"{result.error_rows} errors, "
                f"{result.duplicate_rows} duplicates, "
                f"{result.duration_seconds:.1f}s"
            )

            return result

        except Exception as e:
            logger.exception(f"Batch {batch_id} failed with exception")
            result.duration_seconds = time.perf_counter() - start_time
            result.errors.append(
                {
                    "row": -1,
                    "code": "BATCH_ERROR",
                    "message": str(e)[:500],
                }
            )
            await self.finalize_batch(batch_id, result, status="failed")
            raise


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------


async def process_simplicity_upload(
    file_path: str | Path,
    pool: "AsyncConnectionPool",
    batch_id: Optional[UUID] = None,
    source: str = "simplicity",
    created_by: Optional[str] = None,
) -> BatchResult:
    """
    Convenience function to process a Simplicity CSV upload.

    Creates an IntakeService instance and processes the file.
    """
    service = IntakeService(pool)
    return await service.process_simplicity_upload(
        file_path=file_path,
        batch_id=batch_id,
        source=source,
        created_by=created_by,
    )
