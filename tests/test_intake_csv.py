"""
tests/test_intake_csv.py
========================
Unit tests for the Plaintiff Intake Moat.

Tests cover:
- File hashing (deterministic)
- Dedupe key computation (deterministic)
- CSV parsing with header normalization
- Duplicate batch detection
- Row-level deduplication
"""

from __future__ import annotations

import csv
import hashlib
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from backend.ingest.intake_csv import (
    CANONICAL_HEADERS,
    ImportResult,
    PlaintiffIntakePipeline,
    PlaintiffRow,
    compute_dedupe_key,
    compute_file_hash,
    compute_file_hash_from_path,
    map_headers,
    normalize_email,
    normalize_name,
    parse_csv,
    sanitize_for_log,
)

# =============================================================================
# Test: Hash Functions
# =============================================================================


class TestFileHashing:
    """Tests for file hash computation."""

    def test_compute_file_hash_deterministic(self):
        """Same content should produce same hash."""
        content = b"test content for hashing"
        hash1 = compute_file_hash(content)
        hash2 = compute_file_hash(content)
        assert hash1 == hash2

    def test_compute_file_hash_different_content(self):
        """Different content should produce different hash."""
        hash1 = compute_file_hash(b"content A")
        hash2 = compute_file_hash(b"content B")
        assert hash1 != hash2

    def test_compute_file_hash_is_sha256(self):
        """Hash should be SHA-256 (64 hex chars)."""
        content = b"test"
        hash_value = compute_file_hash(content)
        assert len(hash_value) == 64
        assert all(c in "0123456789abcdef" for c in hash_value)

    def test_compute_file_hash_from_path(self, tmp_path: Path):
        """Hash from path should match hash from content."""
        content = b"file content to hash"
        filepath = tmp_path / "test.csv"
        filepath.write_bytes(content)

        path_hash = compute_file_hash_from_path(filepath)
        content_hash = compute_file_hash(content)

        assert path_hash == content_hash


# =============================================================================
# Test: Dedupe Key Computation
# =============================================================================


class TestDedupeKey:
    """Tests for dedupe key computation."""

    def test_dedupe_key_deterministic(self):
        """Same inputs should produce same dedupe key."""
        key1 = compute_dedupe_key("simplicity", "John Doe", "john@example.com")
        key2 = compute_dedupe_key("simplicity", "John Doe", "john@example.com")
        assert key1 == key2

    def test_dedupe_key_case_insensitive_name(self):
        """Name should be normalized to lowercase."""
        key1 = compute_dedupe_key("simplicity", "John Doe", None)
        key2 = compute_dedupe_key("simplicity", "JOHN DOE", None)
        key3 = compute_dedupe_key("simplicity", "john doe", None)
        assert key1 == key2 == key3

    def test_dedupe_key_whitespace_normalized(self):
        """Whitespace in name should be collapsed."""
        key1 = compute_dedupe_key("simplicity", "John Doe", None)
        key2 = compute_dedupe_key("simplicity", "John  Doe", None)
        key3 = compute_dedupe_key("simplicity", " John   Doe ", None)
        assert key1 == key2 == key3

    def test_dedupe_key_email_normalized(self):
        """Email should be normalized to lowercase."""
        key1 = compute_dedupe_key("simplicity", "John", "John@Example.COM")
        key2 = compute_dedupe_key("simplicity", "john", "john@example.com")
        assert key1 == key2

    def test_dedupe_key_different_source(self):
        """Different source systems should produce different keys."""
        key1 = compute_dedupe_key("simplicity", "John Doe", None)
        key2 = compute_dedupe_key("jbi", "John Doe", None)
        assert key1 != key2

    def test_dedupe_key_with_none_email(self):
        """None email should work."""
        key1 = compute_dedupe_key("simplicity", "John", None)
        key2 = compute_dedupe_key("simplicity", "John", "")
        assert key1 == key2

    def test_dedupe_key_is_sha256(self):
        """Dedupe key should be SHA-256 (64 hex chars)."""
        key = compute_dedupe_key("src", "name", "email@test.com")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)


# =============================================================================
# Test: Name/Email Normalization
# =============================================================================


