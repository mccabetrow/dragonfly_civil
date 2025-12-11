#!/usr/bin/env python3
"""
Dragonfly Engine - Ingest Processor Worker

Background worker that processes CSV ingest jobs from ops.job_queue.
Polls for jobs with job_type = 'ingest_csv' and status = 'pending',
loads CSV from Supabase Storage, parses with pandas, generates
collectability scores, and inserts into public.judgments.

Architecture:
- Uses FOR UPDATE SKIP LOCKED for safe concurrent dequeue
- Transactional job state management
- Idempotent design (can safely retry failed jobs)
- Structured logging with correlation IDs

Usage:
    python -m backend.workers.ingest_processor

Environment:
    SUPABASE_MODE: dev | prod (determines which Supabase project to use)
    SUPABASE_DB_URL_DEV / SUPABASE_DB_URL_PROD: Postgres connection strings
"""

from __future__ import annotations

import io
import json
import logging
import os
import random
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional
from uuid import uuid4

import pandas as pd
import psycopg
from psycopg.rows import dict_row

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.supabase_client import create_supabase_client, get_supabase_db_url, get_supabase_env

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ingest_processor")

# Worker configuration
POLL_INTERVAL_SECONDS = 2.0
LOCK_TIMEOUT_MINUTES = 30
JOB_TYPE = "ingest_csv"

# Simplicity CSV expected columns
SIMPLICITY_COLUMNS = [
    "Case Number",
    "Plaintiff",
    "Defendant",
    "Judgment Amount",
    "Filing Date",
    "County",
]

# FOIL format indicator columns (abbreviated court-style headers)
FOIL_INDICATOR_PATTERNS = [
    r"(?i)^def\.?\s*name$",  # "Def. Name" or "DefName"
    r"(?i)^plf\.?\s*name$",  # "Plf. Name"
    r"(?i)^amt$",  # "Amt" instead of "Amount"
    r"(?i)^jdg(?:mt|ment)?[\s_.-]?date$",  # "Jdgmt Date"
    r"(?i)^date[\s_-]?filed$",  # "Date Filed"
    r"(?i)^index[\s_-]?(?:no|num)?$",  # "Index No"
    r"(?i)^docket[\s_-]?(?:no|num)?$",  # "Docket No"
]


# =============================================================================
# Simplicity Mapper Helpers
# =============================================================================


def _clean_currency(value: Any) -> Optional[Decimal]:
    """Convert common Simplicity currency strings to Decimal.

    Examples:
        "$1,200.00" -> Decimal("1200.00")
        "  500 "    -> Decimal("500")
        None / ""   -> None
    """
    if value is None:
        return None

    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))

    s = str(value).strip()
    if not s:
        return None

    # Remove $ and commas
    s = s.replace("$", "").replace(",", "")

    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _parse_simplicity_date(value: Any) -> Optional[datetime]:
    """Parse Simplicity dates (MM/DD/YYYY) into datetime.

    Returns None if the value is empty or unparseable.
    """
    if value is None:
        return None

    s = str(value).strip()
    if not s:
        return None

    # Common Simplicity format: 03/15/2021
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue

    # If we can't parse, treat as missing
    return None


def _map_simplicity_row(row: pd.Series) -> Dict[str, Any]:
    """Map a single Simplicity CSV row -> public.judgments insert dict.

    Expected columns:
        - Case Number
        - Plaintiff
        - Defendant
        - Judgment Amount
        - Filing Date
        - County

    Raises:
        ValueError if required columns are missing or Judgment Amount is invalid.
    """
    missing_cols = [c for c in SIMPLICITY_COLUMNS if c not in row.index]
    if missing_cols:
        raise ValueError(f"Simplicity row missing required columns: {missing_cols}")

    amount = _clean_currency(row.get("Judgment Amount"))
    if amount is None:
        # We treat missing/invalid amount as a hard validation failure
        raise ValueError("Missing or invalid Judgment Amount")

    filed_at = _parse_simplicity_date(row.get("Filing Date"))

    return {
        "case_number": (row.get("Case Number") or "").strip(),
        "plaintiff_name": (row.get("Plaintiff") or "").strip(),
        "defendant_name": (row.get("Defendant") or "").strip(),
        "judgment_amount": amount,
        "filing_date": filed_at.date().isoformat() if filed_at else None,
        "county": (row.get("County") or "").strip(),
    }


def _log_invalid_row(
    conn: psycopg.Connection,
    batch_id: str,
    raw_row: Dict[str, Any],
    error_message: str,
) -> None:
    """Write a record into ops.intake_logs for invalid rows.

    This provides 'does not crash but logs' behavior for bad data.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.intake_logs (batch_id, level, message, raw_payload, created_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT DO NOTHING
                """,
                (batch_id, "ERROR", error_message[:1000], json.dumps(raw_row, default=str)),
            )
            conn.commit()
    except Exception as e:
        # Table might not exist yet - rollback and continue
        try:
            conn.rollback()
        except Exception:
            pass
        logger.debug(f"Could not log invalid row to ops.intake_logs: {e}")


def _is_simplicity_format(df: pd.DataFrame) -> bool:
    """Check if DataFrame appears to be in Simplicity format.

    Returns True if all required Simplicity columns are present.
    """
    return all(col in df.columns for col in SIMPLICITY_COLUMNS)


