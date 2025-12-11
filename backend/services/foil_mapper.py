"""
Dragonfly Engine - FOIL Mapper

Maps messy FOIL (Freedom of Information Law) court data columns to the
canonical public.judgments schema. Handles varying column names, data formats,
and provides auto-detection with confidence scoring.

Architecture:
- FoilMapper: Main class for column mapping and row transformation
- Uses pattern matching to detect canonical fields from messy column names
- Supports bulk operations via copy_from for high-speed ingestion
- Integrates with raw.foil_datasets for tracking and audit

Usage:
    mapper = FoilMapper()
    mapping = mapper.detect_column_mapping(df)
    canonical_rows = mapper.transform_dataframe(df, mapping)
"""

from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import pandas as pd
import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# =============================================================================
# Column Pattern Definitions
# =============================================================================

# Default patterns for auto-detecting canonical fields
# Keys are canonical judgment field names, values are regex patterns to match
DEFAULT_COLUMN_PATTERNS: dict[str, list[str]] = {
    "case_number": [
        r"(?i)^case[\s_-]?(?:no|num|number|#)\.?$",
        r"(?i)^case[\s_-]?id$",
        r"(?i)^caseno$",
        r"(?i)^docket[\s_-]?(?:no|num|number)?$",
        r"(?i)^index[\s_-]?(?:no|num|number)?$",
    ],
    "defendant_name": [
        r"(?i)^def(?:endant)?[\s_.-]?(?:name)?$",
        r"(?i)^debtor[\s_-]?(?:name)?$",
        r"(?i)^judgment[\s_-]?debtor$",
        r"(?i)^def\.?\s*name$",
    ],
    "plaintiff_name": [
        r"(?i)^pl(?:ain)?t(?:iff)?[\s_.-]?(?:name)?$",
        r"(?i)^creditor[\s_-]?(?:name)?$",
        r"(?i)^judgment[\s_-]?creditor$",
        r"(?i)^plf\.?\s*name$",
    ],
    "judgment_amount": [
        r"(?i)^(?:judgment[\s_-]?)?(?:amt|amount)$",
        r"(?i)^total[\s_-]?(?:judgment|amt|amount)$",
        r"(?i)^original[\s_-]?(?:judgment|amount)$",
        r"(?i)^principal$",
        r"(?i)^balance$",
    ],
    "filing_date": [
        r"(?i)^(?:date[\s_-]?)?filed$",
        r"(?i)^filing[\s_-]?date$",
        r"(?i)^file[\s_-]?date$",
        r"(?i)^date[\s_-]?filed$",
    ],
    "judgment_date": [
        r"(?i)^(?:jud?g(?:e?ment)?[\s_.-]?)?date$",
        r"(?i)^entry[\s_-]?date$",
        r"(?i)^judgment[\s_-]?entered$",
        r"(?i)^date[\s_-]?(?:of[\s_-]?)?judgment$",
    ],
    "county": [
        r"(?i)^county$",
        r"(?i)^venue$",
        r"(?i)^jurisdiction$",
        r"(?i)^location$",
    ],
    "court": [
        r"(?i)^court(?:[\s_-]?name)?$",
        r"(?i)^court[\s_-]?type$",
        r"(?i)^tribunal$",
    ],
    "defendant_address": [
        r"(?i)^def(?:endant)?[\s_.-]?addr(?:ess)?$",
        r"(?i)^debtor[\s_-]?addr(?:ess)?$",
        r"(?i)^address$",
    ],
}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ColumnMapping:
    """Result of column mapping detection."""

    raw_to_canonical: dict[str, str]  # {"Def. Name": "defendant_name", ...}
    canonical_to_raw: dict[str, str]  # {"defendant_name": "Def. Name", ...}
    unmapped_columns: list[str]  # Columns that couldn't be mapped
    confidence: float  # 0-100 confidence score
    required_missing: list[str]  # Required fields that are missing

    @property
    def is_valid(self) -> bool:
        """Check if mapping has minimum required fields."""
        required = {"case_number", "judgment_amount"}
        mapped = set(self.canonical_to_raw.keys())
        return required.issubset(mapped)


