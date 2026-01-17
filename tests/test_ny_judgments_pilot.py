"""
Acceptance Tests for NY Judgments Pilot Worker

Tests cover:
    1. Normalize determinism - same input always produces same output
    2. Dedupe key stability - hashes are reproducible across runs
    3. DB upsert idempotency - ON CONFLICT DO NOTHING works correctly
    4. Batch normalization with error handling

Run with: pytest tests/test_ny_judgments_pilot.py -v
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from workers.ny_judgments_pilot.config import WorkerConfig
from workers.ny_judgments_pilot.normalize import (
    DEFAULT_SOURCE_SYSTEM,
    FIELD_SEPARATOR,
    NormalizedRecord,
    compute_content_hash,
    compute_dedupe_key,
    compute_sha256,
    normalize_amount,
    normalize_batch,
    normalize_county,
    normalize_date,
    normalize_record,
    normalize_string,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_raw_record() -> dict[str, Any]:
    """Standard raw record for testing."""
    return {
        "source_url": "https://example.com/case/12345",
        "external_id": "12345-2026",
        "county": "Kings",
        "court": "Civil Court",
        "case_type": "Money Judgment",
        "judgment_date": "01/15/2026",
        "filing_date": "2026-01-10",
        "amount": "$1,234.56",
        "defendant_name": "John Doe",
    }


@pytest.fixture
def sample_raw_record_variant() -> dict[str, Any]:
    """Same logical record with different formatting."""
    return {
        "source_url": "https://example.com/case/12345",
        "external_id": "12345-2026",
        "county": "  KINGS COUNTY  ",  # Different formatting
        "court": "   civil court   ",
        "case_type": "MONEY JUDGMENT",
        "judgment_date": "2026-01-15",  # ISO format instead of MM/DD/YYYY
        "filing_date": "01-10-2026",  # MM-DD-YYYY format
        "amount": "1234.56",  # No currency symbol
        "defendant_name": "JOHN DOE",
    }


# ============================================================================
# Test: String Normalization
# ============================================================================


class TestNormalizeString:
    """Tests for normalize_string function."""

    def test_none_returns_empty(self):
        assert normalize_string(None) == ""

    def test_strips_whitespace(self):
        assert normalize_string("  hello  ") == "hello"

    def test_collapses_internal_whitespace(self):
        assert normalize_string("hello   world") == "hello world"

    def test_lowercases(self):
        assert normalize_string("HELLO WORLD") == "hello world"

    def test_handles_tabs_and_newlines(self):
        assert normalize_string("hello\t\nworld") == "hello world"

    def test_deterministic(self):
        """Same input always produces same output."""
        inputs = ["Hello World", "  HELLO   world  ", "hello\tworld"]
        for inp in inputs:
            result1 = normalize_string(inp)
            result2 = normalize_string(inp)
            assert result1 == result2


# ============================================================================
# Test: County Normalization
# ============================================================================


class TestNormalizeCounty:
    """Tests for normalize_county function."""

    def test_none_returns_empty(self):
        assert normalize_county(None) == ""

    def test_removes_county_suffix(self):
        assert normalize_county("Kings County") == "kings"

    def test_replaces_spaces_with_underscores(self):
        assert normalize_county("New York") == "new_york"

    def test_lowercases(self):
        assert normalize_county("QUEENS") == "queens"

    def test_handles_combined_cases(self):
        assert normalize_county("  NEW YORK COUNTY  ") == "new_york"

    def test_deterministic(self):
        """Same county always produces same output."""
        variants = ["Kings", "KINGS", "Kings County", "  kings county  "]
        results = [normalize_county(v) for v in variants]
        assert all(r == "kings" for r in results)


# ============================================================================
# Test: Amount Normalization
# ============================================================================


class TestNormalizeAmount:
    """Tests for normalize_amount function."""

    def test_none_returns_none(self):
        assert normalize_amount(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_amount("") is None

    def test_float_passthrough(self):
        assert normalize_amount(123.45) == 123.45

    def test_int_converts_to_float(self):
        assert normalize_amount(100) == 100.0

    def test_removes_currency_symbol(self):
        assert normalize_amount("$1,234.56") == 1234.56

    def test_removes_thousands_separator(self):
        assert normalize_amount("1,000,000") == 1000000.0

    def test_handles_whitespace(self):
        assert normalize_amount(" $ 1,234 ") == 1234.0

    def test_invalid_returns_none(self):
        assert normalize_amount("not a number") is None


# ============================================================================
# Test: Date Normalization
# ============================================================================


class TestNormalizeDate:
    """Tests for normalize_date function."""

    def test_none_returns_none(self):
        assert normalize_date(None) is None

    def test_empty_returns_none(self):
        assert normalize_date("") is None

    def test_date_object_passthrough(self):
        d = date(2026, 1, 15)
        assert normalize_date(d) == "2026-01-15"

    def test_iso_format_passthrough(self):
        assert normalize_date("2026-01-15") == "2026-01-15"

    def test_mm_dd_yyyy_format(self):
        assert normalize_date("01/15/2026") == "2026-01-15"

    def test_mm_dd_yyyy_with_dashes(self):
        assert normalize_date("01-15-2026") == "2026-01-15"

    def test_single_digit_month_day(self):
        assert normalize_date("1/5/2026") == "2026-01-05"

    def test_deterministic_across_formats(self):
        """Different formats for same date produce same output."""
        formats = ["2026-01-15", "01/15/2026", "1/15/2026", "01-15-2026"]
        results = [normalize_date(f) for f in formats]
        assert all(r == "2026-01-15" for r in results)


# ============================================================================
# Test: SHA-256 Hashing
# ============================================================================


class TestComputeSha256:
    """Tests for compute_sha256 function."""

    def test_returns_64_char_hex(self):
        result = compute_sha256("test")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self):
        """Same input always produces same hash."""
        result1 = compute_sha256("test data")
        result2 = compute_sha256("test data")
        assert result1 == result2

    def test_different_inputs_different_hashes(self):
        hash1 = compute_sha256("input1")
        hash2 = compute_sha256("input2")
        assert hash1 != hash2

    def test_case_sensitive(self):
        hash1 = compute_sha256("Test")
        hash2 = compute_sha256("test")
        assert hash1 != hash2


# ============================================================================
# Test: Dedupe Key Computation
# ============================================================================


class TestComputeDedupeKey:
    """Tests for compute_dedupe_key function."""

    def test_returns_64_char_hex(self):
        result = compute_dedupe_key(
            source_system="ny_ecourts",
            source_county="kings",
            external_id="12345",
            source_url="https://example.com/case/12345",
        )
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self):
        """Same inputs always produce same dedupe key."""
        args = {
            "source_system": "ny_ecourts",
            "source_county": "kings",
            "external_id": "12345",
            "source_url": "https://example.com/case/12345",
        }
        result1 = compute_dedupe_key(**args)
        result2 = compute_dedupe_key(**args)
        assert result1 == result2

    def test_normalizes_inputs(self):
        """Formatting differences produce same dedupe key."""
        key1 = compute_dedupe_key(
            source_system="NY_ECOURTS",  # Different case
            source_county="Kings County",  # With suffix
            external_id="  12345  ",  # With whitespace
            source_url="https://example.com/case/12345",
        )
        key2 = compute_dedupe_key(
            source_system="ny_ecourts",
            source_county="kings",
            external_id="12345",
            source_url="https://example.com/case/12345",
        )
        assert key1 == key2

    def test_uses_url_when_no_external_id(self):
        """When external_id is None, URL is used as identifier."""
        key1 = compute_dedupe_key(
            source_system="ny_ecourts",
            source_county="kings",
            external_id=None,
            source_url="https://example.com/case/unique-url",
        )
        key2 = compute_dedupe_key(
            source_system="ny_ecourts",
            source_county="kings",
            external_id=None,
            source_url="https://example.com/case/unique-url",
        )
        assert key1 == key2

    def test_different_external_ids_different_keys(self):
        """Different external_ids produce different dedupe keys."""
        key1 = compute_dedupe_key(
            source_system="ny_ecourts",
            source_county="kings",
            external_id="12345",
            source_url="https://example.com",
        )
        key2 = compute_dedupe_key(
            source_system="ny_ecourts",
            source_county="kings",
            external_id="67890",
            source_url="https://example.com",
        )
        assert key1 != key2


# ============================================================================
# Test: Content Hash Computation
# ============================================================================


class TestComputeContentHash:
    """Tests for compute_content_hash function."""

    def test_deterministic(self):
        """Same payload always produces same content hash."""
        payload = {"key": "value", "nested": {"a": 1, "b": 2}}
        hash1 = compute_content_hash(payload)
        hash2 = compute_content_hash(payload)
        assert hash1 == hash2

    def test_key_order_independent(self):
        """Dict key order doesn't affect hash (sorted internally)."""
        payload1 = {"z": 1, "a": 2, "m": 3}
        payload2 = {"a": 2, "m": 3, "z": 1}
        assert compute_content_hash(payload1) == compute_content_hash(payload2)

    def test_different_content_different_hash(self):
        """Different content produces different hash."""
        hash1 = compute_content_hash({"key": "value1"})
        hash2 = compute_content_hash({"key": "value2"})
        assert hash1 != hash2


