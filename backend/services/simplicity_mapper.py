#!/usr/bin/env python3
"""
Simplicity Vendor Data Mapper

Transforms Simplicity vendor CSV exports into canonical judgment records.
Designed for the Dec 29th vendor data export with robust error handling
and per-row validation.

Column Mapping (Simplicity → Canonical):
    - Case Number  → case_number
    - Plaintiff    → plaintiff_name
    - Defendant    → defendant_name
    - Judgment Amount → judgment_amount
    - Filing Date  → entry_date
    - County       → county
    - Court        → court (optional)

Architecture:
    1. Stage raw rows to intake.simplicity_raw_rows
    2. Transform/validate to intake.simplicity_validated_rows
    3. Upsert valid rows to public.judgments
    4. Log failed rows to intake.simplicity_failed_rows
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import pandas as pd

if TYPE_CHECKING:
    import psycopg

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Required columns for Simplicity format (case-insensitive matching)
SIMPLICITY_REQUIRED_COLUMNS = ["Case Number", "Plaintiff", "Defendant", "Judgment Amount"]

# All expected Simplicity columns with variations
SIMPLICITY_COLUMN_MAPPING = {
    # Required fields
    "case number": "case_number",
    "case_number": "case_number",
    "case no": "case_number",
    "case_no": "case_number",
    "caseno": "case_number",
    "case #": "case_number",
    # Plaintiff variations
    "plaintiff": "plaintiff_name",
    "plaintiff name": "plaintiff_name",
    "plaintiff_name": "plaintiff_name",
    "plf": "plaintiff_name",
    "plf name": "plaintiff_name",
    # Defendant variations
    "defendant": "defendant_name",
    "defendant name": "defendant_name",
    "defendant_name": "defendant_name",
    "def": "defendant_name",
    "def name": "defendant_name",
    # Amount variations
    "judgment amount": "judgment_amount",
    "judgment_amount": "judgment_amount",
    "amount": "judgment_amount",
    "amt": "judgment_amount",
    "judgment amt": "judgment_amount",
    "amount awarded": "judgment_amount",
    "amount_awarded": "judgment_amount",
    "orig amt": "judgment_amount",
    # Date variations
    "filing date": "entry_date",
    "filing_date": "entry_date",
    "file date": "entry_date",
    "date filed": "entry_date",
    "entry date": "entry_date",
    "entry_date": "entry_date",
    "judgment date": "judgment_date",
    "judgment_date": "judgment_date",
    "jdgmt date": "judgment_date",
    # Location variations
    "county": "county",
    "court": "court",
    "court name": "court",
    "court_name": "court",
}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class MappedRow:
    """A single row transformed from Simplicity format to canonical fields."""

    case_number: str
    plaintiff_name: Optional[str] = None
    defendant_name: Optional[str] = None
    judgment_amount: Optional[Decimal] = None
    entry_date: Optional[date] = None
    judgment_date: Optional[date] = None
    county: Optional[str] = None
    court: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def is_valid(self) -> bool:
        """Check if row passed validation (no errors)."""
        return len(self.errors) == 0

    def to_insert_dict(self) -> Dict[str, Any]:
        """Convert to dict for database insert."""
        return {
            "case_number": self.case_number,
            "plaintiff_name": self.plaintiff_name,
            "defendant_name": self.defendant_name,
            "judgment_amount": float(self.judgment_amount) if self.judgment_amount else None,
            "entry_date": self.entry_date,
            "judgment_date": self.judgment_date,
            "county": self.county,
            "court": self.court,
        }


@dataclass
class ColumnMapping:
    """Result of column detection and mapping."""

    raw_to_canonical: Dict[str, str]  # Original column name → canonical name
    unmapped_columns: List[str]  # Columns we couldn't map
    missing_required: List[str]  # Required fields not found
    confidence: float  # 0-100 confidence score

    @property
    def is_valid(self) -> bool:
        """Check if mapping has all required fields."""
        return len(self.missing_required) == 0


@dataclass
class BatchResult:
    """Result of processing a Simplicity batch."""

    batch_id: str
    total_rows: int
    staged_rows: int
    valid_rows: int
    invalid_rows: int
    inserted_rows: int
    duplicate_rows: int
    error_summary: Optional[str] = None


# =============================================================================
# SimplicityMapper Class
# =============================================================================


class SimplicityMapper:
    """
    Transforms Simplicity vendor CSV data to canonical judgment format.

    Usage:
        mapper = SimplicityMapper()
        mapping = mapper.detect_column_mapping(df)
        if mapping.is_valid:
            rows = mapper.transform_dataframe(df, mapping)
            valid = [r for r in rows if r.is_valid()]
    """

    def __init__(self) -> None:
        """Initialize the mapper."""
        self._column_mapping = SIMPLICITY_COLUMN_MAPPING

    def detect_column_mapping(self, df: pd.DataFrame) -> ColumnMapping:
        """
        Detect and map DataFrame columns to canonical field names.

        Returns a ColumnMapping with:
        - raw_to_canonical: mapping of original → canonical names
        - unmapped_columns: columns we couldn't identify
        - missing_required: required fields not found
        - confidence: 0-100 score
        """
        raw_to_canonical: Dict[str, str] = {}
        unmapped: List[str] = []
        found_canonical: set[str] = set()

        for col in df.columns:
            normalized = col.lower().strip()
            if normalized in self._column_mapping:
                canonical = self._column_mapping[normalized]
                raw_to_canonical[col] = canonical
                found_canonical.add(canonical)
            else:
                unmapped.append(col)

        # Check for required fields
        required = {"case_number", "plaintiff_name", "defendant_name", "judgment_amount"}
        missing = list(required - found_canonical)

        # Calculate confidence
        total_expected = len(required) + 3  # Required + entry_date, county, court
        found = len(found_canonical)
        confidence = min(100.0, (found / total_expected) * 100)

        return ColumnMapping(
            raw_to_canonical=raw_to_canonical,
            unmapped_columns=unmapped,
            missing_required=missing,
            confidence=round(confidence, 1),
        )

    def transform_dataframe(self, df: pd.DataFrame, mapping: ColumnMapping) -> List[MappedRow]:
        """
        Transform all rows in DataFrame using the detected mapping.

        Returns list of MappedRow objects (both valid and invalid).
        Invalid rows have errors populated.
        """
        rows: List[MappedRow] = []

        for idx, row in df.iterrows():
            raw_data = row.to_dict()
            mapped = self._transform_row(raw_data, mapping)
            rows.append(mapped)

        return rows

    def _transform_row(self, raw: Dict[str, Any], mapping: ColumnMapping) -> MappedRow:
        """
        Transform a single raw row to MappedRow.

        Applies:
        - Column mapping
        - Type coercion (currency, dates)
        - Validation
        """
        errors: List[str] = []
        warnings: List[str] = []

        # Extract values using mapping
        def get_mapped(canonical: str) -> Any:
            for raw_col, can in mapping.raw_to_canonical.items():
                if can == canonical:
                    return raw.get(raw_col)
            return None

        # Case number (required)
        case_number = self._clean_string(get_mapped("case_number"))
        if not case_number:
            errors.append("Missing required field: case_number")
            case_number = f"MISSING-{id(raw)}"

        # Plaintiff name
        plaintiff_name = self._clean_string(get_mapped("plaintiff_name"))
        if not plaintiff_name:
            errors.append("Missing required field: plaintiff_name")

        # Defendant name
        defendant_name = self._clean_string(get_mapped("defendant_name"))
        if not defendant_name:
            errors.append("Missing required field: defendant_name")

        # Judgment amount
        judgment_amount: Optional[Decimal] = None
        raw_amount = get_mapped("judgment_amount")
        if raw_amount is not None:
            try:
                judgment_amount = self._clean_currency(raw_amount)
                if judgment_amount is not None and judgment_amount < 0:
                    errors.append(f"Negative judgment amount: {judgment_amount}")
            except ValueError as e:
                errors.append(f"Invalid judgment amount: {e}")

        # Entry date (Filing Date)
        entry_date: Optional[date] = None
        raw_entry = get_mapped("entry_date")
        if raw_entry is not None:
            try:
                entry_date = self._parse_date(raw_entry)
            except ValueError as e:
                warnings.append(f"Invalid entry_date: {e}")

        # Judgment date
        judgment_date: Optional[date] = None
        raw_jdate = get_mapped("judgment_date")
        if raw_jdate is not None:
            try:
                judgment_date = self._parse_date(raw_jdate)
            except ValueError as e:
                warnings.append(f"Invalid judgment_date: {e}")

        # County
        county = self._clean_string(get_mapped("county"))

        # Court
        court = self._clean_string(get_mapped("court"))

        return MappedRow(
            case_number=case_number,
            plaintiff_name=plaintiff_name,
            defendant_name=defendant_name,
            judgment_amount=judgment_amount,
            entry_date=entry_date,
            judgment_date=judgment_date,
            county=county,
            court=court,
            raw_data=raw,
            errors=errors,
            warnings=warnings,
        )

    def _clean_string(self, value: Any) -> Optional[str]:
        """Clean and normalize a string value."""
        if value is None:
            return None
        if pd.isna(value):
            return None
        s = str(value).strip()
        return s if s else None

    def _clean_currency(self, value: Any) -> Optional[Decimal]:
        """
        Convert currency string to Decimal.

        Handles:
        - "$1,200.00" → Decimal("1200.00")
        - "1200.00" → Decimal("1200.00")
        - "  500 " → Decimal("500")
        - "" / None → None
        """
        if value is None:
            return None

        if pd.isna(value):
            return None

        if isinstance(value, (int, float)):
            return Decimal(str(value))

        if isinstance(value, Decimal):
            return value

        s = str(value).strip()
        if not s:
            return None

        # Remove currency symbols, commas, whitespace
        cleaned = re.sub(r"[$,\s]", "", s)

        # Handle parentheses for negative (e.g., "(500.00)")
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = "-" + cleaned[1:-1]

        try:
            return Decimal(cleaned)
        except InvalidOperation:
            raise ValueError(f"Cannot parse currency: '{value}'")

    def _parse_date(self, value: Any) -> Optional[date]:
        """
        Parse date string in various formats.

        Handles:
        - "MM/DD/YYYY" (Simplicity standard)
        - "YYYY-MM-DD" (ISO)
        - "M/D/YY"
        - datetime objects
        """
        if value is None:
            return None

        if pd.isna(value):
            return None

        if isinstance(value, date):
            return value

        if isinstance(value, datetime):
            return value.date()

        s = str(value).strip()
        if not s:
            return None

        # Try common formats
        formats = [
            "%m/%d/%Y",  # 01/15/2024 (Simplicity standard)
            "%Y-%m-%d",  # 2024-01-15 (ISO)
            "%m/%d/%y",  # 01/15/24
            "%m-%d-%Y",  # 01-15-2024
            "%d/%m/%Y",  # 15/01/2024 (European)
        ]

        for fmt in formats:
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue

        # Try pandas as last resort
        try:
            return pd.to_datetime(s).date()
        except Exception:
            pass

        raise ValueError(f"Cannot parse date: '{value}'")


# =============================================================================
# Batch Processing Functions
# =============================================================================


def is_simplicity_format(df: pd.DataFrame) -> bool:
    """
    Check if DataFrame appears to be in Simplicity format.

    Returns True if all required columns are present (case-insensitive).
    """
    if df.empty:
        return False

    normalized_cols = {c.lower().strip() for c in df.columns}

    # Check for required columns (using any recognized variation)
    required_patterns = [
        {"case number", "case_number", "case no", "case_no", "caseno"},
        {"plaintiff", "plaintiff name", "plaintiff_name"},
        {"defendant", "defendant name", "defendant_name"},
        {"judgment amount", "judgment_amount", "amount", "amt", "amount awarded", "amount_awarded"},
    ]

    for patterns in required_patterns:
        if not any(p in normalized_cols for p in patterns):
            return False

    return True


def create_batch(
    conn: "psycopg.Connection",
    filename: str,
    source_reference: Optional[str] = None,
    created_by: Optional[str] = None,
) -> str:
    """
    Create a new Simplicity batch record.

    Returns the batch ID (UUID as string).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO intake.simplicity_batches (filename, source_reference, created_by)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (filename, source_reference, created_by),
        )
        result = cur.fetchone()
        conn.commit()
        if result is None:
            raise RuntimeError("Failed to create batch - no ID returned")
        # Support both tuple (default cursor) and dict (dict_row factory)
        batch_id = result["id"] if isinstance(result, dict) else result[0]
        return str(batch_id)