def _is_foil_format(df: pd.DataFrame) -> bool:
    """Check if DataFrame appears to be in FOIL format.

    FOIL format is characterized by abbreviated column names like:
    - "Def. Name" instead of "Defendant"
    - "Amt" instead of "Judgment Amount"
    - "Jdgmt Date" instead of "Judgment Date"

    Returns True if 2+ FOIL indicator patterns match.
    """
    if df.empty:
        return False

    # If it's Simplicity format, it's not FOIL
    if _is_simplicity_format(df):
        return False

    # Count FOIL indicator columns
    foil_matches = 0
    for col in df.columns:
        for pattern in FOIL_INDICATOR_PATTERNS:
            if re.match(pattern, col):
                foil_matches += 1
                break

    return foil_matches >= 2


def process_simplicity_frame(conn: psycopg.Connection, df: pd.DataFrame, batch_id: str) -> int:
    """Process a Simplicity DataFrame into public.judgments rows.

    Uses the hardened mapper with per-row error handling.
    Invalid rows are logged to ops.intake_logs and ops.data_discrepancies.
    Every row is tracked in ops.ingest_audit_log.

    Returns the number of successfully inserted rows.
    """
    from backend.services.reconciliation import ErrorType, ReconciliationService

    success_count = 0
    reconciler = ReconciliationService(conn)

    for idx, row in df.iterrows():
        raw = row.to_dict()
        row_index = int(idx) if isinstance(idx, (int, float)) else 0

        # Log row received
        try:
            reconciler.log_row_received(batch_id, row_index, raw)
        except Exception as e:
            logger.debug(f"Could not log row received: {e}")

        try:
            mapped = _map_simplicity_row(row)

            # Log row parsed
            try:
                case_number = mapped.get("case_number")
                reconciler.log_row_parsed(batch_id, row_index, mapped, case_number)
            except Exception as e:
                logger.debug(f"Could not log row parsed: {e}")

        except ValueError as exc:
            # Validation error - log and continue
            logger.warning("Validation failed for row %s: %s", idx, exc)
            _log_invalid_row(conn, batch_id, raw, str(exc))

            # Log to audit as failed
            try:
                reconciler.log_row_failed(
                    batch_id, row_index, "validate", "VALIDATION_ERROR", str(exc)
                )
            except Exception as e:
                logger.debug(f"Could not log row failed: {e}")

            # Add to Dead Letter Queue
            try:
                reconciler.create_discrepancy(
                    batch_id=batch_id,
                    row_index=row_index,
                    raw_data=raw,
                    error_type=ErrorType.VALIDATION_ERROR,
                    error_message=str(exc),
                    error_code="VALIDATION_ERROR",
                )
            except Exception as e:
                logger.debug(f"Could not create discrepancy: {e}")
            continue
        except Exception as exc:
            # Unexpected error - log with full context and continue
            logger.exception("Unexpected error mapping row %s: %s", idx, exc)
            _log_invalid_row(conn, batch_id, raw, f"Unexpected error: {exc}")

            # Log to audit as failed
            try:
                reconciler.log_row_failed(batch_id, row_index, "parse", "PARSE_ERROR", str(exc))
            except Exception as e:
                logger.debug(f"Could not log row failed: {e}")

            # Add to Dead Letter Queue
            try:
                reconciler.create_discrepancy(
                    batch_id=batch_id,
                    row_index=row_index,
                    raw_data=raw,
                    error_type=ErrorType.PARSE_ERROR,
                    error_message=str(exc),
                    error_code="PARSE_ERROR",
                )
            except Exception as e:
                logger.debug(f"Could not create discrepancy: {e}")
            continue

        # Log row validated
        try:
            reconciler.log_row_validated(batch_id, row_index)
        except Exception as e:
            logger.debug(f"Could not log row validated: {e}")

        # Generate collectability score for new inserts
        collectability_score = generate_collectability_score()

        # Insert into public.judgments
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.judgments (
                        case_number,
                        plaintiff_name,
                        defendant_name,
                        judgment_amount,
                        entry_date,
                        county,
                        collectability_score,
                        source_file,
                        status,
                        created_at
                    )
                    VALUES (
                        %(case_number)s,
                        %(plaintiff_name)s,
                        %(defendant_name)s,
                        %(judgment_amount)s,
                        %(filing_date)s,
                        %(county)s,
                        %(collectability_score)s,
                        %(source_file)s,
                        'pending',
                        now()
                    )
                    ON CONFLICT (case_number) DO UPDATE SET
                        plaintiff_name = EXCLUDED.plaintiff_name,
                        defendant_name = EXCLUDED.defendant_name,
                        judgment_amount = EXCLUDED.judgment_amount,
                        entry_date = EXCLUDED.entry_date,
                        county = EXCLUDED.county,
                        collectability_score = EXCLUDED.collectability_score,
                        updated_at = now()
                    RETURNING id, (xmax = 0) AS is_insert
                    """,
                    {
                        **mapped,
                        "collectability_score": collectability_score,
                        "source_file": f"batch:{batch_id}",
                    },
                )
                result = cur.fetchone()
                judgment_id = str(result[0]) if result else None
                is_insert = result[1] if result else True
            conn.commit()
            success_count += 1

            # Log row stored successfully
            try:
                reconciler.log_row_stored(batch_id, row_index, judgment_id)
            except Exception as e:
                logger.debug(f"Could not log row stored: {e}")

            # Log entity-level audit for data integrity guarantee
            try:
                action = "INSERT" if is_insert else "UPDATE"
                new_values = {
                    **mapped,
                    "collectability_score": collectability_score,
                    "source_file": f"batch:{batch_id}",
                    "status": "pending",
                }
                reconciler.log_entity_change(
                    entity_id=judgment_id or mapped.get("case_number", "unknown"),
                    table_name="public.judgments",
                    action=action,
                    old_values=None if is_insert else {},  # Could fetch old values if needed
                    new_values=new_values,
                    worker_id="ingest_processor",
                    batch_id=batch_id,
                    source_file=f"batch:{batch_id}",
                )
            except Exception as e:
                logger.debug(f"Could not log entity change: {e}")

        except Exception as exc:
            logger.exception("DB error inserting mapped row %s: %s", idx, exc)
            _log_invalid_row(conn, batch_id, raw, f"DB error: {exc}")

            # Log to audit as failed
            try:
                reconciler.log_row_failed(batch_id, row_index, "store", "DB_ERROR", str(exc))
            except Exception as e:
                logger.debug(f"Could not log row failed: {e}")

            # Add to Dead Letter Queue
            try:
                reconciler.create_discrepancy(
                    batch_id=batch_id,
                    row_index=row_index,
                    raw_data=raw,
                    error_type=ErrorType.DB_ERROR,
                    error_message=str(exc),
                    error_code="DB_ERROR",
                )
            except Exception as e:
                logger.debug(f"Could not create discrepancy: {e}")

            # Rollback this row's failed transaction
            try:
                conn.rollback()
            except Exception:
                pass

    return success_count


# =============================================================================
# FOIL Processing
# =============================================================================


def process_foil_frame(conn: psycopg.Connection, df: pd.DataFrame, batch_id: str) -> int:
    """Process a FOIL DataFrame into public.judgments rows.

    Uses the FoilMapper for column auto-detection and bulk insert optimization.
    Designed for massive FOIL datasets (millions of rows).

    For datasets > 10,000 rows, uses COPY-based bulk insert for speed.
    Smaller datasets use row-by-row insert with full audit trail.

    Returns the number of successfully inserted rows.
    """
    from backend.services.foil_mapper import FoilMapper
    from backend.services.reconciliation import ErrorType, ReconciliationService

    reconciler = ReconciliationService(conn)
    mapper = FoilMapper()

    # Detect column mapping
    mapping = mapper.detect_column_mapping(df)
    logger.info(
        f"FOIL column mapping detected: confidence={mapping.confidence}%, "
        f"mapped={len(mapping.raw_to_canonical)}, unmapped={len(mapping.unmapped_columns)}"
    )

    if not mapping.is_valid:
        logger.error(f"FOIL mapping invalid - missing required fields: {mapping.required_missing}")
        # Log all rows as failed
        for idx in range(len(df)):
            try:
                reconciler.create_discrepancy(
                    batch_id=batch_id,
                    row_index=idx,
                    raw_data={"error": "mapping_failed"},
                    error_type=ErrorType.SCHEMA_MISMATCH,
                    error_message=f"Missing required fields: {mapping.required_missing}",
                    error_code="FOIL_MAPPING_INVALID",
                )
            except Exception:
                pass
        return 0

    # Transform all rows
    mapped_rows = mapper.transform_dataframe(df, mapping)

    # Separate valid and invalid rows
    valid_rows = [r for r in mapped_rows if r.is_valid()]
    invalid_rows = [r for r in mapped_rows if not r.is_valid()]

    logger.info(f"FOIL transformation: {len(valid_rows)} valid, {len(invalid_rows)} invalid")

    # Log invalid rows to discrepancy queue
    for i, row in enumerate(invalid_rows):
        try:
            row_index = list(df.index)[mapped_rows.index(row)] if row in mapped_rows else i
            reconciler.create_discrepancy(
                batch_id=batch_id,
                row_index=int(row_index) if isinstance(row_index, (int, float)) else i,
                raw_data=row.raw_data,
                error_type=ErrorType.VALIDATION_ERROR,
                error_message="; ".join(row.errors),
                error_code="FOIL_VALIDATION_FAILED",
            )
        except Exception as e:
            logger.debug(f"Could not create discrepancy: {e}")

    if not valid_rows:
        return 0

    # Use bulk insert for large datasets (> 10,000 rows)
    use_bulk = len(valid_rows) > 10000
    source_file = f"foil-batch:{batch_id}"

    if use_bulk:
        logger.info(f"Using COPY-based bulk insert for {len(valid_rows)} FOIL rows")
        try:
            inserted, duplicates, errors = mapper.bulk_insert_judgments(
                conn, valid_rows, batch_id, source_file
            )
            logger.info(f"FOIL bulk insert: {inserted} inserted, {duplicates} duplicates")
            return inserted
        except Exception as e:
            logger.exception(f"FOIL bulk insert failed, falling back to row-by-row: {e}")
            # Fall through to row-by-row insert

    # Row-by-row insert with full audit trail
    success_count = 0
    for idx, row in enumerate(valid_rows):
        try:
            # Log row received/validated
            try:
                reconciler.log_row_received(batch_id, idx, row.raw_data)
                reconciler.log_row_validated(batch_id, idx)
            except Exception:
                pass

            collectability_score = generate_collectability_score()
            insert_dict = row.to_insert_dict()

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.judgments (
                        case_number,
                        plaintiff_name,
                        defendant_name,
                        judgment_amount,
                        entry_date,
                        county,
                        court,
                        collectability_score,
                        source_file,
                        status,
                        created_at
                    )
                    VALUES (
                        %(case_number)s,
                        %(plaintiff_name)s,
                        %(defendant_name)s,
                        %(judgment_amount)s,
                        %(entry_date)s,
                        %(county)s,
                        %(court)s,
                        %(collectability_score)s,
                        %(source_file)s,
                        'pending',
                        now()
                    )
                    ON CONFLICT (case_number) DO UPDATE SET
                        plaintiff_name = COALESCE(EXCLUDED.plaintiff_name, public.judgments.plaintiff_name),
                        defendant_name = COALESCE(EXCLUDED.defendant_name, public.judgments.defendant_name),
                        judgment_amount = EXCLUDED.judgment_amount,
                        entry_date = COALESCE(EXCLUDED.entry_date, public.judgments.entry_date),
                        county = COALESCE(EXCLUDED.county, public.judgments.county),
                        court = COALESCE(EXCLUDED.court, public.judgments.court),
                        collectability_score = EXCLUDED.collectability_score,
                        updated_at = now()
                    """,
                    {
                        **insert_dict,
                        "collectability_score": collectability_score,
                        "source_file": source_file,
                    },
                )
            conn.commit()
            success_count += 1

            # Log successful storage
            try:
                reconciler.log_row_stored(batch_id, idx, None)
            except Exception:
                pass

        except Exception as exc:
            logger.warning(f"FOIL row {idx} insert failed: {exc}")
            try:
                conn.rollback()
            except Exception:
                pass

            try:
                reconciler.create_discrepancy(
                    batch_id=batch_id,
                    row_index=idx,
                    raw_data=row.raw_data,
                    error_type=ErrorType.DB_ERROR,
                    error_message=str(exc),
                    error_code="FOIL_INSERT_FAILED",
                )
            except Exception:
                pass

    return success_count


