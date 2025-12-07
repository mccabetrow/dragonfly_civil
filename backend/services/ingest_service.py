"""
Dragonfly Engine - Ingest Service

Business logic for ingesting judgment data from various sources.
Handles CSV parsing, column normalization, and bulk database inserts.
Integrates with AI service for immediate embedding generation.
"""

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import pandas as pd

from ..db import get_connection
from .ai_service import build_judgment_context, generate_embedding

logger = logging.getLogger(__name__)


# Column mapping from Simplicity export to public.judgments schema
# Simplicity columns -> judgments columns
SIMPLICITY_COLUMN_MAP: dict[str, str] = {
    # Primary identifiers
    "case_number": "case_number",
    "docket_number": "case_number",  # fallback
    # Party names
    "plaintiff_name": "plaintiff_name",
    "plaintiff": "plaintiff_name",
    "title": "plaintiff_name",  # sometimes title is plaintiff
    "defendant_name": "defendant_name",
    "defendant": "defendant_name",
    # Amounts
    "amount_awarded": "judgment_amount",
    "judgment_amount": "judgment_amount",
    "amount": "judgment_amount",
    "total_amount": "judgment_amount",
    # Dates
    "judgment_date": "entry_date",
    "entry_date": "entry_date",
    "filing_date": "entry_date",  # fallback to filing if no judgment date
    # Metadata
    "court": "source_file",  # we'll prepend court info
}


def _normalize_column_name(col: str) -> str:
    """Normalize column name: lowercase, strip, replace spaces with underscores."""
    return col.lower().strip().replace(" ", "_").replace("-", "_")


def _parse_amount(value: Any) -> float | None:
    """Parse amount value to float, handling currency symbols and commas."""
    if pd.isna(value) or value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    # String parsing
    s = str(value).strip()
    if not s:
        return None

    # Remove currency symbols and commas
    s = s.replace("$", "").replace(",", "").strip()

    try:
        return float(s)
    except ValueError:
        logger.warning(f"Could not parse amount: {value}")
        return None


def _parse_date(value: Any) -> date | None:
    """Parse date value to datetime.date object for asyncpg."""
    if pd.isna(value) or value is None:
        return None

    if isinstance(value, date):
        return value

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, pd.Timestamp):
        return value.date()

    # String parsing
    s = str(value).strip()
    if not s:
        return None

    # Try common date formats
    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d", "%d/%m/%Y"]:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    logger.warning(f"Could not parse date: {value}")
    return None


def normalize_simplicity_df(df: pd.DataFrame, source_file: str) -> pd.DataFrame:
    """
    Normalize a Simplicity CSV DataFrame to match public.judgments schema.

    Args:
        df: Raw DataFrame from CSV
        source_file: Source file name for tracking

    Returns:
        DataFrame with normalized columns matching judgments table
    """
    # Normalize column names
    df.columns = [_normalize_column_name(c) for c in df.columns]

    # Build normalized DataFrame
    normalized: dict[str, list[Any]] = {
        "case_number": [],
        "plaintiff_name": [],
        "defendant_name": [],
        "judgment_amount": [],
        "entry_date": [],
        "source_file": [],
    }

    for _, row in df.iterrows():
        row_dict = row.to_dict()

        # Extract case_number (try multiple columns)
        case_number = None
        for col in ["case_number", "docket_number", "case_no", "docket_no"]:
            if col in row_dict and pd.notna(row_dict[col]):
                case_number = str(row_dict[col]).strip()
                break

        # Extract plaintiff_name
        plaintiff_name = None
        for col in ["plaintiff_name", "plaintiff", "title", "case_title", "case_name"]:
            if col in row_dict and pd.notna(row_dict[col]):
                plaintiff_name = str(row_dict[col]).strip()
                break

        # Extract defendant_name
        defendant_name = None
        for col in ["defendant_name", "defendant", "debtor_name", "debtor"]:
            if col in row_dict and pd.notna(row_dict[col]):
                defendant_name = str(row_dict[col]).strip()
                break

        # Extract judgment_amount
        amount = None
        for col in ["amount_awarded", "judgment_amount", "amount", "total_amount"]:
            if col in row_dict:
                amount = _parse_amount(row_dict[col])
                if amount is not None:
                    break

        # Extract entry_date
        entry_date = None
        for col in ["judgment_date", "entry_date", "filing_date", "date"]:
            if col in row_dict:
                entry_date = _parse_date(row_dict[col])
                if entry_date is not None:
                    break

        # Build source_file with court info if available
        court = None
        for col in ["court", "court_name", "venue"]:
            if col in row_dict and pd.notna(row_dict[col]):
                court = str(row_dict[col]).strip()
                break

        file_source = source_file
        if court:
            file_source = f"{court}|{source_file}"

        normalized["case_number"].append(case_number)
        normalized["plaintiff_name"].append(plaintiff_name)
        normalized["defendant_name"].append(defendant_name)
        normalized["judgment_amount"].append(amount)
        normalized["entry_date"].append(entry_date)
        normalized["source_file"].append(file_source)

    return pd.DataFrame(normalized)