def check_duplicate_batch(conn: "psycopg.Connection", source_reference: str) -> Optional[str]:
    """
    Check if a batch with this source_reference already exists.

    Returns the existing batch_id if found, None otherwise.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM intake.simplicity_batches
            WHERE source_reference = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (source_reference,),
        )
        result = cur.fetchone()
        if result is None:
            return None
        # Support both tuple (default cursor) and dict (dict_row factory)
        batch_id = result["id"] if isinstance(result, dict) else result[0]
        return str(batch_id)


def stage_raw_rows(
    conn: "psycopg.Connection",
    batch_id: str,
    df: pd.DataFrame,
) -> int:
    """
    Stage raw DataFrame rows to intake.simplicity_raw_rows.

    Updates batch status to 'staging' then 'transforming'.
    Returns number of rows staged.
    """
    import json

    # Update batch status
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE intake.simplicity_batches
            SET status = 'staging', row_count_total = %s
            WHERE id = %s
            """,
            (len(df), batch_id),
        )
        conn.commit()

    # Stage rows
    staged = 0
    with conn.cursor() as cur:
        for idx, row in df.iterrows():
            raw_json = json.dumps(row.to_dict(), default=str)
            cur.execute(
                """
                INSERT INTO intake.simplicity_raw_rows (batch_id, row_index, raw_data)
                VALUES (%s, %s, %s)
                """,
                (batch_id, int(idx) if isinstance(idx, (int, float)) else staged, raw_json),
            )
            staged += 1

        # Update batch counts and status
        cur.execute(
            """
            UPDATE intake.simplicity_batches
            SET status = 'transforming', row_count_staged = %s, staged_at = now()
            WHERE id = %s
            """,
            (staged, batch_id),
        )
        conn.commit()

    return staged