# =============================================================================
# FOIL Dataset Ingest (job_type='foil_ingest')
# =============================================================================


def process_foil_ingest_job(conn: psycopg.Connection, job: dict[str, Any]) -> None:
    """
    Process a FOIL dataset ingest job (job_type='foil_ingest').

    This handler:
    1. Loads the raw CSV from storage
    2. Creates an intake.foil_datasets record
    3. Uses ColumnMapper for fuzzy header matching
    4. Stores raw rows to intake.foil_raw_rows
    5. Validates and transforms rows using the detected mapping
    6. Inserts valid rows to public.judgments
    7. Quarantines unmappable rows to intake.foil_quarantine

    Expected payload:
    {
        "file_path": "intake/foil_nyc_civil_2024.csv",
        "dataset_name": "NYC Civil Court Q4 2024",
        "source_agency": "NYC Civil Court",
        "foil_request_number": "FOIL-2024-12345",
        "explicit_mapping": {"Def. Name": "defendant_name"},  # optional
        "fuzzy_threshold": 80  # optional, default 80
    }
    """
    from backend.services.column_mapper import ColumnMapper
    from backend.services.reconciliation import ErrorType, ReconciliationService

    job_id = str(job["id"])
    payload = job.get("payload", {})
    run_id = str(uuid4())[:8]

    file_path = payload.get("file_path")
    dataset_name = payload.get("dataset_name", f"FOIL-{run_id}")
    source_agency = payload.get("source_agency")
    foil_request_number = payload.get("foil_request_number")
    explicit_mapping = payload.get("explicit_mapping", {})
    fuzzy_threshold = payload.get("fuzzy_threshold", 80)

    logger.info(f"[{run_id}] Processing FOIL ingest job {job_id}: {dataset_name}")

    if not file_path:
        error = "Missing file_path in FOIL ingest payload"
        logger.error(f"[{run_id}] {error}")
        mark_job_failed(conn, job_id, error)
        return

    try:
        # Step 1: Load CSV from storage
        df = load_csv_from_storage(file_path)
        if df.empty:
            logger.warning(f"[{run_id}] FOIL CSV is empty: {file_path}")
            mark_job_completed(conn, job_id)
            return

        logger.info(f"[{run_id}] Loaded FOIL CSV: {len(df)} rows, {len(df.columns)} columns")

        # Step 2: Create dataset record
        dataset_id = _create_foil_dataset(
            conn,
            dataset_name=dataset_name,
            original_filename=file_path.split("/")[-1],
            source_agency=source_agency,
            foil_request_number=foil_request_number,
            row_count_raw=len(df),
            column_count=len(df.columns),
            detected_columns=list(df.columns),
        )
        logger.info(f"[{run_id}] Created FOIL dataset: {dataset_id}")

        # Step 3: Use ColumnMapper for fuzzy matching
        mapper = ColumnMapper(
            fuzzy_threshold=fuzzy_threshold,
            explicit_mapping=explicit_mapping,
        )
        mapping_result = mapper.map_columns(list(df.columns))

        logger.info(
            f"[{run_id}] Column mapping: confidence={mapping_result.confidence}%, "
            f"mapped={len(mapping_result.raw_to_canonical)}, "
            f"unmapped={len(mapping_result.unmapped_columns)}"
        )

        # Update dataset with mapping results
        _update_foil_dataset_mapping(
            conn,
            dataset_id=dataset_id,
            mapping_result=mapping_result,
        )

        # Check if mapping is valid (has required fields)
        if not mapping_result.is_valid:
            logger.error(
                f"[{run_id}] FOIL mapping invalid - missing required fields: "
                f"{mapping_result.required_missing}"
            )
            _update_foil_dataset_status(
                conn,
                dataset_id,
                "failed",
                error_summary=f"Missing required fields: {mapping_result.required_missing}",
            )
            mark_job_failed(
                conn, job_id, f"Missing required fields: {mapping_result.required_missing}"
            )
            return

        # If low confidence, mark as needs_review but continue processing
        if mapping_result.needs_review:
            logger.warning(
                f"[{run_id}] FOIL mapping needs review (confidence={mapping_result.confidence}%)"
            )
            _update_foil_dataset_status(conn, dataset_id, "needs_review")

        # Step 4: Store raw rows to intake.foil_raw_rows
        _store_foil_raw_rows(conn, dataset_id, df)
        logger.info(f"[{run_id}] Stored {len(df)} raw rows")

        # Step 5: Process rows using the mapping
        _update_foil_dataset_status(conn, dataset_id, "processing")

        valid_count, invalid_count, quarantine_count = _process_foil_rows(
            conn, dataset_id, df, mapping_result, run_id
        )

        # Step 6: Update dataset with final counts
        final_status = "completed" if quarantine_count == 0 else "partial"
        _update_foil_dataset_counts(
            conn,
            dataset_id=dataset_id,
            row_count_valid=valid_count,
            row_count_invalid=invalid_count,
            row_count_quarantined=quarantine_count,
            status=final_status,
        )

        logger.info(
            f"[{run_id}] FOIL ingest complete: {valid_count} valid, "
            f"{invalid_count} invalid, {quarantine_count} quarantined"
        )
        mark_job_completed(conn, job_id)

    except Exception as e:
        error_msg = str(e)[:500]
        logger.exception(f"[{run_id}] FOIL ingest job {job_id} failed: {e}")
        mark_job_failed(conn, job_id, error_msg)


