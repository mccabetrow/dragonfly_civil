"""
Intake Mapping Configuration

Provides config-driven CSV column mappings so we can quickly adapt
to different vendor export formats (Simplicity, JBI, etc.).

Each mapping dict maps a canonical field name to a list of possible
column header variations that may appear in vendor CSVs.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import date, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Simplicity Export Mapping
# ---------------------------------------------------------------------------
# Maps canonical field names to possible CSV column headers.
# The first match wins when normalizing a row.

SIMPLICITY_MAPPING: dict[str, list[str]] = {
    "case_number": ["CaseNo", "Case #", "Index Number", "case_number", "CaseNumber"],
    "plaintiff_name": [
        "Plaintiff",
        "PlaintiffName",
        "plaintiff_name",
        "Plaintiff Name",
    ],
    "defendant_name": [
        "Defendant",
        "DefendantName",
        "defendant_name",
        "Defendant Name",
    ],
    "judgment_amount": [
        "JudgmentAmount",
        "Amount",
        "judgment_amount",
        "Judgment Amount",
    ],
    "judgment_date": ["JudgmentDate", "Date", "judgment_date", "Judgment Date"],
    "court": ["Court", "court", "CourtName"],
    "county": ["County", "county", "CountyName"],
}

# Required fields that must be present in every row
REQUIRED_FIELDS: set[str] = {"case_number", "plaintiff_name", "defendant_name"}


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _find_column_value(
    raw_row: dict[str, str],
    canonical_name: str,
    possible_headers: list[str],
) -> str | None:
    """
    Find the value for a canonical field by checking all possible header variations.

    Args:
        raw_row: The raw CSV row dict (header -> value)
        canonical_name: The canonical field name we're looking for
        possible_headers: List of possible column headers to check

    Returns:
        The value if found, None otherwise
    """
    for header in possible_headers:
        if header in raw_row:
            return raw_row[header]
    return None


def _parse_amount(value: str | None) -> Decimal | None:
    """
    Parse a monetary amount string to Decimal.

    Handles common formats like:
    - "1234.56"
    - "$1,234.56"
    - "1,234"

    Returns None if value is empty or unparseable.
    """
    if not value or not value.strip():
        return None

    # Clean the value: remove $, commas, whitespace
    cleaned = value.strip().replace("$", "").replace(",", "")

    if not cleaned:
        return None

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_date(value: str | None) -> date | None:
    """
    Parse a date string to date object.

    Handles common formats:
    - "2024-01-15" (ISO)
    - "01/15/2024" (US)
    - "1/15/2024" (US short)

    Returns None if value is empty or unparseable.
    """
    if not value or not value.strip():
        return None

    cleaned = value.strip()

    # Try ISO format first (YYYY-MM-DD)
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d").date()
    except ValueError:
        pass

    # Try US format (MM/DD/YYYY)
    try:
        return datetime.strptime(cleaned, "%m/%d/%Y").date()
    except ValueError:
        pass

    # Try short US format (M/D/YYYY)
    try:
        return datetime.strptime(cleaned, "%m/%d/%y").date()
    except ValueError:
        pass

    return None


def normalize_row(
    raw_row: dict[str, str],
    mapping: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """
    Given a raw CSV row, return a normalized dict with canonical keys.

    Args:
        raw_row: Raw CSV row dict with header -> value
        mapping: Column mapping dict. Defaults to SIMPLICITY_MAPPING.

    Returns:
        Normalized dict with keys:
        - case_number: str
        - plaintiff_name: str
        - defendant_name: str
        - judgment_amount: Decimal | None
        - judgment_date: date | None
        - court: str | None
        - county: str | None

    Raises:
        ValueError: If required fields (case_number, plaintiff_name, defendant_name)
                   are missing or empty.
    """
    if mapping is None:
        mapping = SIMPLICITY_MAPPING

    result: dict[str, Any] = {}

    # Extract all fields using the mapping
    for canonical_name, possible_headers in mapping.items():
        raw_value = _find_column_value(raw_row, canonical_name, possible_headers)

        # Apply type-specific parsing
        if canonical_name == "judgment_amount":
            result[canonical_name] = _parse_amount(raw_value)
        elif canonical_name == "judgment_date":
            result[canonical_name] = _parse_date(raw_value)
        else:
            # String fields: strip whitespace, convert empty to None
            result[canonical_name] = raw_value.strip() if raw_value else None

    # Validate required fields
    missing_fields = []
    for field in REQUIRED_FIELDS:
        if not result.get(field):
            missing_fields.append(field)

    if missing_fields:
        raise ValueError(
            f"Missing required fields: {', '.join(sorted(missing_fields))}"
        )

    return result


def get_mapping_for_source(source: str) -> dict[str, list[str]]:
    """
    Get the column mapping for a given source system.

    Args:
        source: Source identifier (e.g., "simplicity", "jbi")

    Returns:
        Column mapping dict for that source.

    Raises:
        ValueError: If source is not recognized.
    """
    mappings = {
        "simplicity": SIMPLICITY_MAPPING,
        # Future: Add JBI_MAPPING, etc.
    }

    if source not in mappings:
        raise ValueError(
            f"Unknown source: {source}. Known sources: {list(mappings.keys())}"
        )

    return mappings[source]
