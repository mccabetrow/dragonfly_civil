"""
Unit tests for the FOIL Mapper service.

Tests column auto-detection, data transformation, and bulk insert functionality
for FOIL court data imports.
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pandas as pd
import pytest

from backend.services.foil_mapper import (
    ColumnMapping,
    FoilMapper,
    MappedRow,
    get_foil_format_info,
    is_foil_format,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def simplicity_df() -> pd.DataFrame:
    """Create a DataFrame with Simplicity-format columns."""
    return pd.DataFrame(
        {
            "Case Number": ["2021-CV-001", "2021-CV-002"],
            "Plaintiff": ["ACME Corp", "Best LLC"],
            "Defendant": ["John Doe", "Jane Smith"],
            "Judgment Amount": ["$10,000.00", "$25,500.50"],
            "Filing Date": ["01/15/2021", "03/22/2021"],
            "County": ["Kings", "Queens"],
        }
    )


@pytest.fixture
def foil_df() -> pd.DataFrame:
    """Create a DataFrame with FOIL-format columns (messy abbreviations)."""
    return pd.DataFrame(
        {
            "Index No": ["2021-001", "2021-002", "2021-003"],
            "Def. Name": ["John Doe", "Jane Smith", "Bob Wilson"],
            "Plf. Name": ["ACME Corp", "Best LLC", "Top Inc"],
            "Amt": ["$10,000.00", "25500.50", "(5,000.00)"],
            "Date Filed": ["01/15/2021", "2021-03-22", "15-Jan-2021"],
            "Jdgmt Date": ["02/01/2021", "2021-04-15", ""],
            "County": ["Kings", "Queens", "Bronx"],
        }
    )


@pytest.fixture
def foil_missing_required_df() -> pd.DataFrame:
    """Create a FOIL DataFrame missing required fields."""
    return pd.DataFrame(
        {
            "Random Col": ["A", "B"],
            "Another Col": ["X", "Y"],
        }
    )


@pytest.fixture
def mapper() -> FoilMapper:
    """Create a FoilMapper instance."""
    return FoilMapper()


# =============================================================================
# Test Format Detection
# =============================================================================


class TestFormatDetection:
    """Test FOIL vs Simplicity format detection."""

    def test_detects_simplicity_format(self, simplicity_df: pd.DataFrame) -> None:
        """Should correctly identify Simplicity format."""
        assert not is_foil_format(simplicity_df)

    def test_detects_foil_format(self, foil_df: pd.DataFrame) -> None:
        """Should correctly identify FOIL format."""
        assert is_foil_format(foil_df)

    def test_empty_dataframe_not_foil(self) -> None:
        """Empty DataFrame should not be detected as FOIL."""
        df = pd.DataFrame()
        assert not is_foil_format(df)

    def test_mixed_format_detected_as_foil(self) -> None:
        """DataFrame with FOIL indicators should be detected."""
        df = pd.DataFrame(
            {
                "Def. Name": ["Test"],
                "Amt": ["100"],
                "Some Other Col": ["X"],
            }
        )
        assert is_foil_format(df)

    def test_single_foil_indicator_not_enough(self) -> None:
        """Single FOIL indicator should not trigger detection."""
        df = pd.DataFrame(
            {
                "Def. Name": ["Test"],
                "Regular Column": ["X"],
            }
        )
        # Only 1 FOIL indicator, need 2+
        assert not is_foil_format(df)


class TestFoilFormatInfo:
    """Test get_foil_format_info helper."""

    def test_returns_correct_info_for_foil(self, foil_df: pd.DataFrame) -> None:
        """Should return complete FOIL format info."""
        info = get_foil_format_info(foil_df)

        assert info["is_foil"] is True
        assert info["column_count"] == 7
        assert "Index No" in info["columns"]
        assert info["mapping_confidence"] > 50  # Should have decent confidence
        assert info["is_valid_mapping"] is True  # Has required fields

    def test_returns_info_for_simplicity(self, simplicity_df: pd.DataFrame) -> None:
        """Should correctly report Simplicity as non-FOIL."""
        info = get_foil_format_info(simplicity_df)

        assert info["is_foil"] is False


# =============================================================================
# Test Column Mapping Detection
# =============================================================================


class TestColumnMappingDetection:
    """Test automatic column mapping detection."""

    def test_detects_standard_foil_columns(self, mapper: FoilMapper, foil_df: pd.DataFrame) -> None:
        """Should detect standard FOIL column mappings."""
        mapping = mapper.detect_column_mapping(foil_df)

        # Check canonical fields are mapped
        assert "case_number" in mapping.canonical_to_raw
        assert "defendant_name" in mapping.canonical_to_raw
        assert "plaintiff_name" in mapping.canonical_to_raw
        assert "judgment_amount" in mapping.canonical_to_raw
        assert "filing_date" in mapping.canonical_to_raw

        # Check raw->canonical mappings
        assert mapping.raw_to_canonical.get("Index No") == "case_number"
        assert mapping.raw_to_canonical.get("Def. Name") == "defendant_name"
        assert mapping.raw_to_canonical.get("Amt") == "judgment_amount"

    def test_confidence_scoring(self, mapper: FoilMapper, foil_df: pd.DataFrame) -> None:
        """Should calculate reasonable confidence score."""
        mapping = mapper.detect_column_mapping(foil_df)

        # With all required + some optional, should have high confidence
        assert mapping.confidence >= 60
        assert mapping.confidence <= 100

    def test_identifies_unmapped_columns(self, mapper: FoilMapper, foil_df: pd.DataFrame) -> None:
        """Should track unmapped columns."""
        mapping = mapper.detect_column_mapping(foil_df)

        # Jdgmt Date might not match patterns exactly, may be unmapped
        # County should be mapped
        assert "County" not in mapping.unmapped_columns or len(mapping.unmapped_columns) == 0

    def test_missing_required_fields(
        self, mapper: FoilMapper, foil_missing_required_df: pd.DataFrame
    ) -> None:
        """Should report missing required fields."""
        mapping = mapper.detect_column_mapping(foil_missing_required_df)

        assert not mapping.is_valid
        assert "case_number" in mapping.required_missing
        assert "judgment_amount" in mapping.required_missing

    def test_explicit_mapping_override(self) -> None:
        """Explicit mappings should override pattern matching."""
        explicit = {"Custom Col": "case_number"}
        mapper = FoilMapper(explicit_mapping=explicit)

        df = pd.DataFrame(
            {
                "Custom Col": ["123"],
                "Amt": ["100"],
            }
        )

        mapping = mapper.detect_column_mapping(df)
        assert mapping.raw_to_canonical.get("Custom Col") == "case_number"


# =============================================================================
# Test Row Transformation
# =============================================================================


class TestRowTransformation:
    """Test single row transformation."""

    def test_transforms_valid_row(self, mapper: FoilMapper, foil_df: pd.DataFrame) -> None:
        """Should transform valid FOIL row correctly."""
        mapping = mapper.detect_column_mapping(foil_df)
        row = foil_df.iloc[0]

        result = mapper.transform_row(row, mapping)

        assert result.case_number == "2021-001"
        assert result.defendant_name == "John Doe"
        assert result.plaintiff_name == "ACME Corp"
        assert result.judgment_amount == Decimal("10000.00")
        assert result.is_valid()
        assert len(result.errors) == 0

    def test_handles_currency_formats(self, mapper: FoilMapper, foil_df: pd.DataFrame) -> None:
        """Should handle various currency formats."""
        mapping = mapper.detect_column_mapping(foil_df)

        # Row with $-format
        row1 = mapper.transform_row(foil_df.iloc[0], mapping)
        assert row1.judgment_amount == Decimal("10000.00")

        # Row with no $ sign
        row2 = mapper.transform_row(foil_df.iloc[1], mapping)
        assert row2.judgment_amount == Decimal("25500.50")

        # Row with negative (parentheses)
        row3 = mapper.transform_row(foil_df.iloc[2], mapping)
        assert row3.judgment_amount == Decimal("-5000.00")

    def test_handles_date_formats(self, mapper: FoilMapper, foil_df: pd.DataFrame) -> None:
        """Should handle various date formats."""
        mapping = mapper.detect_column_mapping(foil_df)

        # MM/DD/YYYY format
        row1 = mapper.transform_row(foil_df.iloc[0], mapping)
        assert row1.filing_date == datetime(2021, 1, 15)

        # YYYY-MM-DD format
        row2 = mapper.transform_row(foil_df.iloc[1], mapping)
        assert row2.filing_date == datetime(2021, 3, 22)

    def test_handles_empty_values(self, mapper: FoilMapper) -> None:
        """Should handle empty/null values gracefully."""
        df = pd.DataFrame(
            {
                "Case Number": ["123"],
                "Amt": ["100"],
                "Def. Name": [""],
                "Filing Date": [None],
            }
        )

        mapping = mapper.detect_column_mapping(df)
        row = mapper.transform_row(df.iloc[0], mapping)

        # Should still be valid (has case_number and amount)
        assert row.case_number == "123"
        assert row.defendant_name == ""  # Empty string preserved
        assert row.filing_date is None

    def test_collects_validation_errors(self, mapper: FoilMapper) -> None:
        """Should collect errors for invalid rows."""
        df = pd.DataFrame(
            {
                "Case Number": [""],  # Empty case number
                "Amt": ["invalid"],  # Invalid amount
            }
        )

        mapping = mapper.detect_column_mapping(df)
        row = mapper.transform_row(df.iloc[0], mapping)

        assert not row.is_valid()
        assert len(row.errors) > 0
        assert any("case_number" in e.lower() for e in row.errors)


class TestDataFrameTransformation:
    """Test batch DataFrame transformation."""

    def test_transforms_all_rows(self, mapper: FoilMapper, foil_df: pd.DataFrame) -> None:
        """Should transform all rows in DataFrame."""
        mapping = mapper.detect_column_mapping(foil_df)
        results = mapper.transform_dataframe(foil_df, mapping)

        assert len(results) == 3
        assert all(isinstance(r, MappedRow) for r in results)

    def test_separates_valid_invalid(self, mapper: FoilMapper, foil_df: pd.DataFrame) -> None:
        """Should correctly identify valid/invalid rows."""
        mapping = mapper.detect_column_mapping(foil_df)
        results = mapper.transform_dataframe(foil_df, mapping)

        valid = [r for r in results if r.is_valid()]
        invalid = [r for r in results if not r.is_valid()]

        # All our test data should be valid
        assert len(valid) == 3
        assert len(invalid) == 0


# =============================================================================
# Test Currency Parsing
# =============================================================================


class TestCurrencyParsing:
    """Test currency value parsing edge cases."""

    def test_parse_standard_currency(self, mapper: FoilMapper) -> None:
        """Standard currency formats."""
        assert mapper._parse_currency("$1,234.56") == Decimal("1234.56")
        assert mapper._parse_currency("1234.56") == Decimal("1234.56")
        assert mapper._parse_currency("$0.00") == Decimal("0.00")

    def test_parse_negative_currency(self, mapper: FoilMapper) -> None:
        """Negative currency formats."""
        assert mapper._parse_currency("($1,000.00)") == Decimal("-1000.00")
        assert mapper._parse_currency("-$500") == Decimal("-500")

    def test_parse_none_and_empty(self, mapper: FoilMapper) -> None:
        """None and empty values."""
        assert mapper._parse_currency(None) is None
        assert mapper._parse_currency("") is None
        assert mapper._parse_currency("   ") is None

    def test_parse_numeric_types(self, mapper: FoilMapper) -> None:
        """Numeric input types."""
        assert mapper._parse_currency(100) == Decimal("100")
        assert mapper._parse_currency(100.50) == Decimal("100.50")
        assert mapper._parse_currency(Decimal("100")) == Decimal("100")

    def test_parse_invalid_currency(self, mapper: FoilMapper) -> None:
        """Invalid currency strings."""
        assert mapper._parse_currency("not a number") is None
        assert mapper._parse_currency("$abc") is None


# =============================================================================
# Test Date Parsing
# =============================================================================


class TestDateParsing:
    """Test date value parsing edge cases."""

    def test_parse_mm_dd_yyyy(self, mapper: FoilMapper) -> None:
        """MM/DD/YYYY format."""
        assert mapper._parse_date("01/15/2021") == datetime(2021, 1, 15)
        assert mapper._parse_date("12/31/2020") == datetime(2020, 12, 31)

    def test_parse_yyyy_mm_dd(self, mapper: FoilMapper) -> None:
        """YYYY-MM-DD format."""
        assert mapper._parse_date("2021-01-15") == datetime(2021, 1, 15)

    def test_parse_dd_mon_yyyy(self, mapper: FoilMapper) -> None:
        """DD-Mon-YYYY format."""
        assert mapper._parse_date("15-Jan-2021") == datetime(2021, 1, 15)

    def test_parse_none_and_empty(self, mapper: FoilMapper) -> None:
        """None and empty values."""
        assert mapper._parse_date(None) is None
        assert mapper._parse_date("") is None

    def test_parse_invalid_date(self, mapper: FoilMapper) -> None:
        """Invalid date strings."""
        assert mapper._parse_date("not a date") is None
        assert mapper._parse_date("13/45/2021") is None


# =============================================================================
# Test ColumnMapping Dataclass
# =============================================================================


class TestColumnMappingDataclass:
    """Test ColumnMapping validation."""

    def test_is_valid_with_required_fields(self) -> None:
        """Should be valid with all required fields."""
        mapping = ColumnMapping(
            raw_to_canonical={"Col1": "case_number", "Col2": "judgment_amount"},
            canonical_to_raw={"case_number": "Col1", "judgment_amount": "Col2"},
            unmapped_columns=[],
            confidence=60.0,
            required_missing=[],
        )
        assert mapping.is_valid

    def test_is_invalid_missing_case_number(self) -> None:
        """Should be invalid without case_number."""
        mapping = ColumnMapping(
            raw_to_canonical={"Col2": "judgment_amount"},
            canonical_to_raw={"judgment_amount": "Col2"},
            unmapped_columns=[],
            confidence=30.0,
            required_missing=["case_number"],
        )
        assert not mapping.is_valid

    def test_is_invalid_missing_judgment_amount(self) -> None:
        """Should be invalid without judgment_amount."""
        mapping = ColumnMapping(
            raw_to_canonical={"Col1": "case_number"},
            canonical_to_raw={"case_number": "Col1"},
            unmapped_columns=[],
            confidence=30.0,
            required_missing=["judgment_amount"],
        )
        assert not mapping.is_valid


# =============================================================================
# Test MappedRow Dataclass
# =============================================================================


class TestMappedRowDataclass:
    """Test MappedRow conversion."""

    def test_to_insert_dict(self) -> None:
        """Should convert to database insert dict."""
        row = MappedRow(
            case_number="2021-001",
            defendant_name="John Doe",
            plaintiff_name="ACME Corp",
            judgment_amount=Decimal("10000.00"),
            filing_date=datetime(2021, 1, 15),
            judgment_date=datetime(2021, 2, 1),
            county="Kings",
            court="Civil Court",
        )

        d = row.to_insert_dict()

        assert d["case_number"] == "2021-001"
        assert d["defendant_name"] == "John Doe"
        assert d["plaintiff_name"] == "ACME Corp"
        assert d["judgment_amount"] == Decimal("10000.00")
        assert d["filing_date"] == "2021-01-15"
        assert d["entry_date"] == "2021-02-01"  # judgment_date -> entry_date
        assert d["county"] == "Kings"
        assert d["court"] == "Civil Court"

    def test_is_valid_checks_required(self) -> None:
        """Should validate required fields."""
        valid_row = MappedRow(
            case_number="123",
            judgment_amount=Decimal("100"),
        )
        assert valid_row.is_valid()

        missing_case = MappedRow(
            case_number="",
            judgment_amount=Decimal("100"),
        )
        assert not missing_case.is_valid()

        missing_amount = MappedRow(
            case_number="123",
            judgment_amount=None,
        )
        assert not missing_amount.is_valid()


# =============================================================================
# Test Ingest Processor FOIL Detection
# =============================================================================


class TestIngestProcessorFoilDetection:
    """Test FOIL format detection in ingest processor."""

    def test_is_foil_format_import(self) -> None:
        """Should be able to import _is_foil_format from ingest_processor."""
        from backend.workers.ingest_processor import _is_foil_format

        # FOIL format DataFrame
        foil_df = pd.DataFrame(
            {
                "Def. Name": ["Test"],
                "Amt": ["100"],
            }
        )
        assert _is_foil_format(foil_df)

        # Simplicity format
        simplicity_df = pd.DataFrame(
            {
                "Case Number": ["123"],
                "Plaintiff": ["Test"],
                "Defendant": ["Test"],
                "Judgment Amount": ["100"],
                "Filing Date": ["01/01/2021"],
                "County": ["Test"],
            }
        )
        assert not _is_foil_format(simplicity_df)