def _create_foil_dataset(
    conn: psycopg.Connection,
    dataset_name: str,
    original_filename: str,
    source_agency: str | None,
    foil_request_number: str | None,
    row_count_raw: int,
    column_count: int,
    detected_columns: list[str],
) -> str:
    """Create a new intake.foil_datasets record."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO intake.foil_datasets (
                dataset_name,
                original_filename,
                source_agency,
                foil_request_number,
                row_count_raw,
                column_count,
                detected_columns,
                status,
                mapping_started_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'mapping', now())
            RETURNING id
            """,
            (
                dataset_name,
                original_filename,
                source_agency,
                foil_request_number,
                row_count_raw,
                column_count,
                detected_columns,
            ),
        )
        result = cur.fetchone()
        conn.commit()
        if result is None:
            raise RuntimeError("Failed to insert into intake.foil_datasets")
        return str(result[0])


def _update_foil_dataset_mapping(
    conn: psycopg.Connection,
    dataset_id: str,
    mapping_result: Any,  # ColumnMappingResult
) -> None:
    """Update dataset with column mapping results."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE intake.foil_datasets
            SET column_mapping = %s,
                column_mapping_reverse = %s,
                unmapped_columns = %s,
                mapping_confidence = %s,
                required_fields_missing = %s,
                mapping_completed_at = now()
            WHERE id = %s
            """,
            (
                json.dumps(mapping_result.raw_to_canonical),
                json.dumps(mapping_result.canonical_to_raw),
                mapping_result.unmapped_columns,
                mapping_result.confidence,
                mapping_result.required_missing,
                dataset_id,
            ),
        )
        conn.commit()


