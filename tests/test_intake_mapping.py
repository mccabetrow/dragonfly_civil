"""
Tests for the config-driven intake mapping.

Verifies:
- Different header variations map correctly
- Missing required fields raise ValueError
- Type parsing (amounts, dates) works correctly
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from backend.services.intake_mapping import (
    REQUIRED_FIELDS,
    SIMPLICITY_MAPPING,
    get_mapping_for_source,
    normalize_row,
)


class TestSimplicityMappingConfig:
    """Test the SIMPLICITY_MAPPING configuration."""

    def test_mapping_has_required_fields(self) -> None:
        """All required fields should be defined in the mapping."""
        for field in REQUIRED_FIELDS:
            assert field in SIMPLICITY_MAPPING, f"Missing required field: {field}"

    def test_mapping_has_all_canonical_fields(self) -> None:
        """Mapping should include all expected canonical fields."""
        expected_fields = {
            "case_number",
            "plaintiff_name",
            "defendant_name",
            "judgment_amount",
            "judgment_date",
            "court",
            "county",
        }
        assert set(SIMPLICITY_MAPPING.keys()) == expected_fields


class TestNormalizeRowHeaderVariations:
    """Test that different CSV header variations map correctly."""

    def test_standard_headers(self) -> None:
        """Standard Simplicity headers should map correctly."""
        raw_row = {
            "CaseNo": "2024-001",
            "Plaintiff": "Acme Corp",
            "Defendant": "John Doe",
            "JudgmentAmount": "5000.00",
            "JudgmentDate": "2024-01-15",
            "Court": "Supreme Court",
            "County": "New York",
        }

        result = normalize_row(raw_row)

        assert result["case_number"] == "2024-001"
        assert result["plaintiff_name"] == "Acme Corp"
        assert result["defendant_name"] == "John Doe"
        assert result["judgment_amount"] == Decimal("5000.00")
        assert result["judgment_date"] == date(2024, 1, 15)
        assert result["court"] == "Supreme Court"
        assert result["county"] == "New York"

    def test_alternate_headers_case_hash(self) -> None:
        """Alternate header format 'Case #' should work."""
        raw_row = {
            "Case #": "2024-002",
            "PlaintiffName": "Widget Inc",
            "DefendantName": "Jane Smith",
            "Amount": "1234.56",
        }

        result = normalize_row(raw_row)

        assert result["case_number"] == "2024-002"
        assert result["plaintiff_name"] == "Widget Inc"
        assert result["defendant_name"] == "Jane Smith"
        assert result["judgment_amount"] == Decimal("1234.56")

    def test_index_number_header(self) -> None:
        """'Index Number' header variation should work."""
        raw_row = {
            "Index Number": "INDEX-123",
            "Plaintiff": "Test Corp",
            "Defendant": "Test Person",
        }

        result = normalize_row(raw_row)

        assert result["case_number"] == "INDEX-123"

    def test_lowercase_headers(self) -> None:
        """Lowercase canonical headers should work."""
        raw_row = {
            "case_number": "LC-001",
            "plaintiff_name": "Lower Case Inc",
            "defendant_name": "Lower Person",
        }

        result = normalize_row(raw_row)

        assert result["case_number"] == "LC-001"
        assert result["plaintiff_name"] == "Lower Case Inc"
        assert result["defendant_name"] == "Lower Person"

    def test_first_match_wins(self) -> None:
        """When multiple matching headers exist, first in list wins."""
        raw_row = {
            "CaseNo": "FIRST",
            "Case #": "SECOND",  # This should be ignored
            "Plaintiff": "Test",
            "Defendant": "Test",
        }

        result = normalize_row(raw_row)

        assert result["case_number"] == "FIRST"


class TestNormalizeRowTypeParsing:
    """Test type parsing for amounts and dates."""

    def test_amount_with_dollar_sign(self) -> None:
        """Amount with $ should be parsed correctly."""
        raw_row = {
            "CaseNo": "AMT-001",
            "Plaintiff": "Test",
            "Defendant": "Test",
            "JudgmentAmount": "$1,234.56",
        }

        result = normalize_row(raw_row)

        assert result["judgment_amount"] == Decimal("1234.56")

    def test_amount_with_commas(self) -> None:
        """Amount with thousands separators should be parsed."""
        raw_row = {
            "CaseNo": "AMT-002",
            "Plaintiff": "Test",
            "Defendant": "Test",
            "JudgmentAmount": "1,000,000",
        }

        result = normalize_row(raw_row)

        assert result["judgment_amount"] == Decimal("1000000")

    def test_amount_empty_returns_none(self) -> None:
        """Empty amount should return None, not raise."""
        raw_row = {
            "CaseNo": "AMT-003",
            "Plaintiff": "Test",
            "Defendant": "Test",
            "JudgmentAmount": "",
        }

        result = normalize_row(raw_row)

        assert result["judgment_amount"] is None

    def test_date_iso_format(self) -> None:
        """ISO date format (YYYY-MM-DD) should parse."""
        raw_row = {
            "CaseNo": "DATE-001",
            "Plaintiff": "Test",
            "Defendant": "Test",
            "JudgmentDate": "2024-03-15",
        }

        result = normalize_row(raw_row)

        assert result["judgment_date"] == date(2024, 3, 15)

    def test_date_us_format(self) -> None:
        """US date format (MM/DD/YYYY) should parse."""
        raw_row = {
            "CaseNo": "DATE-002",
            "Plaintiff": "Test",
            "Defendant": "Test",
            "JudgmentDate": "03/15/2024",
        }

        result = normalize_row(raw_row)

        assert result["judgment_date"] == date(2024, 3, 15)

    def test_date_empty_returns_none(self) -> None:
        """Empty date should return None, not raise."""
        raw_row = {
            "CaseNo": "DATE-003",
            "Plaintiff": "Test",
            "Defendant": "Test",
            "JudgmentDate": "",
        }

        result = normalize_row(raw_row)

        assert result["judgment_date"] is None


class TestNormalizeRowRequiredFields:
    """Test that missing required fields raise ValueError."""

    def test_missing_case_number_raises(self) -> None:
        """Missing case_number should raise ValueError."""
        raw_row = {
            "Plaintiff": "Test Corp",
            "Defendant": "Test Person",
        }

        with pytest.raises(ValueError) as exc_info:
            normalize_row(raw_row)

        assert "case_number" in str(exc_info.value)

    def test_empty_case_number_raises(self) -> None:
        """Empty case_number should raise ValueError."""
        raw_row = {
            "CaseNo": "",
            "Plaintiff": "Test Corp",
            "Defendant": "Test Person",
        }

        with pytest.raises(ValueError) as exc_info:
            normalize_row(raw_row)

        assert "case_number" in str(exc_info.value)

    def test_whitespace_case_number_raises(self) -> None:
        """Whitespace-only case_number should raise ValueError."""
        raw_row = {
            "CaseNo": "   ",
            "Plaintiff": "Test Corp",
            "Defendant": "Test Person",
        }

        with pytest.raises(ValueError) as exc_info:
            normalize_row(raw_row)

        assert "case_number" in str(exc_info.value)

    def test_missing_plaintiff_raises(self) -> None:
        """Missing plaintiff_name should raise ValueError."""
        raw_row = {
            "CaseNo": "2024-001",
            "Defendant": "Test Person",
        }

        with pytest.raises(ValueError) as exc_info:
            normalize_row(raw_row)

        assert "plaintiff_name" in str(exc_info.value)

    def test_missing_defendant_raises(self) -> None:
        """Missing defendant_name should raise ValueError."""
        raw_row = {
            "CaseNo": "2024-001",
            "Plaintiff": "Test Corp",
        }

        with pytest.raises(ValueError) as exc_info:
            normalize_row(raw_row)

        assert "defendant_name" in str(exc_info.value)

    def test_multiple_missing_fields_in_error(self) -> None:
        """Error message should list all missing fields."""
        raw_row = {
            "Court": "Test Court",
            "County": "Test County",
        }

        with pytest.raises(ValueError) as exc_info:
            normalize_row(raw_row)

        error_msg = str(exc_info.value)
        assert "case_number" in error_msg
        assert "plaintiff_name" in error_msg
        assert "defendant_name" in error_msg


class TestGetMappingForSource:
    """Test the get_mapping_for_source helper."""

    def test_simplicity_source(self) -> None:
        """'simplicity' source should return SIMPLICITY_MAPPING."""
        mapping = get_mapping_for_source("simplicity")
        assert mapping == SIMPLICITY_MAPPING

    def test_unknown_source_raises(self) -> None:
        """Unknown source should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_mapping_for_source("unknown_vendor")

        assert "unknown_vendor" in str(exc_info.value)
        assert "simplicity" in str(exc_info.value)  # Lists known sources


class TestNormalizeRowOptionalFields:
    """Test that optional fields work correctly."""

    def test_optional_fields_can_be_missing(self) -> None:
        """Optional fields (court, county, amount, date) can be missing."""
        raw_row = {
            "CaseNo": "2024-001",
            "Plaintiff": "Test Corp",
            "Defendant": "Test Person",
            # No court, county, amount, date
        }

        result = normalize_row(raw_row)

        assert result["case_number"] == "2024-001"
        assert result["plaintiff_name"] == "Test Corp"
        assert result["defendant_name"] == "Test Person"
        assert result["judgment_amount"] is None
        assert result["judgment_date"] is None
        assert result["court"] is None
        assert result["county"] is None

    def test_whitespace_trimmed(self) -> None:
        """Whitespace should be trimmed from string values."""
        raw_row = {
            "CaseNo": "  2024-001  ",
            "Plaintiff": "  Test Corp  ",
            "Defendant": "  Test Person  ",
            "Court": "  Test Court  ",
        }

        result = normalize_row(raw_row)

        assert result["case_number"] == "2024-001"
        assert result["plaintiff_name"] == "Test Corp"
        assert result["defendant_name"] == "Test Person"
        assert result["court"] == "Test Court"