async def ingest_simplicity_csv(path: str) -> dict[str, int]:
    """
    Ingest a Simplicity CSV file into public.judgments.

    Loads the CSV, normalizes columns to match our schema, and performs
    bulk INSERT with conflict handling (ON CONFLICT DO NOTHING for case_number).

    Args:
        path: Local filesystem path to the CSV file

    Returns:
        Summary dict with rows, inserted, and failed counts

    Raises:
        Exception: On database or file errors
    """
    logger.info(f"Starting Simplicity CSV ingest: {path}")

    # Load CSV
    try:
        df = pd.read_csv(path, dtype=str)  # Read all as string initially
        logger.info(f"Loaded CSV with {len(df)} rows, columns: {list(df.columns)}")
    except Exception as e:
        logger.error(f"Failed to read CSV: {e}")
        raise RuntimeError(f"Failed to read CSV file: {e}") from e

    if df.empty:
        logger.warning("CSV is empty")
        return {"rows": 0, "inserted": 0, "failed": 0}

    # Normalize to judgments schema
    source_file = path.split("/")[-1].split("\\")[-1]  # Extract filename
    normalized_df = normalize_simplicity_df(df, source_file)

    # Filter out rows with no case_number (required)
    valid_df = normalized_df[normalized_df["case_number"].notna()].copy()
    skipped = len(normalized_df) - len(valid_df)
    if skipped > 0:
        logger.warning(f"Skipping {skipped} rows with no case_number")

    if valid_df.empty:
        logger.warning("No valid rows to insert")
        return {"rows": len(df), "inserted": 0, "failed": len(df)}

    # Bulk insert with transaction
    total_rows = len(df)
    inserted = 0
    failed = 0

    # Collect judgments to queue for enrichment AFTER transaction commits
    judgments_to_enrich: list[tuple[str, float]] = []

    async with get_connection() as conn:
        # Start transaction
        async with conn.transaction():
            for _, row in valid_df.iterrows():
                try:
                    # Generate embedding for semantic search
                    # Extract court from source_file if present
                    source_parts = str(row["source_file"]).split("|")
                    court_name = source_parts[0] if len(source_parts) > 1 else None

                    context = build_judgment_context(
                        plaintiff_name=row.get("plaintiff_name"),
                        defendant_name=row.get("defendant_name"),
                        court_name=court_name,
                        judgment_amount=row.get("judgment_amount"),
                        case_number=row.get("case_number"),
                        judgment_date=(
                            str(row.get("entry_date")) if row.get("entry_date") else None
                        ),
                    )

                    # Generate embedding (returns None on failure - graceful degradation)
                    embedding: Optional[list[float]] = None
                    if context:
                        try:
                            embedding = await generate_embedding(context)
                        except Exception as e:
                            logger.warning(
                                f"Embedding generation failed for {row['case_number']}: {e}"
                            )

                    # Build INSERT with ON CONFLICT DO NOTHING
                    # This handles duplicate case_numbers gracefully
                    # Use RETURNING id to capture the inserted judgment for enrichment
                    # Note: description_embedding is optional - only include if pgvector is set up
                    if embedding:
                        row_result = await conn.fetchrow(
                            """
                            INSERT INTO public.judgments (
                                case_number,
                                plaintiff_name,
                                defendant_name,
                                judgment_amount,
                                entry_date,
                                source_file,
                                description_embedding
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                            ON CONFLICT (case_number) DO NOTHING
                            RETURNING id
                            """,
                            row["case_number"],
                            row["plaintiff_name"],
                            row["defendant_name"],
                            row["judgment_amount"],
                            row["entry_date"],
                            row["source_file"],
                            str(embedding),
                        )
                    else:
                        # No embedding - insert without the vector column
                        row_result = await conn.fetchrow(
                            """
                            INSERT INTO public.judgments (
                                case_number,
                                plaintiff_name,
                                defendant_name,
                                judgment_amount,
                                entry_date,
                                source_file
                            ) VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (case_number) DO NOTHING
                            RETURNING id
                            """,
                            row["case_number"],
                            row["plaintiff_name"],
                            row["defendant_name"],
                            row["judgment_amount"],
                            row["entry_date"],
                            row["source_file"],
                        )

                    if row_result and row_result["id"]:
                        inserted += 1
                        judgment_id = row_result["id"]
                        amount = float(row["judgment_amount"] or 0)
                        # Collect for enrichment after transaction commits
                        judgments_to_enrich.append((str(judgment_id), amount))

                        # Queue graph build (fire-and-forget, wrapped in try/except)
                        try:
                            from .graph_service import process_judgment_for_graph

                            await process_judgment_for_graph(int(judgment_id))
                            logger.debug("Queued graph build for judgment %s", judgment_id)

                            # Emit new_judgment event (best-effort, after graph is built)
                            # The graph build creates the entity we need for event tracking
                            try:
                                from .event_service import emit_event_for_judgment

                                # Extract county from source_file if available
                                source_parts = str(row["source_file"]).split("|")
                                county = source_parts[0] if len(source_parts) > 1 else None

                                await emit_event_for_judgment(
                                    judgment_id=int(judgment_id),
                                    event_type="new_judgment",
                                    payload={
                                        "judgment_id": int(judgment_id),
                                        "amount": str(amount),
                                        "county": county,
                                        "court": county,  # Often same as county for civil courts
                                        "case_number": row.get("case_number"),
                                    },
                                )
                            except Exception as event_err:
                                # Never fail ingest due to event emission
                                logger.debug(
                                    "Event emission skipped for judgment %s: %s",
                                    judgment_id,
                                    event_err,
                                )
                        except Exception as graph_err:
                            # Don't fail ingest if graph build fails
                            logger.warning(
                                "Graph build failed for judgment %s: %s",
                                judgment_id,
                                graph_err,
                            )
                    else:
                        # Conflict - already exists
                        logger.debug(f"Skipped duplicate case_number: {row['case_number']}")

                except Exception as e:
                    logger.warning(f"Failed to insert row {row['case_number']}: {e}")
                    failed += 1

    # Queue enrichment jobs AFTER the transaction has committed
    if judgments_to_enrich:
        try:
            # Local import to avoid circular dependencies
            from .enrichment_service import queue_enrichment

            for judgment_id, amount in judgments_to_enrich:
                try:
                    await queue_enrichment(judgment_id=judgment_id, amount=amount)
                    logger.debug(
                        "Queued enrichment for judgment %s (amount: %s)",
                        judgment_id,
                        amount,
                    )
                except Exception as enrich_err:
                    # Don't fail the ingest if enrichment queueing fails
                    logger.warning(
                        "Failed to queue enrichment for judgment %s: %s",
                        judgment_id,
                        enrich_err,
                    )
        except ImportError:
            logger.warning("enrichment_service not available, skipping enrichment queueing")

    logger.info(
        f"Ingest complete: {total_rows} rows processed, "
        f"{inserted} inserted, {failed} failed, {skipped} skipped (no case_number)"
    )

    return {"rows": total_rows, "inserted": inserted, "failed": failed + skipped}