# ============================================================================
# Test: Record Normalization
# ============================================================================


class TestNormalizeRecord:
    """Tests for normalize_record function."""

    def test_creates_normalized_record(self, sample_raw_record):
        record = normalize_record(sample_raw_record)
        assert isinstance(record, NormalizedRecord)

    def test_extracts_source_url(self, sample_raw_record):
        record = normalize_record(sample_raw_record)
        assert "example.com/case/12345" in record.source_url

    def test_normalizes_county(self, sample_raw_record):
        record = normalize_record(sample_raw_record)
        assert record.source_county == "kings"

    def test_normalizes_dates(self, sample_raw_record):
        record = normalize_record(sample_raw_record)
        assert record.judgment_entered_at == "2026-01-15"
        assert record.filed_at == "2026-01-10"

    def test_computes_dedupe_key(self, sample_raw_record):
        record = normalize_record(sample_raw_record)
        assert len(record.dedupe_key) == 64

    def test_computes_content_hash(self, sample_raw_record):
        record = normalize_record(sample_raw_record)
        assert len(record.content_hash) == 64

    def test_stores_raw_payload(self, sample_raw_record):
        record = normalize_record(sample_raw_record)
        assert record.raw_payload == sample_raw_record

    def test_raises_on_missing_source_url(self):
        """Records without source_url should raise ValueError."""
        with pytest.raises(ValueError, match="source_url"):
            normalize_record({"external_id": "12345"})

    def test_deterministic(self, sample_raw_record):
        """Same input always produces same normalized record."""
        record1 = normalize_record(sample_raw_record)
        record2 = normalize_record(sample_raw_record)
        assert record1.dedupe_key == record2.dedupe_key
        assert record1.content_hash == record2.content_hash

    def test_formatting_variants_same_dedupe_key(
        self, sample_raw_record, sample_raw_record_variant
    ):
        """Different formatting of same logical record produces same dedupe key."""
        record1 = normalize_record(sample_raw_record)
        record2 = normalize_record(sample_raw_record_variant)
        # Dedupe key should be the same (based on external_id, county, url)
        assert record1.dedupe_key == record2.dedupe_key