class TestNormalization:
    """Tests for name and email normalization."""

    def test_normalize_name_lowercase(self):
        """Name should be lowercased."""
        assert normalize_name("JOHN DOE") == "john doe"

    def test_normalize_name_whitespace(self):
        """Whitespace should be collapsed."""
        assert normalize_name("  John   Doe  ") == "john doe"

    def test_normalize_name_empty(self):
        """Empty name should return empty string."""
        assert normalize_name("") == ""
        assert normalize_name("   ") == ""

    def test_normalize_email_lowercase(self):
        """Email should be lowercased."""
        assert normalize_email("John@Example.COM") == "john@example.com"

    def test_normalize_email_strip(self):
        """Email should be stripped."""
        assert normalize_email("  john@example.com  ") == "john@example.com"

    def test_normalize_email_none(self):
        """None email should return None."""
        assert normalize_email(None) is None
        assert normalize_email("") is None
        assert normalize_email("   ") is None


# =============================================================================
# Test: Header Mapping
# =============================================================================


class TestHeaderMapping:
    """Tests for CSV header mapping."""

    def test_map_headers_standard(self):
        """Standard headers should map correctly."""
        headers = ["PlaintiffName", "FirmName", "ContactEmail"]
        mapping = map_headers(headers)

        assert mapping["PlaintiffName"] == "plaintiff_name"
        assert mapping["FirmName"] == "firm_name"
        assert mapping["ContactEmail"] == "contact_email"

    def test_map_headers_snake_case(self):
        """snake_case headers should map correctly."""
        headers = ["plaintiff_name", "firm_name", "contact_email"]
        mapping = map_headers(headers)

        assert mapping["plaintiff_name"] == "plaintiff_name"
        assert mapping["firm_name"] == "firm_name"
        assert mapping["contact_email"] == "contact_email"

    def test_map_headers_simple(self):
        """Simple headers should map correctly."""
        headers = ["name", "firm", "email", "phone", "address"]
        mapping = map_headers(headers)

        assert mapping["name"] == "plaintiff_name"
        assert mapping["firm"] == "firm_name"
        assert mapping["email"] == "contact_email"
        assert mapping["phone"] == "contact_phone"
        assert mapping["address"] == "contact_address"

    def test_map_headers_unknown(self):
        """Unknown headers should map to None."""
        headers = ["custom_field", "unknown_col"]
        mapping = map_headers(headers)

        assert mapping["custom_field"] is None
        assert mapping["unknown_col"] is None


# =============================================================================
# Test: CSV Parsing
# =============================================================================


class TestCsvParsing:
    """Tests for CSV parsing."""

    def _create_csv(self, tmp_path: Path, headers: List[str], rows: List[List[str]]) -> Path:
        """Helper to create a test CSV file."""
        filepath = tmp_path / "test.csv"
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for row in rows:
                writer.writerow(row)
        return filepath

    def test_parse_csv_basic(self, tmp_path: Path):
        """Basic CSV parsing should work."""
        filepath = self._create_csv(
            tmp_path,
            ["PlaintiffName", "FirmName", "ContactEmail"],
            [
                ["John Doe", "Doe Law Firm", "john@doe.com"],
                ["Jane Smith", "Smith Legal", "jane@smith.com"],
            ],
        )

        result = parse_csv(filepath, "test")

        assert len(result.rows) == 2
        assert result.rows[0].plaintiff_name == "John Doe"
        assert result.rows[0].firm_name == "Doe Law Firm"
        assert result.rows[0].contact_email == "john@doe.com"
        assert result.rows[1].plaintiff_name == "Jane Smith"

    def test_parse_csv_generates_dedupe_keys(self, tmp_path: Path):
        """Parsing should generate dedupe keys for each row."""
        filepath = self._create_csv(
            tmp_path,
            ["PlaintiffName", "ContactEmail"],
            [
                ["John Doe", "john@doe.com"],
                ["Jane Smith", "jane@smith.com"],
            ],
        )

        result = parse_csv(filepath, "test")

        assert result.rows[0].dedupe_key != ""
        assert result.rows[1].dedupe_key != ""
        assert result.rows[0].dedupe_key != result.rows[1].dedupe_key

    def test_parse_csv_tracks_row_index(self, tmp_path: Path):
        """Parsing should track 0-based row index."""
        filepath = self._create_csv(
            tmp_path,
            ["PlaintiffName"],
            [["A"], ["B"], ["C"]],
        )

        result = parse_csv(filepath, "test")

        assert result.rows[0].row_index == 0
        assert result.rows[1].row_index == 1
        assert result.rows[2].row_index == 2

    def test_parse_csv_missing_required_column(self, tmp_path: Path):
        """Parsing should fail if required column is missing."""
        filepath = self._create_csv(
            tmp_path,
            ["FirmName", "ContactEmail"],  # Missing PlaintiffName
            [["Firm", "email@test.com"]],
        )

        with pytest.raises(ValueError, match="Missing required columns"):
            parse_csv(filepath, "test")

    def test_parse_csv_empty_name_creates_error(self, tmp_path: Path):
        """Empty plaintiff name should create error row."""
        filepath = self._create_csv(
            tmp_path,
            ["PlaintiffName", "FirmName"],
            [
                ["John Doe", "Firm A"],
                ["", "Firm B"],  # Empty name
            ],
        )

        result = parse_csv(filepath, "test")

        assert len(result.rows) == 2
        assert result.rows[0].error is None
        assert result.rows[1].error is not None
        assert "plaintiff_name" in result.rows[1].error.lower()

    def test_parse_csv_preserves_raw_payload(self, tmp_path: Path):
        """Raw payload should contain original row data."""
        filepath = self._create_csv(
            tmp_path,
            ["PlaintiffName", "CustomField"],
            [["John", "custom_value"]],
        )

        result = parse_csv(filepath, "test")

        assert "PlaintiffName" in result.rows[0].raw_payload
        assert "CustomField" in result.rows[0].raw_payload
        assert result.rows[0].raw_payload["CustomField"] == "custom_value"