def _update_foil_dataset_status(
    conn: psycopg.Connection,
    dataset_id: str,
    status: str,
    error_summary: str | None = None,
) -> None:
    """Update dataset status."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE intake.foil_datasets
            SET status = %s,
                error_summary = COALESCE(%s, error_summary),
                processing_started_at = CASE WHEN %s = 'processing' THEN now() ELSE processing_started_at END
            WHERE id = %s
            """,
            (status, error_summary, status, dataset_id),
        )
        conn.commit()


def _update_foil_dataset_counts(
    conn: psycopg.Connection,
    dataset_id: str,
    row_count_valid: int,
    row_count_invalid: int,
    row_count_quarantined: int,
    status: str,
) -> None:
    """Update dataset with final row counts."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE intake.foil_datasets
            SET row_count_valid = %s,
                row_count_invalid = %s,
                row_count_quarantined = %s,
                row_count_mapped = %s,
                status = %s,
                processed_at = now()
            WHERE id = %s
            """,
            (
                row_count_valid,
                row_count_invalid,
                row_count_quarantined,
                row_count_valid + row_count_invalid,
                status,
                dataset_id,
            ),
        )
        conn.commit()


def _store_foil_raw_rows(
    conn: psycopg.Connection,
    dataset_id: str,
    df: pd.DataFrame,
) -> None:
    """Store raw CSV rows to intake.foil_raw_rows."""
    with conn.cursor() as cur:
        for idx, row in df.iterrows():
            row_index = int(idx) if isinstance(idx, (int, float)) else 0
            cur.execute(
                """
                INSERT INTO intake.foil_raw_rows (dataset_id, row_index, raw_data)
                VALUES (%s, %s, %s)
                """,
                (dataset_id, row_index, json.dumps(row.to_dict(), default=str)),
            )
        conn.commit()


