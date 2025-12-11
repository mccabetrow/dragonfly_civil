#!/usr/bin/env python3
"""
Tests for Simplicity Data Ingestion Pipeline

Tests the SimplicityMapper class and the 3-step intake pipeline:
    1. Stage raw rows to intake.simplicity_raw_rows
    2. Transform/validate to intake.simplicity_validated_rows
    3. Upsert valid rows to public.judgments

Run with:
    pytest tests/test_ingest_simplicity.py -v
"""

from __future__ import annotations

import csv
import tempfile
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Generator

import pandas as pd
import pytest

from backend.services.simplicity_mapper import (
    ColumnMapping,
    MappedRow,
    SimplicityMapper,
    is_simplicity_format,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mapper() -> SimplicityMapper:
    """Create a fresh SimplicityMapper instance."""
    return SimplicityMapper()


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Create a sample DataFrame in Simplicity format."""
    return pd.DataFrame(
        {
            "Case Number": ["CIV-2024-001", "CIV-2024-002", "CIV-2024-003"],
            "Plaintiff": ["John Smith", "Jane Doe", "Acme Corp"],
            "Defendant": ["Bob Jones", "Evil Corp", "John Johnson"],
            "Judgment Amount": ["$1,200.00", "$5,500.50", "750"],
            "Filing Date": ["01/15/2024", "2024-03-22", "12/01/2023"],
            "County": ["Kings", "Queens", "New York"],
        }
    )


@pytest.fixture
def sample_df_with_court() -> pd.DataFrame:
    """Create a sample DataFrame with optional Court column."""
    return pd.DataFrame(
        {
            "Case Number": ["CIV-2024-010"],
            "Plaintiff": ["Test Plaintiff"],
            "Defendant": ["Test Defendant"],
            "Judgment Amount": ["2500.00"],
            "Filing Date": ["05/20/2024"],
            "County": ["Bronx"],
            "Court": ["Bronx Civil Court"],
        }
    )


@pytest.fixture
def sample_df_invalid() -> pd.DataFrame:
    """Create a DataFrame with some invalid rows."""
    return pd.DataFrame(
        {
            "Case Number": ["CIV-2024-100", "", "CIV-2024-102"],
            "Plaintiff": ["Valid Plaintiff", "No Case Number", "Another Plaintiff"],
            "Defendant": ["Valid Defendant", "Test Def", "Another Defendant"],
            "Judgment Amount": ["1000.00", "500", "invalid-amount"],
            "Filing Date": ["01/01/2024", "02/02/2024", "not-a-date"],
            "County": ["Kings", "Queens", "Bronx"],
        }
    )


@pytest.fixture
def temp_csv_file(sample_df: pd.DataFrame) -> Generator[Path, None, None]:
    """Create a temporary CSV file with sample data."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        sample_df.to_csv(f, index=False)
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    temp_path.unlink(missing_ok=True)


# =============================================================================
# SimplicityMapper Unit Tests
# =============================================================================


class TestSimplicityMapper:
    """Unit tests for SimplicityMapper class."""

    def test_detect_column_mapping_standard(
        self, mapper: SimplicityMapper, sample_df: pd.DataFrame
    ) -> None:
        """Test column detection with standard Simplicity headers."""
        mapping = mapper.detect_column_mapping(sample_df)

        assert mapping.is_valid
        assert len(mapping.missing_required) == 0
        assert "Case Number" in mapping.raw_to_canonical
        assert mapping.raw_to_canonical["Case Number"] == "case_number"
        assert mapping.raw_to_canonical["Plaintiff"] == "plaintiff_name"
        assert mapping.raw_to_canonical["Defendant"] == "defendant_name"
        assert mapping.raw_to_canonical["Judgment Amount"] == "judgment_amount"
        assert mapping.confidence > 50.0

    def test_detect_column_mapping_variations(self, mapper: SimplicityMapper) -> None:
        """Test column detection with common variations."""
        df = pd.DataFrame(
            {
                "case_number": ["CIV-001"],
                "plaintiff_name": ["Test Plf"],
                "defendant_name": ["Test Def"],
                "amount_awarded": ["1000"],
            }
        )

        mapping = mapper.detect_column_mapping(df)

        assert mapping.is_valid
        assert mapping.raw_to_canonical["amount_awarded"] == "judgment_amount"

    def test_detect_column_mapping_missing_required(self, mapper: SimplicityMapper) -> None:
        """Test column detection when required fields are missing."""
        df = pd.DataFrame(
            {
                "Case Number": ["CIV-001"],
                "County": ["Kings"],
            }
        )

        mapping = mapper.detect_column_mapping(df)

        assert not mapping.is_valid
        assert "plaintiff_name" in mapping.missing_required
        assert "defendant_name" in mapping.missing_required
        assert "judgment_amount" in mapping.missing_required

    def test_transform_dataframe_valid(
        self, mapper: SimplicityMapper, sample_df: pd.DataFrame
    ) -> None:
        """Test transformation of valid DataFrame."""
        mapping = mapper.detect_column_mapping(sample_df)
        rows = mapper.transform_dataframe(sample_df, mapping)

        assert len(rows) == 3

        # Check first row
        row0 = rows[0]
        assert row0.case_number == "CIV-2024-001"
        assert row0.plaintiff_name == "John Smith"
        assert row0.defendant_name == "Bob Jones"
        assert row0.judgment_amount == Decimal("1200.00")
        assert row0.entry_date == date(2024, 1, 15)
        assert row0.county == "Kings"
        assert row0.is_valid()

    def test_transform_dataframe_invalid_rows(
        self, mapper: SimplicityMapper, sample_df_invalid: pd.DataFrame
    ) -> None:
        """Test transformation handles invalid rows."""
        mapping = mapper.detect_column_mapping(sample_df_invalid)
        rows = mapper.transform_dataframe(sample_df_invalid, mapping)

        assert len(rows) == 3

        # First row should be valid
        assert rows[0].is_valid()

        # Second row has empty case number - should have error
        assert not rows[1].is_valid()
        assert any("case_number" in e.lower() for e in rows[1].errors)

        # Third row has invalid amount - should have error
        assert not rows[2].is_valid()
        assert any("amount" in e.lower() for e in rows[2].errors)


class TestCurrencyParsing:
    """Tests for currency parsing logic."""

    def test_clean_currency_standard(self, mapper: SimplicityMapper) -> None:
        """Test standard currency formats."""
        assert mapper._clean_currency("$1,200.00") == Decimal("1200.00")
        assert mapper._clean_currency("1200.00") == Decimal("1200.00")
        assert mapper._clean_currency("1,200") == Decimal("1200")
        assert mapper._clean_currency("500") == Decimal("500")

    def test_clean_currency_edge_cases(self, mapper: SimplicityMapper) -> None:
        """Test edge cases for currency parsing."""
        assert mapper._clean_currency(None) is None
        assert mapper._clean_currency("") is None
        assert mapper._clean_currency("  ") is None
        assert mapper._clean_currency(1200) == Decimal("1200")
        assert mapper._clean_currency(1200.50) == Decimal("1200.5")

    def test_clean_currency_negative(self, mapper: SimplicityMapper) -> None:
        """Test negative amounts in parentheses."""
        assert mapper._clean_currency("(500.00)") == Decimal("-500.00")
        assert mapper._clean_currency("($1,000)") == Decimal("-1000")

    def test_clean_currency_invalid(self, mapper: SimplicityMapper) -> None:
        """Test invalid currency values raise ValueError."""
        with pytest.raises(ValueError, match="Cannot parse currency"):
            mapper._clean_currency("not-a-number")


class TestDateParsing:
    """Tests for date parsing logic."""

    def test_parse_date_mm_dd_yyyy(self, mapper: SimplicityMapper) -> None:
        """Test MM/DD/YYYY format (Simplicity standard)."""
        assert mapper._parse_date("01/15/2024") == date(2024, 1, 15)
        assert mapper._parse_date("12/31/2023") == date(2023, 12, 31)

    def test_parse_date_iso(self, mapper: SimplicityMapper) -> None:
        """Test ISO YYYY-MM-DD format."""
        assert mapper._parse_date("2024-01-15") == date(2024, 1, 15)
        assert mapper._parse_date("2023-12-31") == date(2023, 12, 31)

    def test_parse_date_short_year(self, mapper: SimplicityMapper) -> None:
        """Test M/D/YY short format."""
        assert mapper._parse_date("1/5/24") == date(2024, 1, 5)

    def test_parse_date_edge_cases(self, mapper: SimplicityMapper) -> None:
        """Test edge cases for date parsing."""
        assert mapper._parse_date(None) is None
        assert mapper._parse_date("") is None
        assert mapper._parse_date(date(2024, 1, 15)) == date(2024, 1, 15)

    def test_parse_date_invalid(self, mapper: SimplicityMapper) -> None:
        """Test invalid date values raise ValueError."""
        with pytest.raises(ValueError, match="Cannot parse date"):
            mapper._parse_date("not-a-date")


class TestFormatDetection:
    """Tests for Simplicity format detection."""

    def test_is_simplicity_format_valid(self, sample_df: pd.DataFrame) -> None:
        """Test detection of valid Simplicity format."""
        assert is_simplicity_format(sample_df) is True

    def test_is_simplicity_format_variations(self) -> None:
        """Test detection with column name variations."""
        df = pd.DataFrame(
            {
                "case_number": ["CIV-001"],
                "plaintiff_name": ["Test"],
                "defendant_name": ["Test"],
                "amount": ["1000"],
            }
        )
        assert is_simplicity_format(df) is True

    def test_is_simplicity_format_missing_columns(self) -> None:
        """Test detection fails with missing required columns."""
        df = pd.DataFrame(
            {
                "Case Number": ["CIV-001"],
                "County": ["Kings"],
            }
        )
        assert is_simplicity_format(df) is False

    def test_is_simplicity_format_empty(self) -> None:
        """Test detection returns False for empty DataFrame."""
        assert is_simplicity_format(pd.DataFrame()) is False


class TestMappedRow:
    """Tests for MappedRow dataclass."""

    def test_mapped_row_is_valid(self) -> None:
        """Test is_valid() method."""
        valid_row = MappedRow(
            case_number="CIV-001",
            plaintiff_name="Test",
            judgment_amount=Decimal("1000"),
        )
        assert valid_row.is_valid() is True

        invalid_row = MappedRow(
            case_number="CIV-002",
            errors=["Missing required field"],
        )
        assert invalid_row.is_valid() is False

    def test_mapped_row_to_insert_dict(self) -> None:
        """Test to_insert_dict() method."""
        row = MappedRow(
            case_number="CIV-001",
            plaintiff_name="Test Plaintiff",
            defendant_name="Test Defendant",
            judgment_amount=Decimal("1500.50"),
            entry_date=date(2024, 1, 15),
            county="Kings",
        )

        insert_dict = row.to_insert_dict()

        assert insert_dict["case_number"] == "CIV-001"
        assert insert_dict["plaintiff_name"] == "Test Plaintiff"
        assert insert_dict["judgment_amount"] == 1500.50  # Float for DB
        assert insert_dict["entry_date"] == date(2024, 1, 15)
        assert insert_dict["county"] == "Kings"
        assert insert_dict["court"] is None


# =============================================================================
# Integration Tests (require database connection)
# =============================================================================


@pytest.mark.integration
class TestSimplicityPipelineIntegration:
    """Integration tests for the full Simplicity pipeline.

    These tests require a database connection and the intake schema tables.
    Skip if not running integration tests.
    """

    @pytest.fixture
    def db_url(self) -> str:
        """Get database URL from environment."""
        import os

        url = os.environ.get("SUPABASE_DB_URL_DEV") or os.environ.get("SUPABASE_DB_URL")
        if not url:
            pytest.skip("Database URL not configured")
        return url

    def test_create_and_process_batch(self, db_url: str, sample_df: pd.DataFrame) -> None:
        """Test creating and processing a complete batch."""
        import psycopg

        from backend.services.simplicity_mapper import create_batch, process_simplicity_batch

        source_ref = f"test-batch-{uuid.uuid4().hex[:8]}"

        with psycopg.connect(db_url) as conn:
            result = process_simplicity_batch(conn, sample_df, "test_sample.csv", source_ref)

            assert result.batch_id is not None
            assert result.total_rows == 3
            assert result.staged_rows == 3
            assert result.valid_rows == 3
            assert result.invalid_rows == 0
            assert result.inserted_rows >= 0  # May be 0 if duplicates

            # Verify batch record
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM intake.simplicity_batches WHERE id = %s",
                    (result.batch_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert row[0] == "completed"

    def test_duplicate_batch_prevention(self, db_url: str, sample_df: pd.DataFrame) -> None:
        """Test that duplicate batches are prevented by source_reference."""
        import psycopg

        from backend.services.simplicity_mapper import process_simplicity_batch

        source_ref = f"test-dup-{uuid.uuid4().hex[:8]}"

        with psycopg.connect(db_url) as conn:
            # First batch should succeed
            result1 = process_simplicity_batch(conn, sample_df, "test_dup_1.csv", source_ref)
            assert result1.error_summary is None

            # Second batch with same source_ref should be flagged as duplicate
            result2 = process_simplicity_batch(conn, sample_df, "test_dup_2.csv", source_ref)
            assert result2.duplicate_rows == len(sample_df)
            assert "Duplicate batch" in (result2.error_summary or "")


# =============================================================================
# CSV File Tests
# =============================================================================


class TestCSVFileProcessing:
    """Tests for CSV file loading and validation."""

    def test_load_sample_csv(self, temp_csv_file: Path) -> None:
        """Test loading a sample CSV file."""
        df = pd.read_csv(temp_csv_file)

        assert len(df) == 3
        assert "Case Number" in df.columns
        assert is_simplicity_format(df)

    def test_process_csv_with_missing_columns(self) -> None:
        """Test handling of CSV with missing required columns."""
        df = pd.DataFrame(
            {
                "Case Number": ["CIV-001"],
                "Random Column": ["value"],
            }
        )

        assert not is_simplicity_format(df)

    def test_process_empty_csv(self) -> None:
        """Test handling of empty CSV."""
        df = pd.DataFrame()
        assert not is_simplicity_format(df)


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_whitespace_handling(self, mapper: SimplicityMapper) -> None:
        """Test that whitespace is properly trimmed."""
        df = pd.DataFrame(
            {
                "Case Number": ["  CIV-001  "],
                "Plaintiff": ["  Test Plaintiff  "],
                "Defendant": ["Test Defendant"],
                "Judgment Amount": ["  $1,000.00  "],
                "Filing Date": ["  01/15/2024  "],
                "County": ["  Kings  "],
            }
        )

        mapping = mapper.detect_column_mapping(df)
        rows = mapper.transform_dataframe(df, mapping)

        assert rows[0].case_number == "CIV-001"
        assert rows[0].plaintiff_name == "Test Plaintiff"
        assert rows[0].county == "Kings"
        assert rows[0].judgment_amount == Decimal("1000.00")

    def test_unicode_handling(self, mapper: SimplicityMapper) -> None:
        """Test handling of Unicode characters."""
        df = pd.DataFrame(
            {
                "Case Number": ["CIV-2024-001"],
                "Plaintiff": ["José García"],
                "Defendant": ["François Müller"],
                "Judgment Amount": ["1000"],
            }
        )

        mapping = mapper.detect_column_mapping(df)
        rows = mapper.transform_dataframe(df, mapping)

        assert rows[0].plaintiff_name == "José García"
        assert rows[0].defendant_name == "François Müller"

    def test_large_amounts(self, mapper: SimplicityMapper) -> None:
        """Test handling of large judgment amounts."""
        df = pd.DataFrame(
            {
                "Case Number": ["CIV-001"],
                "Plaintiff": ["Big Corp"],
                "Defendant": ["Mega Corp"],
                "Judgment Amount": ["$10,000,000.00"],
            }
        )

        mapping = mapper.detect_column_mapping(df)
        rows = mapper.transform_dataframe(df, mapping)

        assert rows[0].judgment_amount == Decimal("10000000.00")

    def test_zero_amount(self, mapper: SimplicityMapper) -> None:
        """Test handling of zero judgment amount."""
        df = pd.DataFrame(
            {
                "Case Number": ["CIV-001"],
                "Plaintiff": ["Test"],
                "Defendant": ["Test"],
                "Judgment Amount": ["0"],
            }
        )

        mapping = mapper.detect_column_mapping(df)
        rows = mapper.transform_dataframe(df, mapping)

        assert rows[0].judgment_amount == Decimal("0")
        assert rows[0].is_valid()  # Zero is valid, just not useful