# =============================================================================
# Test: Import Result
# =============================================================================


class TestImportResult:
    """Tests for ImportResult."""

    def test_summary_normal(self):
        """Summary should show counts."""
        result = ImportResult(
            import_run_id="abc",
            source_system="test",
            source_batch_id="batch1",
            file_hash="hash123",
            filename="test.csv",
            status="completed",
            rows_fetched=100,
            rows_inserted=90,
            rows_skipped=8,
            rows_errored=2,
        )

        summary = result.summary()

        assert "100 fetched" in summary
        assert "90 inserted" in summary
        assert "8 skipped" in summary
        assert "2 errored" in summary

    def test_summary_duplicate_batch(self):
        """Summary for duplicate batch should indicate no action."""
        result = ImportResult(
            import_run_id="abc",
            source_system="test",
            source_batch_id="batch1",
            file_hash="hash123",
            filename="test.csv",
            is_duplicate_batch=True,
        )

        summary = result.summary()

        assert "DUPLICATE BATCH" in summary
        assert "already been imported" in summary


# =============================================================================
# Test: Idempotency (Integration-style, mocked DB)
# =============================================================================


class TestIdempotencyLogic:
    """Tests for idempotency logic with mocked database."""

    def test_same_file_hash_produces_same_hash(self, tmp_path: Path):
        """Same file should always produce the same hash."""
        content = b"plaintiff data goes here"

        file1 = tmp_path / "file1.csv"
        file2 = tmp_path / "file2.csv"
        file1.write_bytes(content)
        file2.write_bytes(content)

        hash1 = compute_file_hash_from_path(file1)
        hash2 = compute_file_hash_from_path(file2)

        assert hash1 == hash2

    def test_different_files_produce_different_hashes(self, tmp_path: Path):
        """Different files should produce different hashes."""
        file1 = tmp_path / "file1.csv"
        file2 = tmp_path / "file2.csv"
        file1.write_bytes(b"content A")
        file2.write_bytes(b"content B")

        hash1 = compute_file_hash_from_path(file1)
        hash2 = compute_file_hash_from_path(file2)

        assert hash1 != hash2

    def test_same_row_in_different_batches_same_dedupe_key(self, tmp_path: Path):
        """Same plaintiff in different files should have same dedupe key."""
        # Simulate two files with overlapping plaintiff
        common_name = "John Doe Legal Group"
        common_email = "contact@johndoe.com"

        key1 = compute_dedupe_key("simplicity", common_name, common_email)
        key2 = compute_dedupe_key("simplicity", common_name, common_email)

        assert key1 == key2


# =============================================================================
# Test: Dry Run Mode
# =============================================================================