def _process_foil_rows(
    conn: psycopg.Connection,
    dataset_id: str,
    df: pd.DataFrame,
    mapping_result: Any,  # ColumnMappingResult
    run_id: str,
) -> tuple[int, int, int]:
    """
    Process FOIL rows using the column mapping.

    Returns: (valid_count, invalid_count, quarantine_count)
    """
    from backend.services.reconciliation import ErrorType, ReconciliationService

    valid_count = 0
    invalid_count = 0
    quarantine_count = 0

    raw_to_canonical = mapping_result.raw_to_canonical

    for idx, row in df.iterrows():
        row_index = int(idx) if isinstance(idx, (int, float)) else 0
        raw_data = row.to_dict()

        try:
            # Map row to canonical format
            mapped = _map_foil_row(row, raw_to_canonical)

            if not mapped.get("case_number") or mapped.get("judgment_amount") is None:
                # Missing required fields - quarantine
                _quarantine_foil_row(
                    conn,
                    dataset_id=dataset_id,
                    row_index=row_index,
                    raw_data=raw_data,
                    reason="missing_required",
                    error_message="Missing case_number or judgment_amount",
                    mapped_data=mapped,
                )
                quarantine_count += 1
                continue

            # Insert into public.judgments
            collectability_score = generate_collectability_score()
            source_file = f"foil-dataset:{dataset_id}"

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.judgments (
                        case_number,
                        plaintiff_name,
                        defendant_name,
                        judgment_amount,
                        entry_date,
                        county,
                        court,
                        collectability_score,
                        source_file,
                        status,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', now())
                    ON CONFLICT (case_number) DO UPDATE SET
                        plaintiff_name = COALESCE(EXCLUDED.plaintiff_name, public.judgments.plaintiff_name),
                        defendant_name = COALESCE(EXCLUDED.defendant_name, public.judgments.defendant_name),
                        judgment_amount = EXCLUDED.judgment_amount,
                        entry_date = COALESCE(EXCLUDED.entry_date, public.judgments.entry_date),
                        county = COALESCE(EXCLUDED.county, public.judgments.county),
                        court = COALESCE(EXCLUDED.court, public.judgments.court),
                        updated_at = now()
                    RETURNING id
                    """,
                    (
                        mapped["case_number"],
                        mapped.get("plaintiff_name"),
                        mapped.get("defendant_name"),
                        mapped.get("judgment_amount"),
                        mapped.get("entry_date"),
                        mapped.get("county"),
                        mapped.get("court"),
                        collectability_score,
                        source_file,
                    ),
                )
                result = cur.fetchone()
                judgment_id = str(result[0]) if result else None

            conn.commit()

            # Update raw row status
            _update_foil_raw_row_status(conn, dataset_id, row_index, "valid", judgment_id)
            valid_count += 1

        except Exception as e:
            logger.warning(f"[{run_id}] FOIL row {row_index} failed: {e}")
            try:
                conn.rollback()
            except Exception:
                pass

            # Quarantine the failed row
            _quarantine_foil_row(
                conn,
                dataset_id=dataset_id,
                row_index=row_index,
                raw_data=raw_data,
                reason="transform_error",
                error_message=str(e)[:500],
            )
            quarantine_count += 1

    return valid_count, invalid_count, quarantine_count


def _map_foil_row(row: pd.Series, raw_to_canonical: dict[str, str]) -> dict[str, Any]:
    """Map a single FOIL row to canonical format."""
    mapped: dict[str, Any] = {}

    for raw_col, canonical_col in raw_to_canonical.items():
        value = row.get(raw_col)
        if pd.isna(value):
            continue

        # Handle type conversion based on canonical field
        if canonical_col == "judgment_amount":
            mapped[canonical_col] = _parse_foil_currency(value)
        elif canonical_col in ("filing_date", "judgment_date"):
            parsed = _parse_foil_date(value)
            if canonical_col == "filing_date":
                mapped["entry_date"] = parsed.date().isoformat() if parsed else None
            else:
                mapped["entry_date"] = mapped.get("entry_date") or (
                    parsed.date().isoformat() if parsed else None
                )
        elif canonical_col == "case_number":
            mapped[canonical_col] = str(value).strip()[:100]
        else:
            mapped[canonical_col] = str(value).strip()[:500]

    return mapped


def _parse_foil_currency(value: Any) -> Decimal | None:
    """Parse currency value from FOIL data."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))

    s = str(value).strip()
    if not s:
        return None

    # Remove currency symbols and thousands separators
    s = re.sub(r"[\$,]", "", s)
    # Handle parentheses for negative numbers
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]

    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _parse_foil_date(value: Any) -> datetime | None:
    """Parse date value from FOIL data."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    if isinstance(value, datetime):
        return value

    s = str(value).strip()
    if not s:
        return None

    formats = [
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%m-%d-%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%m/%d/%y",
        "%d-%b-%Y",
        "%b %d, %Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue

    return None


def _update_foil_raw_row_status(
    conn: psycopg.Connection,
    dataset_id: str,
    row_index: int,
    status: str,
    judgment_id: str | None = None,
) -> None:
    """Update raw row validation status."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE intake.foil_raw_rows
            SET validation_status = %s,
                judgment_id = %s
            WHERE dataset_id = %s AND row_index = %s
            """,
            (status, judgment_id, dataset_id, row_index),
        )
        conn.commit()


def _quarantine_foil_row(
    conn: psycopg.Connection,
    dataset_id: str,
    row_index: int,
    raw_data: dict[str, Any],
    reason: str,
    error_message: str,
    mapped_data: dict[str, Any] | None = None,
) -> None:
    """Add a row to the quarantine table."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO intake.foil_quarantine (
                dataset_id,
                row_index,
                raw_data,
                quarantine_reason,
                error_message,
                mapped_data
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                dataset_id,
                row_index,
                json.dumps(raw_data, default=str),
                reason,
                error_message,
                json.dumps(mapped_data or {}, default=str),
            ),
        )

        # Update raw row status
        cur.execute(
            """
            UPDATE intake.foil_raw_rows
            SET validation_status = 'quarantined'
            WHERE dataset_id = %s AND row_index = %s
            """,
            (dataset_id, row_index),
        )
        conn.commit()