def store_validated_rows(
    conn: "psycopg.Connection",
    batch_id: str,
    rows: List[MappedRow],
) -> Tuple[int, int]:
    """
    Store validated rows to intake.simplicity_validated_rows.
    Failed rows go to intake.simplicity_failed_rows.

    Returns (valid_count, invalid_count).
    """
    valid_count = 0
    invalid_count = 0
    import json

    with conn.cursor() as cur:
        for idx, row in enumerate(rows):
            if row.is_valid():
                try:
                    cur.execute(
                        """
                        INSERT INTO intake.simplicity_validated_rows (
                            batch_id, row_index, case_number, plaintiff_name, defendant_name,
                            judgment_amount, entry_date, judgment_date, county, court,
                            validation_status, validation_warnings
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (batch_id, case_number) DO UPDATE SET
                            plaintiff_name = EXCLUDED.plaintiff_name,
                            defendant_name = EXCLUDED.defendant_name,
                            judgment_amount = EXCLUDED.judgment_amount,
                            entry_date = EXCLUDED.entry_date,
                            judgment_date = EXCLUDED.judgment_date,
                            county = EXCLUDED.county,
                            court = EXCLUDED.court,
                            validation_warnings = EXCLUDED.validation_warnings
                        """,
                        (
                            batch_id,
                            idx,
                            row.case_number,
                            row.plaintiff_name,
                            row.defendant_name,
                            float(row.judgment_amount) if row.judgment_amount else None,
                            row.entry_date,
                            row.judgment_date,
                            row.county,
                            row.court,
                            "warning" if row.warnings else "valid",
                            row.warnings if row.warnings else None,
                        ),
                    )
                    valid_count += 1
                except Exception as e:
                    # Row itself failed DB insert - treat as invalid
                    logger.warning(f"Row {idx} failed validated insert: {e}")
                    cur.execute(
                        """
                        INSERT INTO intake.simplicity_failed_rows (
                            batch_id, row_index, error_stage, error_code, error_message, raw_data
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            batch_id,
                            idx,
                            "transform",
                            "DB_ERROR",
                            str(e)[:500],
                            json.dumps(row.raw_data, default=str),
                        ),
                    )
                    invalid_count += 1
            else:
                # Row has validation errors
                cur.execute(
                    """
                    INSERT INTO intake.simplicity_failed_rows (
                        batch_id, row_index, error_stage, error_code, error_message, raw_data
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        batch_id,
                        idx,
                        "validate",
                        "VALIDATION_ERROR",
                        "; ".join(row.errors),
                        json.dumps(row.raw_data, default=str),
                    ),
                )
                invalid_count += 1

        # Update batch counts and status
        cur.execute(
            """
            UPDATE intake.simplicity_batches
            SET status = 'upserting', row_count_valid = %s, row_count_invalid = %s, transformed_at = now()
            WHERE id = %s
            """,
            (valid_count, invalid_count, batch_id),
        )
        conn.commit()

    return valid_count, invalid_count