async def log_ingest_result(summary: dict[str, int], source: str) -> None:
    """
    Log an ingest run to etl_run_logs table.

    Args:
        summary: Ingest result summary (rows, inserted, failed)
        source: Source identifier (e.g., "upload:file.csv", "path:/data/file.csv")
    """
    logger.info(f"Logging ingest result: source={source}, summary={summary}")

    run_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # Status must be one of: success, partial_failure, error, running
    if summary["failed"] == 0:
        status = "success"
    elif summary["inserted"] > 0:
        status = "partial_failure"
    else:
        status = "error"

    try:
        async with get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO public.etl_run_logs (
                    run_id,
                    workflow_name,
                    batch_name,
                    batch_file,
                    status,
                    started_at,
                    completed_at,
                    total_rows,
                    processed_rows,
                    inserted_count,
                    failed_count,
                    committed,
                    created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                run_id,
                "backend_simplicity_ingest",
                source,
                source.split(":")[-1] if ":" in source else source,
                status,
                now,
                now,
                summary["rows"],
                summary["inserted"] + summary["failed"],
                summary["inserted"],
                summary["failed"],
                True,
                now,
            )
            logger.info(f"Logged ingest result to etl_run_logs (run_id={run_id})")

    except Exception as e:
        # Don't fail the ingest if logging fails
        logger.error(f"Failed to log ingest result: {e}")