class TestDryRunMode:
    """Tests for dry run mode."""

    def _create_test_csv(self, tmp_path: Path) -> Path:
        """Create a test CSV file."""
        filepath = tmp_path / "test_plaintiffs.csv"
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["PlaintiffName", "FirmName", "ContactEmail"])
            writer.writerow(["John Doe", "Doe Firm", "john@doe.com"])
            writer.writerow(["Jane Smith", "Smith LLC", "jane@smith.com"])
        return filepath

    def test_dry_run_does_not_require_db(self, tmp_path: Path):
        """Dry run should work without database connection."""
        filepath = self._create_test_csv(tmp_path)

        # Create pipeline with no DB URL (will use env fallback)
        pipeline = PlaintiffIntakePipeline(db_url="postgresql://fake:fake@fake/fake")

        # Dry run should not connect to DB
        result = pipeline.import_csv(
            filepath=filepath,
            source_system="test",
            dry_run=True,
        )

        assert result.status == "dry_run"
        assert result.rows_fetched == 2
        assert result.rows_inserted == 2  # Would be inserted

    def test_dry_run_detects_errors(self, tmp_path: Path):
        """Dry run should detect parsing errors."""
        filepath = tmp_path / "test.csv"
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["PlaintiffName", "FirmName"])
            writer.writerow(["Valid Name", "Firm"])
            writer.writerow(["", "No Name"])  # Error: empty name

        pipeline = PlaintiffIntakePipeline(db_url="postgresql://fake:fake@fake/fake")
        result = pipeline.import_csv(
            filepath=filepath,
            source_system="test",
            dry_run=True,
        )

        assert result.rows_fetched == 2
        assert result.rows_errored == 1


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_unicode_in_name(self, tmp_path: Path):
        """Unicode characters in name should be handled."""
        filepath = tmp_path / "unicode.csv"
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["PlaintiffName"])
            writer.writerow(["José García"])
            writer.writerow(["北京律师事务所"])  # Chinese law firm

        result = parse_csv(filepath, "test")

        assert len(result.valid_rows) == 2
        assert result.rows[0].plaintiff_name == "José García"
        assert result.rows[1].plaintiff_name == "北京律师事务所"

    def test_very_long_name(self, tmp_path: Path):
        """Very long names should be handled."""
        long_name = "A" * 1000
        filepath = tmp_path / "long.csv"
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["PlaintiffName"])
            writer.writerow([long_name])

        result = parse_csv(filepath, "test")

        assert len(result.valid_rows) == 1
        assert result.rows[0].plaintiff_name == long_name

    def test_special_characters_in_email(self):
        """Special characters in email should be normalized."""
        email = "john+test@example.com"
        normalized = normalize_email(email)
        assert normalized == "john+test@example.com"

    def test_empty_csv_no_rows(self, tmp_path: Path):
        """CSV with only headers should produce zero rows."""
        filepath = tmp_path / "empty.csv"
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["PlaintiffName", "FirmName"])
            # No data rows

        result = parse_csv(filepath, "test")

        assert len(result.rows) == 0


# =============================================================================
# Test: PII Log Redaction
# =============================================================================