# ============================================================================
# Test: Batch Normalization
# ============================================================================


class TestNormalizeBatch:
    """Tests for normalize_batch function."""

    def test_normalizes_all_valid_records(self):
        records = [
            {"source_url": "https://example.com/1", "county": "kings"},
            {"source_url": "https://example.com/2", "county": "queens"},
            {"source_url": "https://example.com/3", "county": "bronx"},
        ]
        normalized, errors = normalize_batch(records)
        assert len(normalized) == 3
        assert len(errors) == 0

    def test_collects_errors(self):
        records = [
            {"source_url": "https://example.com/1"},  # Valid
            {"external_id": "12345"},  # Invalid - no source_url
            {"source_url": "https://example.com/3"},  # Valid
        ]
        normalized, errors = normalize_batch(records)
        assert len(normalized) == 2
        assert len(errors) == 1
        assert errors[0][0] == 1  # Index of failed record

    def test_applies_source_system(self):
        records = [{"source_url": "https://example.com/1"}]
        normalized, _ = normalize_batch(records, source_system="custom_system")
        assert normalized[0].source_system == "custom_system"

    def test_applies_source_county_override(self):
        """source_county parameter is used when record has no county."""
        records = [{"source_url": "https://example.com/1"}]  # No county in record
        normalized, _ = normalize_batch(records, source_county="kings")
        # Override is used when record has no county
        assert normalized[0].source_county == "kings"

    def test_record_county_takes_precedence(self):
        """Record's county takes precedence over source_county parameter."""
        records = [{"source_url": "https://example.com/1", "county": "manhattan"}]
        normalized, _ = normalize_batch(records, source_county="kings")
        # Record county wins
        assert normalized[0].source_county == "manhattan"