@dataclass
class MappedRow:
    """A single row mapped to canonical schema."""

    case_number: str
    defendant_name: Optional[str] = None
    plaintiff_name: Optional[str] = None
    judgment_amount: Optional[Decimal] = None
    filing_date: Optional[datetime] = None
    judgment_date: Optional[datetime] = None
    county: Optional[str] = None
    court: Optional[str] = None
    defendant_address: Optional[str] = None
    raw_data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def is_valid(self) -> bool:
        """Check if row passes minimum validation."""
        return bool(self.case_number and self.judgment_amount is not None)

    def to_insert_dict(self) -> dict[str, Any]:
        """Convert to dict for database insertion."""
        return {
            "case_number": self.case_number,
            "defendant_name": self.defendant_name,
            "plaintiff_name": self.plaintiff_name,
            "judgment_amount": self.judgment_amount,
            "filing_date": self.filing_date.date().isoformat() if self.filing_date else None,
            "entry_date": self.judgment_date.date().isoformat() if self.judgment_date else None,
            "county": self.county,
            "court": self.court,
        }


@dataclass
class FoilProcessingResult:
    """Result of processing a FOIL dataset."""

    dataset_id: str
    total_rows: int
    mapped_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    success_rate: float
    errors: list[dict[str, Any]]
    duration_seconds: float


# =============================================================================
# FOIL Mapper Class
# =============================================================================


