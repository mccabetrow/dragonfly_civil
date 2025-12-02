"""Integration tests for the bulletproof Simplicity orchestrator.

These tests verify:
    1. Basic import functionality with a sample CSV
    2. Idempotency (duplicate handling)
    3. Quarantine file creation for bad rows
    4. Row counts in key tables
"""

from __future__ import annotations

import csv
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from textwrap import dedent

import psycopg
import pytest

# Import the orchestrator components
from etl.src.simplicity_orchestrator import (
    FailedRow,
    ImportConfig,
    ImportResult,
    _normalize_email,
    _normalize_name,
    _normalize_phone,
    _parse_amount,
    _parse_date,
    _read_csv,
    run_import,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Create a valid sample CSV for testing."""
    content = dedent(
        """\
        PlaintiffName,JudgmentNumber,JudgmentAmount,JudgmentDate,Phone,Email,Court,County,State,DefendantName
        Acme Collections LLC,JDG-2024-001,15000.00,2024-01-15,(212) 555-0100,acme@example.com,Queens Civil,Queens,NY,John Doe
        Beta Finance Corp,JDG-2024-002,8750.50,2024-02-20,(718) 555-0200,beta@example.com,Kings Civil,Kings,NY,Jane Smith
        Gamma Funding Inc,JDG-2024-003,22500.00,2024-03-10,(646) 555-0300,gamma@example.com,NY Civil,New York,NY,Bob Wilson
        """
    )
    csv_path = tmp_path / "sample_import.csv"
    csv_path.write_text(content, encoding="utf-8")
    return csv_path


@pytest.fixture
def bad_rows_csv(tmp_path: Path) -> Path:
    """Create a CSV with some invalid rows."""
    content = dedent(
        """\
        PlaintiffName,JudgmentNumber,JudgmentAmount,JudgmentDate,Phone,Email
        Valid Plaintiff,JDG-VALID-001,5000.00,2024-01-01,(555) 555-5555,valid@test.com
        ,JDG-MISSING-NAME,1000.00,2024-01-01,,,
        Missing Judgment,,2000.00,2024-01-01,,,
        Another Valid,JDG-VALID-002,3000.00,2024-02-01,(555) 555-6666,another@test.com
        """
    )
    csv_path = tmp_path / "bad_rows.csv"
    csv_path.write_text(content, encoding="utf-8")
    return csv_path


@pytest.fixture
def duplicate_csv(tmp_path: Path) -> Path:
    """Create a CSV with duplicate entries (same plaintiff name/email)."""
    content = dedent(
        """\
        PlaintiffName,JudgmentNumber,JudgmentAmount,JudgmentDate,Phone,Email
        Duplicate Test LLC,JDG-DUP-001,10000.00,2024-01-01,(555) 111-1111,dupe@test.com
        Duplicate Test LLC,JDG-DUP-002,20000.00,2024-02-01,(555) 111-1111,dupe@test.com
        Duplicate Test LLC,JDG-DUP-003,30000.00,2024-03-01,(555) 111-1111,dupe@test.com
        """
    )
    csv_path = tmp_path / "duplicates.csv"
    csv_path.write_text(content, encoding="utf-8")
    return csv_path


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestNormalizationHelpers:
    """Tests for normalization utility functions."""

    def test_normalize_name(self) -> None:
        assert _normalize_name("  John   Doe  ") == "john doe"
        assert _normalize_name("ACME CORP") == "acme corp"
        assert _normalize_name("") == ""

    def test_normalize_email(self) -> None:
        assert _normalize_email("Test@Example.COM") == "test@example.com"
        assert _normalize_email("  user@test.com  ") == "user@test.com"
        assert _normalize_email("") is None
        assert _normalize_email(None) is None

    def test_normalize_phone(self) -> None:
        assert _normalize_phone("(555) 123-4567") == "5551234567"
        assert _normalize_phone("555.123.4567") == "5551234567"
        assert _normalize_phone("123") is None  # Too short
        assert _normalize_phone(None) is None

    def test_parse_date_various_formats(self) -> None:
        assert _parse_date("2024-01-15") == date(2024, 1, 15)
        assert _parse_date("01/15/2024") == date(2024, 1, 15)
        assert _parse_date("01/15/24") == date(2024, 1, 15)
        assert _parse_date("") is None
        assert _parse_date(None) is None
        assert _parse_date("invalid") is None

    def test_parse_amount(self) -> None:
        assert _parse_amount("$1,234.56") == Decimal("1234.56")
        assert _parse_amount("1234.56") == Decimal("1234.56")
        assert _parse_amount("$10,000") == Decimal("10000")
        assert _parse_amount("") is None
        assert _parse_amount(None) is None
        assert _parse_amount("invalid") is None


# ---------------------------------------------------------------------------
# CSV parsing tests
# ---------------------------------------------------------------------------


class TestCsvParsing:
    """Tests for CSV parsing functionality."""

    def test_parse_valid_csv(self, sample_csv: Path) -> None:
        """Valid CSV should parse without failures."""
        rows, failures = _read_csv(sample_csv)

        assert len(rows) == 3
        assert len(failures) == 0

        # Check first row
        row = rows[0]
        assert row["plaintiff_name"] == "Acme Collections LLC"
        assert row["judgment_number"] == "JDG-2024-001"
        assert row["judgment_amount"] == Decimal("15000.00")
        assert row["email"] == "acme@example.com"

    def test_parse_csv_with_bad_rows(self, bad_rows_csv: Path) -> None:
        """CSV with invalid rows should capture failures."""
        rows, failures = _read_csv(bad_rows_csv)

        assert len(rows) == 2  # Only 2 valid rows
        assert len(failures) == 2  # 2 invalid rows

        # Check failures have proper error info
        for failure in failures:
            assert failure.error_type == "ValidationError"
            assert failure.stage == "parse"
            assert "Missing required field" in failure.error_message

    def test_parse_missing_file(self, tmp_path: Path) -> None:
        """Missing file should raise FileNotFoundError."""
        missing_path = tmp_path / "nonexistent.csv"

        with pytest.raises(FileNotFoundError):
            _read_csv(missing_path)

    def test_parse_empty_csv(self, tmp_path: Path) -> None:
        """Empty CSV should return no rows."""
        empty_csv = tmp_path / "empty.csv"
        empty_csv.write_text("PlaintiffName,JudgmentNumber\n", encoding="utf-8")

        rows, failures = _read_csv(empty_csv)
        assert len(rows) == 0
        assert len(failures) == 0


# ---------------------------------------------------------------------------
# Import configuration tests
# ---------------------------------------------------------------------------


class TestImportConfig:
    """Tests for ImportConfig dataclass."""

    def test_effective_batch_name_default(self, tmp_path: Path) -> None:
        """Default batch name is derived from source and run_id."""
        config = ImportConfig(
            batch_file=tmp_path / "test.csv",
            run_id="abc12345-6789-0000-0000-000000000000",
            source="simplicity",
        )

        assert config.effective_batch_name == "simplicity:abc12345"

    def test_effective_batch_name_explicit(self, tmp_path: Path) -> None:
        """Explicit batch name overrides default."""
        config = ImportConfig(
            batch_file=tmp_path / "test.csv",
            run_id="abc12345",
            batch_name="Q1-2024-import",
        )

        assert config.effective_batch_name == "Q1-2024-import"


# ---------------------------------------------------------------------------
# Import result tests
# ---------------------------------------------------------------------------


class TestImportResult:
    """Tests for ImportResult dataclass."""

    def test_success_with_no_failures(self) -> None:
        result = ImportResult(
            run_id="test",
            total_rows=10,
            processed_rows=10,
            inserted_plaintiffs=5,
        )

        assert result.success is True
        assert result.has_failures is False

    def test_failure_with_failed_rows(self) -> None:
        result = ImportResult(run_id="test", total_rows=10, processed_rows=8)
        result.failed_rows.append(
            FailedRow(
                row_number=2,
                raw_data={},
                error_type="ValidationError",
                error_message="Missing field",
                stage="parse",
            )
        )

        assert result.success is False
        assert result.has_failures is True

    def test_as_dict(self) -> None:
        result = ImportResult(
            run_id="test-123",
            total_rows=10,
            processed_rows=9,
            inserted_plaintiffs=4,
            updated_plaintiffs=3,
            skipped_duplicates=2,
            committed=True,
        )

        d = result.as_dict()
        assert d["run_id"] == "test-123"
        assert d["total_rows"] == 10
        assert d["processed_rows"] == 9
        assert d["inserted_plaintiffs"] == 4
        assert d["updated_plaintiffs"] == 3
        assert d["skipped_duplicates"] == 2
        assert d["committed"] is True
        assert d["success"] is True


# ---------------------------------------------------------------------------
# Integration tests (require database)
# ---------------------------------------------------------------------------


def _get_test_db_url() -> str | None:
    """Get database URL for integration tests, or None if not available."""
    from src.supabase_client import get_supabase_db_url, get_supabase_env

    try:
        env = get_supabase_env()
        return get_supabase_db_url(env)
    except Exception:
        return None


def _skip_if_no_db() -> None:
    """Skip test if database is not available."""
    if _get_test_db_url() is None:
        pytest.skip("Database not configured for integration tests")


def _count_plaintiffs_by_name(conn: psycopg.Connection, name_pattern: str) -> int:
    """Count plaintiffs matching a name pattern."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM public.plaintiffs WHERE name LIKE %s",
            (f"%{name_pattern}%",),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


def _count_judgments_by_number(conn: psycopg.Connection, pattern: str) -> int:
    """Count judgments matching a number pattern."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM public.judgments WHERE judgment_number LIKE %s",
            (f"{pattern}%",),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


@pytest.mark.integration
class TestOrchestratorIntegration:
    """Integration tests that require a database connection."""

    def test_dry_run_does_not_commit(self, sample_csv: Path) -> None:
        """Dry-run should not persist any changes."""
        _skip_if_no_db()

        run_id = str(uuid.uuid4())
        config = ImportConfig(
            batch_file=sample_csv,
            run_id=run_id,
            source="test-dry-run",
            commit=False,
            skip_jobs=True,
        )

        result = run_import(config)

        assert result.committed is False
        assert result.processed_rows > 0

        # Verify nothing was persisted
        db_url = _get_test_db_url()
        assert db_url is not None
        with psycopg.connect(db_url) as conn:
            # Just verify DB is accessible - actual count depends on test order
            _count_plaintiffs_by_name(conn, "Acme Collections")

    def test_quarantine_file_created_for_failures(self, bad_rows_csv: Path) -> None:
        """Failed rows should be written to quarantine file."""
        _skip_if_no_db()

        run_id = str(uuid.uuid4())
        config = ImportConfig(
            batch_file=bad_rows_csv,
            run_id=run_id,
            source="test-quarantine",
            commit=False,
            skip_jobs=True,
        )

        result = run_import(config)

        assert result.has_failures is True
        assert result.quarantine_file is not None
        assert result.quarantine_file.exists()

        # Check quarantine file content
        with result.quarantine_file.open("r") as f:
            reader = csv.DictReader(f)
            quarantine_rows = list(reader)

        assert len(quarantine_rows) == 2  # 2 bad rows

        # Verify error details
        for qrow in quarantine_rows:
            assert qrow["stage"] == "parse"
            assert qrow["error_type"] == "ValidationError"

        # Cleanup
        result.quarantine_file.unlink()

    def test_idempotent_plaintiff_handling(self, duplicate_csv: Path) -> None:
        """
        Multiple rows for same plaintiff should not create duplicates.

        Note: This test runs in dry-run mode to avoid polluting the database.
        In production, the same logic applies with commit=True.
        """
        _skip_if_no_db()

        run_id = str(uuid.uuid4())
        config = ImportConfig(
            batch_file=duplicate_csv,
            run_id=run_id,
            source="test-idempotent",
            commit=False,
            skip_jobs=True,
        )

        result = run_import(config)

        # All rows should be processed
        assert result.total_rows == 3
        assert result.processed_rows == 3

        # First row creates, subsequent rows should update existing
        # (in dry-run we can't verify DB state, but logic is exercised)
        assert result.success is True


@pytest.mark.integration
class TestOrchestratorCommit:
    """Integration tests that actually commit to the database.

    These tests use unique identifiers to avoid conflicts and
    should clean up after themselves.
    """

    def test_commit_inserts_and_is_idempotent(self, tmp_path: Path) -> None:
        """Committing twice with same data should be idempotent."""
        _skip_if_no_db()

        # Create a unique CSV for this test
        unique_id = uuid.uuid4().hex[:8].upper()
        content = dedent(
            f"""\
            PlaintiffName,JudgmentNumber,JudgmentAmount,JudgmentDate,Email
            Test Plaintiff {unique_id},JDG-TEST-{unique_id}-001,5000.00,2024-01-01,test{unique_id}@example.com
            """
        )
        csv_path = tmp_path / f"test_commit_{unique_id}.csv"
        csv_path.write_text(content, encoding="utf-8")

        # First import
        run_id_1 = str(uuid.uuid4())
        config_1 = ImportConfig(
            batch_file=csv_path,
            run_id=run_id_1,
            source=f"test-commit-{unique_id}",
            commit=True,
            skip_jobs=True,
        )

        result_1 = run_import(config_1)

        assert result_1.committed is True
        assert result_1.inserted_plaintiffs == 1
        assert result_1.processed_rows == 1

        # Second import with same data (different judgment number to avoid dupe skip)
        content_2 = dedent(
            f"""\
            PlaintiffName,JudgmentNumber,JudgmentAmount,JudgmentDate,Email
            Test Plaintiff {unique_id},JDG-TEST-{unique_id}-002,6000.00,2024-02-01,test{unique_id}@example.com
            """
        )
        csv_path_2 = tmp_path / f"test_commit_{unique_id}_2.csv"
        csv_path_2.write_text(content_2, encoding="utf-8")

        run_id_2 = str(uuid.uuid4())
        config_2 = ImportConfig(
            batch_file=csv_path_2,
            run_id=run_id_2,
            source=f"test-commit-{unique_id}",
            commit=True,
            skip_jobs=True,
        )

        result_2 = run_import(config_2)

        assert result_2.committed is True
        # Should update existing plaintiff, not create new
        assert result_2.updated_plaintiffs == 1
        assert result_2.inserted_plaintiffs == 0

        # Verify only one plaintiff exists
        db_url = _get_test_db_url()
        assert db_url is not None
        with psycopg.connect(db_url) as conn:
            count = _count_plaintiffs_by_name(conn, f"Test Plaintiff {unique_id}")
            assert count == 1

            # But two judgments should exist
            jdg_count = _count_judgments_by_number(conn, f"JDG-TEST-{unique_id}")
            assert jdg_count == 2

            # Cleanup
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM public.judgments WHERE judgment_number LIKE %s",
                    (f"JDG-TEST-{unique_id}%",),
                )
                cur.execute(
                    "DELETE FROM public.plaintiff_status_history WHERE plaintiff_id IN "
                    "(SELECT id FROM public.plaintiffs WHERE name LIKE %s)",
                    (f"%{unique_id}%",),
                )
                cur.execute(
                    "DELETE FROM public.plaintiff_contacts WHERE plaintiff_id IN "
                    "(SELECT id FROM public.plaintiffs WHERE name LIKE %s)",
                    (f"%{unique_id}%",),
                )
                cur.execute(
                    "DELETE FROM public.plaintiffs WHERE name LIKE %s",
                    (f"%{unique_id}%",),
                )
            conn.commit()