def upsert_to_judgments(
    conn: "psycopg.Connection",
    batch_id: str,
    source_file: Optional[str] = None,
) -> Tuple[int, int]:
    """
    Upsert validated rows from intake.simplicity_validated_rows to public.judgments.

    Uses ON CONFLICT (case_number) DO UPDATE for idempotent upserts.
    Returns (inserted_count, duplicate_count).
    """
    import random

    if source_file is None:
        source_file = f"simplicity-batch:{batch_id}"

    inserted = 0
    duplicates = 0

    with conn.cursor() as cur:
        # Fetch validated rows for this batch
        cur.execute(
            """
            SELECT case_number, plaintiff_name, defendant_name, judgment_amount,
                   entry_date, judgment_date, county, court
            FROM intake.simplicity_validated_rows
            WHERE batch_id = %s AND validation_status IN ('valid', 'warning')
            """,
            (batch_id,),
        )
        rows = cur.fetchall()

        for row in rows:
            # Support both dict_row (from worker) and tuple row factories
            if isinstance(row, dict):
                case_number = row["case_number"]
                plaintiff_name = row["plaintiff_name"]
                defendant_name = row["defendant_name"]
                judgment_amount = row["judgment_amount"]
                entry_date = row["entry_date"]
                judgment_date = row["judgment_date"]
                county = row["county"]
                court = row["court"]
            else:
                (
                    case_number,
                    plaintiff_name,
                    defendant_name,
                    judgment_amount,
                    entry_date,
                    judgment_date,
                    county,
                    court,
                ) = row

            # Generate collectability score for new records
            collectability_score = random.randint(0, 100)

            try:
                cur.execute(
                    """
                    INSERT INTO public.judgments (
                        case_number, plaintiff_name, defendant_name, judgment_amount,
                        entry_date, judgment_date, county, court, collectability_score,
                        source_file, status, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', now())
                    ON CONFLICT (case_number) DO UPDATE SET
                        plaintiff_name = COALESCE(EXCLUDED.plaintiff_name, public.judgments.plaintiff_name),
                        defendant_name = COALESCE(EXCLUDED.defendant_name, public.judgments.defendant_name),
                        judgment_amount = EXCLUDED.judgment_amount,
                        entry_date = COALESCE(EXCLUDED.entry_date, public.judgments.entry_date),
                        judgment_date = COALESCE(EXCLUDED.judgment_date, public.judgments.judgment_date),
                        county = COALESCE(EXCLUDED.county, public.judgments.county),
                        court = COALESCE(EXCLUDED.court, public.judgments.court),
                        updated_at = now()
                    RETURNING (xmax = 0) AS inserted
                    """,
                    (
                        case_number,
                        plaintiff_name,
                        defendant_name,
                        judgment_amount,
                        entry_date,
                        judgment_date,
                        county,
                        court,
                        collectability_score,
                        source_file,
                    ),
                )
                result = cur.fetchone()
                # Support both tuple and dict row factories
                inserted_flag = result["inserted"] if isinstance(result, dict) else result[0]
                if result and inserted_flag:  # xmax = 0 means INSERT (not UPDATE)
                    inserted += 1
                else:
                    duplicates += 1

            except Exception as e:
                logger.warning(f"Failed to upsert case {case_number}: {e}")
                duplicates += 1  # Count as duplicate/skip

        # Update batch status to completed
        cur.execute(
            """
            UPDATE intake.simplicity_batches
            SET status = 'completed', row_count_inserted = %s, completed_at = now()
            WHERE id = %s
            """,
            (inserted, batch_id),
        )
        conn.commit()

    return inserted, duplicates