class FoilMapper:
    """
    Maps messy FOIL data columns to canonical judgment schema.

    Supports:
    - Auto-detection of columns via regex patterns
    - Custom column mapping overrides
    - Data type conversion and validation
    - Bulk insert optimization via COPY
    """

    def __init__(
        self,
        column_patterns: Optional[dict[str, list[str]]] = None,
        explicit_mapping: Optional[dict[str, str]] = None,
    ):
        """
        Initialize FoilMapper.

        Args:
            column_patterns: Custom regex patterns for column detection
            explicit_mapping: Explicit raw->canonical column mapping to use
        """
        self.column_patterns = column_patterns or DEFAULT_COLUMN_PATTERNS
        self.explicit_mapping = explicit_mapping or {}

    def detect_column_mapping(self, df: pd.DataFrame) -> ColumnMapping:
        """
        Detect column mapping from DataFrame headers.

        Uses regex pattern matching to identify canonical fields.

        Args:
            df: DataFrame with raw FOIL data

        Returns:
            ColumnMapping with detected mappings and confidence score
        """
        raw_to_canonical: dict[str, str] = {}
        canonical_to_raw: dict[str, str] = {}
        unmapped_columns: list[str] = []

        # First, apply any explicit mappings
        for raw_col, canonical_col in self.explicit_mapping.items():
            if raw_col in df.columns:
                raw_to_canonical[raw_col] = canonical_col
                canonical_to_raw[canonical_col] = raw_col

        # Then, try pattern matching for remaining columns
        for col in df.columns:
            if col in raw_to_canonical:
                continue  # Already mapped explicitly

            matched = False
            for canonical_field, patterns in self.column_patterns.items():
                if canonical_field in canonical_to_raw:
                    continue  # Already have this canonical field

                for pattern in patterns:
                    if re.match(pattern, col):
                        raw_to_canonical[col] = canonical_field
                        canonical_to_raw[canonical_field] = col
                        matched = True
                        break
                if matched:
                    break

            if not matched:
                unmapped_columns.append(col)

        # Calculate confidence based on required fields
        required_fields = ["case_number", "judgment_amount", "defendant_name"]
        optional_fields = ["plaintiff_name", "filing_date", "judgment_date", "county", "court"]

        required_found = sum(1 for f in required_fields if f in canonical_to_raw)
        optional_found = sum(1 for f in optional_fields if f in canonical_to_raw)

        # Confidence formula: 60% weight on required, 40% on optional
        required_score = (required_found / len(required_fields)) * 60
        optional_score = (optional_found / len(optional_fields)) * 40
        confidence = required_score + optional_score

        # Track missing required fields
        required_missing = [f for f in required_fields if f not in canonical_to_raw]

        return ColumnMapping(
            raw_to_canonical=raw_to_canonical,
            canonical_to_raw=canonical_to_raw,
            unmapped_columns=unmapped_columns,
            confidence=round(confidence, 1),
            required_missing=required_missing,
        )

    def transform_row(
        self,
        row: pd.Series,
        mapping: ColumnMapping,
    ) -> MappedRow:
        """
        Transform a single row using the column mapping.

        Args:
            row: pandas Series representing a single row
            mapping: ColumnMapping to use for transformation

        Returns:
            MappedRow with canonical fields populated
        """
        errors: list[str] = []
        raw_data = row.to_dict()

        # Extract case_number (required)
        case_number_col = mapping.canonical_to_raw.get("case_number")
        case_number = ""
        if case_number_col:
            val = row.get(case_number_col)
            if pd.notna(val):
                case_number = str(val).strip()
        if not case_number:
            errors.append("Missing or empty case_number")

        # Extract defendant_name
        def_col = mapping.canonical_to_raw.get("defendant_name")
        defendant_name = None
        if def_col:
            val = row.get(def_col)
            if pd.notna(val):
                defendant_name = str(val).strip()[:500]

        # Extract plaintiff_name
        plf_col = mapping.canonical_to_raw.get("plaintiff_name")
        plaintiff_name = None
        if plf_col:
            val = row.get(plf_col)
            if pd.notna(val):
                plaintiff_name = str(val).strip()[:500]

        # Extract judgment_amount (required)
        amt_col = mapping.canonical_to_raw.get("judgment_amount")
        judgment_amount = None
        if amt_col:
            val = row.get(amt_col)
            judgment_amount = self._parse_currency(val)
            if judgment_amount is None:
                errors.append(f"Invalid judgment_amount: {val}")

        # Extract filing_date
        filing_col = mapping.canonical_to_raw.get("filing_date")
        filing_date = None
        if filing_col:
            val = row.get(filing_col)
            filing_date = self._parse_date(val)

        # Extract judgment_date
        jdgmt_col = mapping.canonical_to_raw.get("judgment_date")
        judgment_date = None
        if jdgmt_col:
            val = row.get(jdgmt_col)
            judgment_date = self._parse_date(val)

        # Extract county
        county_col = mapping.canonical_to_raw.get("county")
        county = None
        if county_col:
            val = row.get(county_col)
            if pd.notna(val):
                county = str(val).strip()[:100]

        # Extract court
        court_col = mapping.canonical_to_raw.get("court")
        court = None
        if court_col:
            val = row.get(court_col)
            if pd.notna(val):
                court = str(val).strip()[:200]

        # Extract defendant_address
        addr_col = mapping.canonical_to_raw.get("defendant_address")
        defendant_address = None
        if addr_col:
            val = row.get(addr_col)
            if pd.notna(val):
                defendant_address = str(val).strip()[:500]

        return MappedRow(
            case_number=case_number,
            defendant_name=defendant_name,
            plaintiff_name=plaintiff_name,
            judgment_amount=judgment_amount,
            filing_date=filing_date,
            judgment_date=judgment_date,
            county=county,
            court=court,
            defendant_address=defendant_address,
            raw_data=raw_data,
            errors=errors,
        )

    def transform_dataframe(
        self,
        df: pd.DataFrame,
        mapping: ColumnMapping,
    ) -> list[MappedRow]:
        """
        Transform all rows in a DataFrame.

        Args:
            df: DataFrame with raw FOIL data
            mapping: ColumnMapping to use

        Returns:
            List of MappedRow objects
        """
        results: list[MappedRow] = []
        for _, row in df.iterrows():
            mapped = self.transform_row(row, mapping)
            results.append(mapped)
        return results

    # -------------------------------------------------------------------------
    # Bulk Insert Methods
    # -------------------------------------------------------------------------

    def bulk_insert_raw_rows(
        self,
        conn: psycopg.Connection,
        dataset_id: str,
        df: pd.DataFrame,
    ) -> int:
        """
        Bulk insert raw rows into raw.foil_raw_rows using COPY.

        This is the fastest way to ingest large FOIL datasets.

        Args:
            conn: Database connection
            dataset_id: UUID of the foil_dataset record
            df: DataFrame with raw data

        Returns:
            Number of rows inserted
        """
        if df.empty:
            return 0

        # Prepare data for COPY
        buffer = io.StringIO()

        for idx, row in df.iterrows():
            row_json = json.dumps(row.to_dict(), default=str)
            row_index = int(idx) if isinstance(idx, (int, float)) else 0
            # Tab-separated: dataset_id, row_index, raw_json, validation_status
            line = f"{dataset_id}\t{row_index}\t{row_json}\tpending\n"
            buffer.write(line)

        buffer.seek(0)

        # Use COPY for bulk insert
        with conn.cursor() as cur:
            with cur.copy(
                "COPY raw.foil_raw_rows (dataset_id, row_index, raw_json, validation_status) "
                "FROM STDIN WITH (FORMAT text)"
            ) as copy:
                while data := buffer.read(8192):
                    copy.write(data)

        conn.commit()
        return len(df)

    def bulk_insert_judgments(
        self,
        conn: psycopg.Connection,
        mapped_rows: list[MappedRow],
        batch_id: str,
        source_file: str,
    ) -> tuple[int, int, list[dict[str, Any]]]:
        """
        Bulk insert mapped rows into public.judgments using COPY.

        Uses COPY to a temp table, then INSERT...SELECT with conflict handling.

        Args:
            conn: Database connection
            mapped_rows: List of validated MappedRow objects
            batch_id: Batch ID for source_file reference
            source_file: Source file identifier

        Returns:
            Tuple of (inserted_count, duplicate_count, errors)
        """
        valid_rows = [r for r in mapped_rows if r.is_valid()]
        if not valid_rows:
            return 0, 0, []

        errors: list[dict[str, Any]] = []

        # Create temp table for bulk load
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TEMP TABLE IF NOT EXISTS _foil_staging (
                    case_number TEXT,
                    plaintiff_name TEXT,
                    defendant_name TEXT,
                    judgment_amount NUMERIC,
                    entry_date DATE,
                    county TEXT,
                    court TEXT,
                    source_file TEXT
                ) ON COMMIT DROP
            """
            )

        # Prepare data for COPY
        buffer = io.StringIO()
        for row in valid_rows:
            d = row.to_insert_dict()
            # Tab-separated values, using \N for nulls
            values = [
                d.get("case_number") or "",
                d.get("plaintiff_name") or r"\N",
                d.get("defendant_name") or r"\N",
                str(d.get("judgment_amount", "")) if d.get("judgment_amount") else r"\N",
                d.get("entry_date") or r"\N",
                d.get("county") or r"\N",
                d.get("court") or r"\N",
                source_file,
            ]
            line = "\t".join(values) + "\n"
            buffer.write(line)

        buffer.seek(0)

        # COPY into staging table
        with conn.cursor() as cur:
            with cur.copy("COPY _foil_staging FROM STDIN WITH (FORMAT text, NULL '\\N')") as copy:
                while data := buffer.read(8192):
                    copy.write(data)

        # Insert from staging with conflict handling
        with conn.cursor() as cur:
            # Count existing rows for duplicate detection
            cur.execute(
                """
                SELECT COUNT(*) FROM _foil_staging s
                WHERE EXISTS (
                    SELECT 1 FROM public.judgments j
                    WHERE j.case_number = s.case_number
                )
            """
            )
            result = cur.fetchone()
            duplicate_count = result[0] if result else 0

            # Insert with upsert
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
                    source_file,
                    status,
                    created_at
                )
                SELECT
                    case_number,
                    plaintiff_name,
                    defendant_name,
                    judgment_amount,
                    entry_date,
                    county,
                    court,
                    source_file,
                    'pending',
                    now()
                FROM _foil_staging
                ON CONFLICT (case_number) DO UPDATE SET
                    plaintiff_name = COALESCE(EXCLUDED.plaintiff_name, public.judgments.plaintiff_name),
                    defendant_name = COALESCE(EXCLUDED.defendant_name, public.judgments.defendant_name),
                    judgment_amount = EXCLUDED.judgment_amount,
                    entry_date = COALESCE(EXCLUDED.entry_date, public.judgments.entry_date),
                    county = COALESCE(EXCLUDED.county, public.judgments.county),
                    court = COALESCE(EXCLUDED.court, public.judgments.court),
                    updated_at = now()
            """
            )
            inserted_count = cur.rowcount

        conn.commit()
        return inserted_count, duplicate_count, errors

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _parse_currency(self, value: Any) -> Optional[Decimal]:
        """Parse currency value to Decimal."""
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

    def _parse_date(self, value: Any) -> Optional[datetime]:
        """Parse date value to datetime."""
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None

        if isinstance(value, datetime):
            return value

        s = str(value).strip()
        if not s:
            return None

        # Common date formats in court data
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


