"""
NY Judgments Pilot Worker - Normalization Module

Pure, deterministic functions for record canonicalization.
No side effects, no I/O, no randomness.

CRITICAL INVARIANTS:
    - All functions are pure and deterministic
    - Same input ALWAYS produces same output
    - No use of now(), random(), or external state
    - Hash inputs are sorted for stability
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any

# ============================================================================
# Constants
# ============================================================================

# Separator for composite key fields (must not appear in data)
FIELD_SEPARATOR = "|"

# Default source system for NY pilot
DEFAULT_SOURCE_SYSTEM = "ny_ecourts"


# ============================================================================
# String Normalization
# ============================================================================


def normalize_string(value: str | None) -> str:
    """
    Normalize a string value for consistent hashing.

    Transformations:
        - Strip leading/trailing whitespace
        - Collapse internal whitespace to single spaces
        - Convert to lowercase
        - Replace None with empty string

    Args:
        value: Input string (may be None).

    Returns:
        Normalized string.
    """
    if value is None:
        return ""

    # Strip and collapse whitespace
    normalized = re.sub(r"\s+", " ", str(value).strip())

    # Lowercase for case-insensitive matching
    return normalized.lower()


def normalize_county(county: str | None) -> str:
    """
    Normalize county name to canonical form.

    Examples:
        - "Kings County" -> "kings"
        - "KINGS" -> "kings"
        - "  kings  " -> "kings"
        - "New York" -> "new_york"

    Args:
        county: Raw county name.

    Returns:
        Normalized county identifier.
    """
    if not county:
        return ""

    # Normalize
    normalized = normalize_string(county)

    # Remove "county" suffix
    normalized = re.sub(r"\s*county\s*$", "", normalized)

    # Replace spaces with underscores
    normalized = normalized.replace(" ", "_")

    return normalized


def normalize_amount(amount: str | float | int | None) -> float | None:
    """
    Normalize monetary amount to float.

    Handles:
        - Currency symbols ($)
        - Thousands separators (,)
        - Whitespace
        - String representations

    Args:
        amount: Raw amount value.

    Returns:
        Float amount or None if invalid/missing.
    """
    if amount is None:
        return None

    if isinstance(amount, (int, float)):
        return float(amount)

    # String cleaning
    cleaned = str(amount).strip()

    # Remove currency symbols and thousands separators
    cleaned = re.sub(r"[$,\s]", "", cleaned)

    if not cleaned:
        return None

    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_date(date_value: str | date | None) -> str | None:
    """
    Normalize date to ISO format (YYYY-MM-DD).

    Args:
        date_value: Raw date (string or date object).

    Returns:
        ISO date string or None if invalid.
    """
    if date_value is None:
        return None

    if isinstance(date_value, date):
        return date_value.isoformat()

    # Try common formats
    cleaned = str(date_value).strip()

    if not cleaned:
        return None

    # Already ISO format
    if re.match(r"^\d{4}-\d{2}-\d{2}$", cleaned):
        return cleaned

    # MM/DD/YYYY
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", cleaned)
    if match:
        month, day, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    # MM-DD-YYYY
    match = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})$", cleaned)
    if match:
        month, day, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    return None


# ============================================================================
# Hash Functions
# ============================================================================


def compute_sha256(data: str) -> str:
    """
    Compute SHA-256 hash of a string.

    Args:
        data: Input string.

    Returns:
        Lowercase hex digest (64 characters).
    """
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def compute_dedupe_key(
    source_system: str,
    source_county: str | None,
    external_id: str | None,
    source_url: str,
) -> str:
    """
    Compute deterministic deduplication key for a judgment record.

    Formula:
        sha256(source_system | source_county | external_id | source_url)

    If external_id is None, uses source_url as the identifier.
    All components are normalized before hashing.

    CRITICAL: This function must be pure and deterministic.
    Same inputs must ALWAYS produce the same output.

    Args:
        source_system: Source system identifier (e.g., 'ny_ecourts').
        source_county: County identifier (may be None).
        external_id: External record ID (may be None).
        source_url: URL where record was retrieved.

    Returns:
        64-character lowercase hex SHA-256 hash.
    """
    # Normalize all inputs
    norm_source = normalize_string(source_system) or DEFAULT_SOURCE_SYSTEM
    norm_county = normalize_county(source_county)
    norm_id = normalize_string(external_id) or ""
    norm_url = normalize_string(source_url)

    # If no external ID, use URL as the identifier
    effective_id = norm_id if norm_id else norm_url

    # Build composite key with separator
    composite = FIELD_SEPARATOR.join(
        [
            norm_source,
            norm_county,
            effective_id,
            norm_url,
        ]
    )

    return compute_sha256(composite)


def compute_content_hash(raw_payload: dict[str, Any]) -> str:
    """
    Compute content hash for change detection.

    Uses sorted JSON serialization for deterministic output.

    Args:
        raw_payload: Raw record data as dictionary.

    Returns:
        64-character lowercase hex SHA-256 hash.
    """
    import json

    # Sort keys for deterministic serialization
    serialized = json.dumps(
        raw_payload,
        sort_keys=True,
        ensure_ascii=True,
        default=str,  # Handle dates, UUIDs, etc.
    )

    return compute_sha256(serialized)


# ============================================================================
# Record Normalization
# ============================================================================


class NormalizedRecord:
    """
    Immutable normalized judgment record ready for database insertion.

    All fields are validated and normalized.
    dedupe_key and content_hash are pre-computed.
    """

    __slots__ = (
        "source_system",
        "source_county",
        "source_court",
        "case_type",
        "external_id",
        "source_url",
        "judgment_entered_at",
        "filed_at",
        "raw_payload",
        "raw_text",
        "raw_html",
        "content_hash",
        "dedupe_key",
    )

    def __init__(
        self,
        source_system: str,
        source_county: str | None,
        source_court: str | None,
        case_type: str | None,
        external_id: str | None,
        source_url: str,
        judgment_entered_at: str | None,
        filed_at: str | None,
        raw_payload: dict[str, Any],
        raw_text: str | None = None,
        raw_html: str | None = None,
    ) -> None:
        # Store normalized values
        self.source_system = source_system
        self.source_county = source_county
        self.source_court = source_court
        self.case_type = case_type
        self.external_id = external_id
        self.source_url = source_url
        self.judgment_entered_at = judgment_entered_at
        self.filed_at = filed_at
        self.raw_payload = raw_payload
        self.raw_text = raw_text
        self.raw_html = raw_html

        # Pre-compute hashes
        self.content_hash = compute_content_hash(raw_payload)
        self.dedupe_key = compute_dedupe_key(
            source_system=source_system,
            source_county=source_county,
            external_id=external_id,
            source_url=source_url,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "source_system": self.source_system,
            "source_county": self.source_county,
            "source_court": self.source_court,
            "case_type": self.case_type,
            "external_id": self.external_id,
            "source_url": self.source_url,
            "judgment_entered_at": self.judgment_entered_at,
            "filed_at": self.filed_at,
            "raw_payload": self.raw_payload,
            "raw_text": self.raw_text,
            "raw_html": self.raw_html,
            "content_hash": self.content_hash,
            "dedupe_key": self.dedupe_key,
        }


def normalize_record(
    raw: dict[str, Any],
    source_system: str = DEFAULT_SOURCE_SYSTEM,
    source_county: str | None = None,
) -> NormalizedRecord:
    """
    Normalize a raw judgment record from the scraper.

    This function is pure and deterministic.

    Args:
        raw: Raw record dictionary from scraper.
        source_system: Source system identifier.
        source_county: County identifier (override).

    Returns:
        NormalizedRecord ready for database insertion.

    Raises:
        ValueError: If required fields are missing.
    """
    # Extract and validate source_url (required)
    source_url = raw.get("source_url") or raw.get("url")
    if not source_url:
        raise ValueError("Record missing required field: source_url")

    # Extract other fields with normalization
    return NormalizedRecord(
        source_system=normalize_string(source_system) or DEFAULT_SOURCE_SYSTEM,
        source_county=normalize_county(
            raw.get("source_county") or raw.get("county") or source_county
        ),
        source_court=normalize_string(raw.get("source_court") or raw.get("court")) or None,
        case_type=normalize_string(raw.get("case_type") or raw.get("type")) or None,
        external_id=normalize_string(
            raw.get("external_id") or raw.get("index_number") or raw.get("case_number")
        )
        or None,
        source_url=normalize_string(source_url),
        judgment_entered_at=normalize_date(
            raw.get("judgment_entered_at") or raw.get("judgment_date")
        ),
        filed_at=normalize_date(raw.get("filed_at") or raw.get("filing_date")),
        raw_payload=raw,
        raw_text=raw.get("raw_text"),
        raw_html=raw.get("raw_html"),
    )


def normalize_batch(
    records: list[dict[str, Any]],
    source_system: str = DEFAULT_SOURCE_SYSTEM,
    source_county: str | None = None,
) -> tuple[list[NormalizedRecord], list[tuple[int, str]]]:
    """
    Normalize a batch of records, collecting errors.

    Args:
        records: List of raw records.
        source_system: Source system identifier.
        source_county: County identifier.

    Returns:
        Tuple of (normalized_records, errors).
        Errors are tuples of (index, error_message).
    """
    normalized: list[NormalizedRecord] = []
    errors: list[tuple[int, str]] = []

    for i, raw in enumerate(records):
        try:
            record = normalize_record(
                raw=raw,
                source_system=source_system,
                source_county=source_county,
            )
            normalized.append(record)
        except Exception as e:
            errors.append((i, str(e)))

    return normalized, errors