class TestPIILogRedaction:
    """
    Tests for PII log redaction.

    CRITICAL: SSN-like patterns must NEVER appear in logs.
    Emails and phones are acceptable to log.
    """

    def test_ssn_basic_format_redacted(self):
        """Standard SSN format XXX-XX-XXXX must be redacted."""
        value = "John Doe SSN: 123-45-6789 is here"
        sanitized = sanitize_for_log(value)

        assert "[REDACTED-SSN]" in sanitized
        assert "123-45-6789" not in sanitized

    def test_ssn_multiple_redacted(self):
        """Multiple SSNs in same string must all be redacted."""
        value = "SSN1: 111-22-3333 and SSN2: 444-55-6666"
        sanitized = sanitize_for_log(value)

        assert "111-22-3333" not in sanitized
        assert "444-55-6666" not in sanitized
        assert sanitized.count("[REDACTED-SSN]") == 2

    def test_ssn_at_start_redacted(self):
        """SSN at start of string must be redacted."""
        value = "123-45-6789 is the SSN"
        sanitized = sanitize_for_log(value)

        assert "123-45-6789" not in sanitized

    def test_ssn_at_end_redacted(self):
        """SSN at end of string must be redacted."""
        value = "The SSN is 123-45-6789"
        sanitized = sanitize_for_log(value)

        assert "123-45-6789" not in sanitized

    def test_ssn_only_redacted(self):
        """String with only SSN must be fully redacted."""
        value = "123-45-6789"
        sanitized = sanitize_for_log(value)

        assert sanitized == "[REDACTED-SSN]"

    def test_credit_card_redacted(self):
        """Credit card numbers must be redacted."""
        value = "Card: 4111-1111-1111-1111 charged"
        sanitized = sanitize_for_log(value)

        assert "[REDACTED-CC]" in sanitized
        assert "4111-1111-1111-1111" not in sanitized

    def test_credit_card_no_dashes_redacted(self):
        """Credit card without dashes must be redacted."""
        value = "Card: 4111111111111111 charged"
        sanitized = sanitize_for_log(value)

        assert "[REDACTED-CC]" in sanitized
        assert "4111111111111111" not in sanitized

    def test_credit_card_spaces_redacted(self):
        """Credit card with spaces must be redacted."""
        value = "Card: 4111 1111 1111 1111 charged"
        sanitized = sanitize_for_log(value)

        assert "[REDACTED-CC]" in sanitized
        assert "4111 1111 1111 1111" not in sanitized

    def test_email_allowed_in_log(self):
        """Email addresses are allowed to be logged."""
        value = "Contact: john.doe@example.com for details"
        sanitized = sanitize_for_log(value)

        # Email should NOT be redacted
        assert "john.doe@example.com" in sanitized
        assert "[REDACTED" not in sanitized

    def test_phone_allowed_in_log(self):
        """Phone numbers are allowed to be logged."""
        value = "Call (555) 123-4567 for assistance"
        sanitized = sanitize_for_log(value)

        # Phone should NOT be redacted (different from SSN format)
        assert "(555) 123-4567" in sanitized

    def test_truncation_applied(self):
        """Long strings should be truncated."""
        value = "A" * 200
        sanitized = sanitize_for_log(value, max_len=50)

        assert len(sanitized) == 53  # 50 chars + "..."
        assert sanitized.endswith("...")

    def test_empty_string_safe(self):
        """Empty string should return empty."""
        assert sanitize_for_log("") == ""
        assert sanitize_for_log(None) == ""  # type: ignore

    def test_ssn_not_in_log_output(self, tmp_path: Path, caplog):
        """
        CRITICAL TEST: Ensure SSN-like patterns never appear in actual log output.

        This test parses a CSV with SSN-like data and verifies the log
        messages do not contain the sensitive patterns.
        """
        import logging

        # Create CSV with SSN-like data in a custom field
        filepath = tmp_path / "sensitive.csv"
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["PlaintiffName", "CustomSSN"])
            writer.writerow(["John Doe", "123-45-6789"])

        # Parse with logging enabled
        with caplog.at_level(logging.DEBUG):
            result = parse_csv(filepath, "test")

        # Check that SSN pattern does not appear in any log message
        for record in caplog.records:
            assert (
                "123-45-6789" not in record.message
            ), f"SSN pattern found in log message: {record.message}"

    def test_ssn_variations_all_redacted(self):
        """Various SSN-like patterns must all be redacted."""
        test_cases = [
            "SSN: 123-45-6789",  # Standard
            "ssn 111-22-3333",  # Lowercase prefix
            "Tax ID: 999-88-7777",  # With Tax ID label
            "ID#123-45-6789#",  # With special chars around
        ]

        for value in test_cases:
            sanitized = sanitize_for_log(value)
            # Extract the SSN pattern (XXX-XX-XXXX)
            import re

            ssn_matches = re.findall(r"\b\d{3}-\d{2}-\d{4}\b", value)
            for ssn in ssn_matches:
                assert ssn not in sanitized, f"SSN {ssn} not redacted in: {sanitized}"

    def test_non_ssn_numbers_not_redacted(self):
        """Numbers that don't match SSN format should not be redacted."""
        test_cases = [
            ("Case #12345678", "12345678"),  # 8 digits
            ("Ref: 123-456-7890", "123-456-7890"),  # Phone-like (10 digits)
            ("ID: 12-34-5678", "12-34-5678"),  # Wrong grouping
            ("Amount: $1,234.56", "$1,234.56"),  # Currency
        ]

        for value, should_remain in test_cases:
            sanitized = sanitize_for_log(value)
            assert (
                should_remain in sanitized
            ), f"'{should_remain}' incorrectly redacted from '{value}'"