# =============================================================================
# FOIL Detection Helper
# =============================================================================

# Known FOIL column patterns (columns that indicate FOIL format)
FOIL_INDICATOR_COLUMNS = [
    r"(?i)^def\.?\s*name$",  # "Def. Name" or "DefName"
    r"(?i)^plf\.?\s*name$",  # "Plf. Name"
    r"(?i)^amt$",  # "Amt" instead of "Amount"
    r"(?i)^jdg(?:mt|ment)?[\s_.-]?date$",  # "Jdgmt Date"
    r"(?i)^date[\s_-]?filed$",  # "Date Filed"
    r"(?i)^index[\s_-]?(?:no|num)?$",  # "Index No"
    r"(?i)^docket[\s_-]?(?:no|num)?$",  # "Docket No"
]


def is_foil_format(df: pd.DataFrame) -> bool:
    """
    Detect if a DataFrame appears to be in FOIL format.

    FOIL format is characterized by:
    - Abbreviated column names (Def., Plf., Amt, etc.)
    - Missing standard Simplicity columns
    - Presence of court-specific identifiers

    Args:
        df: DataFrame to check

    Returns:
        True if the data appears to be FOIL format
    """
    if df.empty:
        return False

    # Check for Simplicity format first (if it's Simplicity, it's not FOIL)
    simplicity_columns = [
        "Case Number",
        "Plaintiff",
        "Defendant",
        "Judgment Amount",
        "Filing Date",
        "County",
    ]
    if all(col in df.columns for col in simplicity_columns):
        return False

    # Count FOIL indicator columns
    foil_matches = 0
    for col in df.columns:
        for pattern in FOIL_INDICATOR_COLUMNS:
            if re.match(pattern, col):
                foil_matches += 1
                break

    # If we match 2+ FOIL patterns, it's likely FOIL
    return foil_matches >= 2


def get_foil_format_info(df: pd.DataFrame) -> dict[str, Any]:
    """
    Get information about a potential FOIL format DataFrame.

    Returns column names, detected format, and mapping suggestions.
    """
    mapper = FoilMapper()
    mapping = mapper.detect_column_mapping(df)

    return {
        "is_foil": is_foil_format(df),
        "column_count": len(df.columns),
        "columns": list(df.columns),
        "detected_mapping": mapping.raw_to_canonical,
        "unmapped_columns": mapping.unmapped_columns,
        "mapping_confidence": mapping.confidence,
        "required_missing": mapping.required_missing,
        "is_valid_mapping": mapping.is_valid,
    }