# =============================================================================
# Job Processing
# =============================================================================


def claim_pending_job(conn: psycopg.Connection) -> dict[str, Any] | None:
    """
    Claim a pending ingest_csv job using FOR UPDATE SKIP LOCKED.

    Returns the job row dict, or None if no jobs available.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        # Use text-based query since job_type might be enum or text
        cur.execute(
            """
            UPDATE ops.job_queue
            SET status = 'processing',
                locked_at = now(),
                attempts = attempts + 1
            WHERE id = (
                SELECT id FROM ops.job_queue
                WHERE job_type::text = %s
                  AND status::text = 'pending'
                  AND (locked_at IS NULL OR locked_at < now() - interval '%s minutes')
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
            """,
            (JOB_TYPE, LOCK_TIMEOUT_MINUTES),
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None


def mark_job_completed(conn: psycopg.Connection, job_id: str) -> None:
    """Mark a job as completed."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ops.job_queue
            SET status = 'completed', locked_at = NULL
            WHERE id = %s
            """,
            (job_id,),
        )
        conn.commit()


def mark_job_failed(conn: psycopg.Connection, job_id: str, error: str) -> None:
    """Mark a job as failed with error message."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ops.job_queue
            SET status = 'failed', locked_at = NULL, last_error = %s
            WHERE id = %s
            """,
            (error[:2000], job_id),  # Truncate error to avoid column overflow
        )
        conn.commit()


def update_batch_status(
    conn: psycopg.Connection,
    batch_id: str,
    status: str,
    row_count_valid: int = 0,
    error_summary: str | None = None,
) -> None:
    """Update the ingest_batches status."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ops.ingest_batches
            SET status = %s,
                row_count_valid = %s,
                processed_at = now(),
                error_summary = %s
            WHERE id = %s
            """,
            (status, row_count_valid, error_summary, batch_id),
        )
        conn.commit()


def load_csv_from_storage(file_path: str) -> pd.DataFrame:
    """
    Load a CSV file from Supabase Storage or local filesystem.

    Args:
        file_path: Path in storage bucket (e.g., 'intake/batch_123.csv')
                   OR local path prefixed with 'file://' for testing

    Returns:
        pandas DataFrame with CSV contents
    """
    # Support local file paths for testing (file:// prefix)
    if file_path.startswith("file://"):
        local_path = file_path[7:]  # Strip 'file://' prefix
        logger.info(f"Loading CSV from local path: {local_path}")
        try:
            df = pd.read_csv(local_path)
            logger.info(f"Loaded {len(df)} rows from local file")
            return df
        except Exception as e:
            logger.error(f"Failed to load local CSV: {e}")
            raise

    client = create_supabase_client()

    # Parse bucket and path
    # Expected format: "bucket_name/path/to/file.csv" or just "path/to/file.csv"
    parts = file_path.split("/", 1)
    if len(parts) == 2 and parts[0] in ("intake", "imports", "csv"):
        bucket = parts[0]
        path = parts[1]
    else:
        bucket = "intake"
        path = file_path

    logger.info(f"Downloading CSV from storage: bucket={bucket}, path={path}")

    try:
        response = client.storage.from_(bucket).download(path)
        df = pd.read_csv(io.BytesIO(response))
        logger.info(f"Loaded {len(df)} rows from {file_path}")
        return df
    except Exception as e:
        logger.error(f"Failed to load CSV from storage: {e}")
        raise


def generate_collectability_score() -> int:
    """Generate a random collectability score between 0-100."""
    return random.randint(0, 100)


def insert_judgments(conn: psycopg.Connection, df: pd.DataFrame, batch_id: str) -> int:
    """
    Insert judgment rows from DataFrame into public.judgments.

    Auto-detects format:
    - Simplicity format: Uses hardened mapper with strict validation
    - FOIL format: Uses FoilMapper with bulk insert optimization
    - Generic format: Uses flexible column mapping with fallbacks

    Returns:
        Number of rows successfully inserted
    """
    # Check if this is Simplicity format (has all required Simplicity columns)
    if _is_simplicity_format(df):
        logger.info(f"Detected Simplicity format CSV ({len(df)} rows)")
        return process_simplicity_frame(conn, df, batch_id)

    # Check if this is FOIL format (abbreviated court columns)
    if _is_foil_format(df):
        logger.info(f"Detected FOIL format CSV ({len(df)} rows)")
        return process_foil_frame(conn, df, batch_id)

    # Generic format - use flexible column mapping
    logger.info(f"Using generic format processing ({len(df)} rows)")

    # Normalize column names
    df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]

    # Map common column name variations
    column_mapping = {
        "case_no": "case_number",
        "caseno": "case_number",
        "case_num": "case_number",
        "plaintiff": "plaintiff_name",
        "defendant": "defendant_name",
        "amount": "judgment_amount",
        "judgment_amt": "judgment_amount",
        "date": "entry_date",
        "jdgmt_date": "judgment_date",
    }
    df = df.rename(columns=column_mapping)

    inserted = 0
    errors = []

    with conn.cursor() as cur:
        for idx, row in df.iterrows():
            try:
                # Extract values with fallbacks
                case_number = row.get("case_number", f"INTAKE-{batch_id[:8]}-{idx}")
                plaintiff_name = row.get("plaintiff_name", "Unknown Plaintiff")
                defendant_name = row.get("defendant_name", "Unknown Defendant")

                # Handle numeric judgment amount
                judgment_amount = row.get("judgment_amount")
                if pd.isna(judgment_amount):
                    judgment_amount = 0.0
                else:
                    try:
                        judgment_amount = float(
                            str(judgment_amount).replace(",", "").replace("$", "")
                        )
                    except (ValueError, TypeError):
                        judgment_amount = 0.0

                # Handle dates
                entry_date = row.get("entry_date") or row.get("judgment_date")
                if pd.notna(entry_date):
                    try:
                        entry_date = pd.to_datetime(entry_date).date()
                    except Exception:
                        entry_date = None
                else:
                    entry_date = None

                collectability_score = generate_collectability_score()

                cur.execute(
                    """
                    INSERT INTO public.judgments (
                        case_number,
                        plaintiff_name,
                        defendant_name,
                        judgment_amount,
                        entry_date,
                        collectability_score,
                        court,
                        county,
                        source_file,
                        status,
                        created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', now()
                    )
                    ON CONFLICT (case_number) DO UPDATE SET
                        collectability_score = EXCLUDED.collectability_score,
                        updated_at = now()
                    """,
                    (
                        str(case_number),
                        str(plaintiff_name)[:500],
                        str(defendant_name)[:500],
                        judgment_amount,
                        entry_date,
                        collectability_score,
                        row.get("court", None),
                        row.get("county", None),
                        f"batch:{batch_id}",
                    ),
                )
                inserted += 1

            except Exception as e:
                errors.append(f"Row {idx}: {str(e)[:100]}")
                logger.warning(f"Failed to insert row {idx}: {e}")

        conn.commit()

    if errors:
        logger.warning(f"{len(errors)} rows failed during insert")

    return inserted


def process_job(conn: psycopg.Connection, job: dict[str, Any]) -> None:
    """
    Process a single ingest_csv job.

    Expected payload:
    {
        "file_path": "intake/batch_123.csv",
        "batch_id": "uuid-of-ingest-batch"
    }
    """
    job_id = str(job["id"])
    payload = job.get("payload", {})

    file_path = payload.get("file_path")
    batch_id = payload.get("batch_id")

    run_id = str(uuid4())[:8]
    logger.info(f"[{run_id}] Processing job {job_id}: file_path={file_path}, batch_id={batch_id}")

    if not file_path:
        error = "Missing file_path in job payload"
        logger.error(f"[{run_id}] {error}")
        mark_job_failed(conn, job_id, error)
        if batch_id:
            update_batch_status(conn, batch_id, "failed", error_summary=error)
        return

    try:
        # Load CSV from storage
        df = load_csv_from_storage(file_path)

        if df.empty:
            logger.warning(f"[{run_id}] CSV is empty: {file_path}")
            mark_job_completed(conn, job_id)
            if batch_id:
                update_batch_status(conn, batch_id, "completed", row_count_valid=0)
            return

        # Insert judgments
        inserted = insert_judgments(conn, df, batch_id or job_id)

        logger.info(f"[{run_id}] Inserted {inserted}/{len(df)} judgments")

        # Mark success
        mark_job_completed(conn, job_id)
        if batch_id:
            update_batch_status(conn, batch_id, "completed", row_count_valid=inserted)

        logger.info(f"[{run_id}] Job {job_id} completed successfully")

    except Exception as e:
        error_msg = str(e)[:500]
        logger.exception(f"[{run_id}] Job {job_id} failed: {e}")
        mark_job_failed(conn, job_id, error_msg)
        if batch_id:
            update_batch_status(conn, batch_id, "failed", error_summary=error_msg)


# =============================================================================
# Worker Loop
# =============================================================================


def run_worker_loop() -> None:
    """
    Main worker loop - polls for pending jobs and processes them.
    """
    env = get_supabase_env()
    dsn = get_supabase_db_url(env)

    logger.info(f"🚀 Starting Ingest Processor Worker (env={env})")
    logger.info(f"   Poll interval: {POLL_INTERVAL_SECONDS}s")
    logger.info(f"   Job type: {JOB_TYPE}")

    conn = psycopg.connect(dsn)

    try:
        while True:
            try:
                job = claim_pending_job(conn)

                if job:
                    logger.info(f"Claimed job: {job['id']}")
                    process_job(conn, job)
                else:
                    # No jobs available, sleep before polling again
                    import time

                    time.sleep(POLL_INTERVAL_SECONDS)

            except psycopg.OperationalError as e:
                logger.error(f"Database connection error: {e}")
                # Reconnect
                try:
                    conn.close()
                except Exception:
                    pass
                import time

                time.sleep(5)
                conn = psycopg.connect(dsn)

            except KeyboardInterrupt:
                logger.info("Worker interrupted by user")
                break

            except Exception as e:
                logger.exception(f"Unexpected error in worker loop: {e}")
                import time

                time.sleep(POLL_INTERVAL_SECONDS)

    finally:
        conn.close()
        logger.info("Worker shutdown complete")


# =============================================================================
# Entry Point
# =============================================================================


if __name__ == "__main__":
    run_worker_loop()
