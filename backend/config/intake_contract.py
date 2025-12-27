# backend/config/intake_contract.py
"""
Intake System Contract - Single Source of Truth

This module defines the canonical data contract for the Dragonfly intake system.
All intake pipelines (Simplicity, JBI, etc.) MUST validate against this contract.

Usage:
    from backend.config.intake_contract import (
        REQUIRED_COLUMNS,
        IntakeError,
        validate_row,
    )
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

# =============================================================================
# Constants: Required Columns
# =============================================================================

# These are the CANONICAL column names expected in validated rows
# Source adapters (Simplicity, JBI) map vendor columns to these names
REQUIRED_COLUMNS = frozenset(
    {
        "case_number",  # Unique identifier for the judgment
        "defendant_name",  # Name of the defendant
        "judgment_amount",  # Dollar amount of the judgment
    }
)

# Optional columns that should be present but aren't blocking
OPTIONAL_COLUMNS = frozenset(
    {
        "plaintiff_name",  # Name of the plaintiff
        "entry_date",  # Date judgment was entered
        "judgment_date",  # Date of judgment
        "court",  # Court name
        "county",  # County/jurisdiction
    }
)

# All recognized columns
ALL_COLUMNS = REQUIRED_COLUMNS | OPTIONAL_COLUMNS


# =============================================================================
# Error Codes: Intake Error Types
# =============================================================================


class IntakeError(Enum):
    """
    Canonical error codes for intake validation.

    Each error has a code (for programmatic use) and a human-readable description.
    Error codes are prefixed by stage:
        - COL_* : Column-level errors
        - VAL_* : Value validation errors
        - DUP_* : Duplicate detection errors
        - SYS_* : System/processing errors
    """

    # Column errors
    MISSING_COLUMN = ("COL_MISSING", "Required column is missing")
    EMPTY_VALUE = ("COL_EMPTY", "Required field has empty value")

    # Value validation errors
    INVALID_AMOUNT = ("VAL_AMOUNT", "Judgment amount is not a valid number")
    NEGATIVE_AMOUNT = ("VAL_NEG_AMOUNT", "Judgment amount cannot be negative")
    INVALID_DATE = ("VAL_DATE", "Date is not in a valid format")
    FUTURE_DATE = ("VAL_FUTURE_DATE", "Date cannot be in the future")
    INVALID_CASE_NUMBER = ("VAL_CASE_NUM", "Case number format is invalid")

    # Duplicate errors
    DUPLICATE_ROW = ("DUP_ROW", "Duplicate row within same batch")
    DUPLICATE_CASE = ("DUP_CASE", "Case number already exists in system")
    DUPLICATE_BATCH = ("DUP_BATCH", "Batch with same file hash already processed")

    # System errors
    PARSE_ERROR = ("SYS_PARSE", "Failed to parse row data")
    TRANSFORM_ERROR = ("SYS_TRANSFORM", "Failed to transform row")
    UPSERT_ERROR = ("SYS_UPSERT", "Failed to upsert to database")

    def __init__(self, code: str, description: str):
        self._code = code
        self._description = description

    @property
    def code(self) -> str:
        return self._code

    @property
    def description(self) -> str:
        return self._description


# =============================================================================
# Validation Result
# =============================================================================


@dataclass
class ValidationError:
    """A single validation error."""

    error: IntakeError
    field: str | None = None
    value: Any = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.error.code,
            "field": self.field,
            "value": str(self.value) if self.value is not None else None,
            "message": self.message or self.error.description,
        }

    def __str__(self) -> str:
        parts = [self.error.code]
        if self.field:
            parts.append(f"[{self.field}]")
        parts.append(self.message or self.error.description)
        return ": ".join(parts)


# =============================================================================
# Validation Logic
# =============================================================================


def validate_row(row: dict[str, Any]) -> list[ValidationError]:
    """
    Validate a single intake row against the canonical contract.

    Args:
        row: Dictionary with canonical column names as keys

    Returns:
        List of ValidationError objects. Empty list means valid.

    Example:
        >>> errors = validate_row({"case_number": "123", "defendant_name": "John"})
        >>> if errors:
        ...     print(f"Row invalid: {errors}")
    """
    errors: list[ValidationError] = []

    # Check required columns
    for col in REQUIRED_COLUMNS:
        if col not in row:
            errors.append(
                ValidationError(
                    error=IntakeError.MISSING_COLUMN,
                    field=col,
                )
            )
        elif row[col] is None or str(row[col]).strip() == "":
            errors.append(
                ValidationError(
                    error=IntakeError.EMPTY_VALUE,
                    field=col,
                    value=row[col],
                )
            )

    # If missing required columns, skip value validation
    if any(e.error == IntakeError.MISSING_COLUMN for e in errors):
        return errors

    # Validate case_number format
    case_number = str(row.get("case_number", "")).strip()
    if case_number and not _is_valid_case_number(case_number):
        errors.append(
            ValidationError(
                error=IntakeError.INVALID_CASE_NUMBER,
                field="case_number",
                value=case_number,
                message=f"Invalid case number format: {case_number}",
            )
        )

    # Validate judgment_amount
    amount = row.get("judgment_amount")
    if amount is not None and str(amount).strip():
        try:
            parsed_amount = _parse_amount(amount)
            if parsed_amount is not None and parsed_amount < 0:
                errors.append(
                    ValidationError(
                        error=IntakeError.NEGATIVE_AMOUNT,
                        field="judgment_amount",
                        value=amount,
                    )
                )
        except (ValueError, InvalidOperation):
            errors.append(
                ValidationError(
                    error=IntakeError.INVALID_AMOUNT,
                    field="judgment_amount",
                    value=amount,
                )
            )

    # Validate dates (entry_date, judgment_date)
    for date_field in ("entry_date", "judgment_date"):
        date_val = row.get(date_field)
        if date_val is not None and str(date_val).strip():
            try:
                parsed_date = _parse_date(date_val)
                if parsed_date and parsed_date > datetime.now().date():
                    errors.append(
                        ValidationError(
                            error=IntakeError.FUTURE_DATE,
                            field=date_field,
                            value=date_val,
                        )
                    )
            except ValueError:
                errors.append(
                    ValidationError(
                        error=IntakeError.INVALID_DATE,
                        field=date_field,
                        value=date_val,
                    )
                )

    return errors


def _is_valid_case_number(case_number: str) -> bool:
    """
    Validate case number format.

    Accepts common formats:
        - Alphanumeric with dashes/slashes: "2024-CV-001234"
        - Numeric only: "123456"
        - With court prefix: "NYC-2024-001234"
    """
    if not case_number or len(case_number) > 100:
        return False

    # Allow alphanumeric, dashes, slashes, spaces
    pattern = r"^[A-Za-z0-9\-/\s]+$"
    return bool(re.match(pattern, case_number))


def _parse_amount(value: Any) -> Decimal | None:
    """Parse various amount formats to Decimal."""
    if value is None:
        return None

    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))

    # Remove currency symbols and commas
    cleaned = str(value).strip()
    cleaned = cleaned.replace("$", "").replace(",", "").strip()

    if not cleaned:
        return None

    return Decimal(cleaned)


def _parse_date(value: Any) -> datetime | None:
    """Parse various date formats."""
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if hasattr(value, "date"):  # datetime-like
        return value.date()

    date_str = str(value).strip()
    if not date_str:
        return None

    # Try common formats
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Unable to parse date: {date_str}")


# =============================================================================
# Batch Validation
# =============================================================================


def validate_batch_columns(columns: list[str]) -> list[ValidationError]:
    """
    Validate that a CSV/DataFrame has all required columns.

    Args:
        columns: List of column names from the input data

    Returns:
        List of ValidationError for any missing required columns
    """
    errors: list[ValidationError] = []
    normalized = {col.lower().strip() for col in columns}

    for required in REQUIRED_COLUMNS:
        if required.lower() not in normalized:
            errors.append(
                ValidationError(
                    error=IntakeError.MISSING_COLUMN,
                    field=required,
                    message=f"CSV is missing required column: {required}",
                )
            )

    return errors