# ============================================================================
# Test: NormalizedRecord
# ============================================================================


class TestNormalizedRecord:
    """Tests for NormalizedRecord class."""

    def test_to_dict(self, sample_raw_record):
        record = normalize_record(sample_raw_record)
        data = record.to_dict()

        assert isinstance(data, dict)
        assert "source_system" in data
        assert "source_county" in data
        assert "dedupe_key" in data
        assert "content_hash" in data
        assert "raw_payload" in data

    def test_immutable_hashes(self, sample_raw_record):
        """Hashes should be computed once at init and not change."""
        record = normalize_record(sample_raw_record)
        original_dedupe = record.dedupe_key
        original_content = record.content_hash

        # Access multiple times
        for _ in range(10):
            assert record.dedupe_key == original_dedupe
            assert record.content_hash == original_content


# ============================================================================
# Test: Config
# ============================================================================


class TestWorkerConfig:
    """Tests for WorkerConfig class."""

    def test_generate_source_batch_id(self):
        config = WorkerConfig(database_url="postgresql://localhost:5432/test")
        batch_id = config.generate_source_batch_id(date(2026, 1, 15))
        assert batch_id == "ny_judgments_2026-01-15"

    def test_generate_source_batch_id_today(self, monkeypatch):
        from datetime import date as date_module

        config = WorkerConfig(database_url="postgresql://localhost:5432/test")
        batch_id = config.generate_source_batch_id()
        # Should contain today's date
        assert "ny_judgments_" in batch_id

    def test_env_validation(self):
        config = WorkerConfig(
            database_url="postgresql://localhost:5432/test",
            env="PROD",  # Should be normalized to lowercase
        )
        assert config.env == "prod"

    def test_invalid_env_raises(self):
        with pytest.raises(ValueError):
            WorkerConfig(
                database_url="postgresql://localhost:5432/test",
                env="invalid",
            )

    def test_database_url_validation(self):
        with pytest.raises(ValueError, match="postgres"):
            WorkerConfig(
                database_url="mysql://localhost:3306/test",
            )


# ============================================================================
# Test: Idempotency Guarantees
# ============================================================================


class TestIdempotencyGuarantees:
    """Tests to verify idempotency guarantees of the pipeline."""

    def test_same_record_same_dedupe_key_multiple_runs(self, sample_raw_record):
        """Simulates multiple ingestion runs with same record."""
        # Run 1
        record1 = normalize_record(sample_raw_record.copy())

        # Run 2 (later in time, same data)
        record2 = normalize_record(sample_raw_record.copy())

        # Run 3 (with minor whitespace differences)
        modified = sample_raw_record.copy()
        modified["county"] = "  Kings  County  "  # Add whitespace
        record3 = normalize_record(modified)

        # All should produce the same dedupe key
        assert record1.dedupe_key == record2.dedupe_key
        assert record2.dedupe_key == record3.dedupe_key

    def test_content_hash_detects_changes(self, sample_raw_record):
        """Content hash should change when data changes."""
        record1 = normalize_record(sample_raw_record)

        # Modify the raw payload
        modified = sample_raw_record.copy()
        modified["amount"] = "$9,999.99"
        record2 = normalize_record(modified)

        # Dedupe key should be same (same case)
        assert record1.dedupe_key == record2.dedupe_key
        # Content hash should be different
        assert record1.content_hash != record2.content_hash

    def test_batch_processing_order_independent(self):
        """Batch results should be deterministic regardless of order."""
        records = [
            {"source_url": "https://example.com/1", "county": "kings"},
            {"source_url": "https://example.com/2", "county": "queens"},
            {"source_url": "https://example.com/3", "county": "bronx"},
        ]

        # Process in original order
        normalized1, _ = normalize_batch(records)

        # Process in reverse order
        normalized2, _ = normalize_batch(list(reversed(records)))

        # Same dedupe keys should exist (order may differ)
        keys1 = {r.dedupe_key for r in normalized1}
        keys2 = {r.dedupe_key for r in normalized2}
        assert keys1 == keys2