def process_simplicity_batch(
    conn: "psycopg.Connection",
    df: pd.DataFrame,
    filename: str,
    source_reference: Optional[str] = None,
) -> BatchResult:
    """
    Process a complete Simplicity batch through the 3-step pipeline.

    Steps:
        1. Stage: Store raw rows in intake.simplicity_raw_rows
        2. Transform: Map and validate to intake.simplicity_validated_rows
        3. Upsert: Insert valid rows to public.judgments

    Returns BatchResult with counts and status.
    """
    # Check for duplicate batch
    if source_reference:
        existing = check_duplicate_batch(conn, source_reference)
        if existing:
            logger.warning(
                f"Batch with source_reference '{source_reference}' already exists: {existing}"
            )
            return BatchResult(
                batch_id=existing,
                total_rows=len(df),
                staged_rows=0,
                valid_rows=0,
                invalid_rows=0,
                inserted_rows=0,
                duplicate_rows=len(df),
                error_summary=f"Duplicate batch: {existing}",
            )

    # Create batch record
    batch_id = create_batch(conn, filename, source_reference)
    logger.info(f"Created Simplicity batch {batch_id} for {filename} ({len(df)} rows)")

    try:
        # Step 1: Stage raw rows
        staged = stage_raw_rows(conn, batch_id, df)
        logger.info(f"[{batch_id[:8]}] Staged {staged} raw rows")

        # Step 2: Transform and validate
        mapper = SimplicityMapper()
        mapping = mapper.detect_column_mapping(df)

        if not mapping.is_valid:
            error = f"Missing required columns: {mapping.missing_required}"
            logger.error(f"[{batch_id[:8]}] {error}")
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE intake.simplicity_batches
                    SET status = 'failed', error_summary = %s
                    WHERE id = %s
                    """,
                    (error, batch_id),
                )
                conn.commit()
            return BatchResult(
                batch_id=batch_id,
                total_rows=len(df),
                staged_rows=staged,
                valid_rows=0,
                invalid_rows=len(df),
                inserted_rows=0,
                duplicate_rows=0,
                error_summary=error,
            )

        rows = mapper.transform_dataframe(df, mapping)
        valid_count, invalid_count = store_validated_rows(conn, batch_id, rows)
        logger.info(f"[{batch_id[:8]}] Validated: {valid_count} valid, {invalid_count} invalid")

        # Step 3: Upsert to judgments
        inserted, duplicates = upsert_to_judgments(conn, batch_id)
        logger.info(f"[{batch_id[:8]}] Upserted: {inserted} inserted, {duplicates} duplicates")

        return BatchResult(
            batch_id=batch_id,
            total_rows=len(df),
            staged_rows=staged,
            valid_rows=valid_count,
            invalid_rows=invalid_count,
            inserted_rows=inserted,
            duplicate_rows=duplicates,
        )

    except Exception as e:
        logger.exception(f"[{batch_id[:8]}] Batch failed: {e}")
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE intake.simplicity_batches
                SET status = 'failed', error_summary = %s
                WHERE id = %s
                """,
                (str(e)[:500], batch_id),
            )
            conn.commit()
        return BatchResult(
            batch_id=batch_id,
            total_rows=len(df),
            staged_rows=0,
            valid_rows=0,
            invalid_rows=0,
            inserted_rows=0,
            duplicate_rows=0,
            error_summary=str(e)[:500],
        )
