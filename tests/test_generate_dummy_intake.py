"""Tests for the dummy intake CSV generator."""

import csv
from pathlib import Path
import tempfile

import pytest

from tools.generate_dummy_intake import (
    CSV_HEADERS,
    generate_dummy_csv,
    generate_case_number,
    generate_defendant_name,
    generate_judgment_amount,
    generate_judgment_date,
    generate_row,
)


class TestGenerateDummyCsv:
    """Test the main CSV generation function."""

    def test_creates_file(self, tmp_path: Path) -> None:
        """CSV file is created at the specified path."""
        output = tmp_path / "test_intake.csv"
        generate_dummy_csv(output, num_rows=3)
        assert output.exists()

    def test_correct_row_count(self, tmp_path: Path) -> None:
        """CSV has the expected number of data rows."""
        output = tmp_path / "test_intake.csv"
        generate_dummy_csv(output, num_rows=7)

        with output.open() as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Header + 7 data rows
        assert len(rows) == 8

    def test_correct_headers(self, tmp_path: Path) -> None:
        """CSV has the correct Simplicity-compatible headers."""
        output = tmp_path / "test_intake.csv"
        generate_dummy_csv(output, num_rows=2)

        with output.open() as f:
            reader = csv.reader(f)
            headers = next(reader)

        assert headers == CSV_HEADERS

    def test_utf8_encoding(self, tmp_path: Path) -> None:
        """CSV is written with UTF-8 encoding."""
        output = tmp_path / "test_intake.csv"
        generate_dummy_csv(output, num_rows=2)

        # Should be readable as UTF-8 without errors
        content = output.read_text(encoding="utf-8")
        assert "CaseNo" in content

    def test_returns_generated_rows(self, tmp_path: Path) -> None:
        """Function returns the list of generated rows."""
        output = tmp_path / "test_intake.csv"
        rows = generate_dummy_csv(output, num_rows=5)

        assert len(rows) == 5
        assert all(isinstance(r, dict) for r in rows)


class TestGenerateRow:
    """Test individual row generation."""

    def test_row_has_all_fields(self) -> None:
        """Generated row contains all required fields."""
        row = generate_row()
        for header in CSV_HEADERS:
            assert header in row, f"Missing field: {header}"

    def test_high_amount_flag(self) -> None:
        """ensure_high_amount produces amounts >= 25000."""
        for _ in range(10):
            row = generate_row(ensure_high_amount=True)
            amount = float(row["JudgmentAmount"])
            assert amount >= 25000, f"Expected >= 25000, got {amount}"


class TestGenerateCaseNumber:
    """Test case number generation."""

    def test_returns_string(self) -> None:
        """Case number is a non-empty string."""
        case_no = generate_case_number(2023)
        assert isinstance(case_no, str)
        assert len(case_no) > 0

    def test_includes_year(self) -> None:
        """Case number includes the year."""
        case_no = generate_case_number(2021)
        assert "2021" in case_no


class TestGenerateDefendantName:
    """Test defendant name generation."""

    def test_returns_full_name(self) -> None:
        """Defendant name has first and last name."""
        name = generate_defendant_name()
        parts = name.split()
        assert len(parts) == 2, f"Expected 'First Last', got '{name}'"


class TestGenerateJudgmentAmount:
    """Test judgment amount generation."""

    def test_returns_decimal_string(self) -> None:
        """Amount is a valid decimal string."""
        amount = generate_judgment_amount()
        # Should be parseable as float
        value = float(amount)
        assert value > 0


class TestGenerateJudgmentDate:
    """Test judgment date generation."""

    def test_returns_iso_date(self) -> None:
        """Date is in ISO format (YYYY-MM-DD)."""
        date_str = generate_judgment_date()
        # Should match pattern
        parts = date_str.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # Year
        assert len(parts[1]) == 2  # Month
        assert len(parts[2]) == 2  # Day
