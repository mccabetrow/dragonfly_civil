"""Ingest judgments from Simplicity/Incubator CSV into public.core_judgments.

This script reads CSV files in the typical Simplicity export format and inserts
rows into the ``public.core_judgments`` table (from migration 0200).  Existing
rows (by ``case_index_number``) are skipped rather than overwritten.

Expected CSV columns (case-insensitive header matching):

    PlaintiffName   → original_creditor
    DefendantName   → debtor_name
    CaseNumber      → case_index_number (required, unique key)
    JudgmentAmount  → principal_amount
    JudgmentDate    → judgment_date (ISO or common date formats)
    Court           → court_name
    County          → county

Additional columns (SourceBatch, etc.) are ignored.

Usage:
    # Dry run (default CSV path: ./data/judgments_batch.csv)
    python scripts/ingest_judgments.py --dry-run

    # Ingest from a specific CSV, writing to Supabase
    $env:SUPABASE_MODE='dev'
    python scripts/ingest_judgments.py --csv data_in/simplicity_judgments.csv

Environment Variables:
    SUPABASE_URL                 – Supabase project URL (dev)
    SUPABASE_SERVICE_ROLE_KEY    – Service role key (dev)
    SUPABASE_URL_PROD            – Supabase project URL (prod)
    SUPABASE_SERVICE_ROLE_KEY_PROD – Service role key (prod)
    SUPABASE_MODE                – Target environment (dev|prod)
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional, Sequence

# ---------------------------------------------------------------------------
# Path setup – ensure project root is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.supabase_client import create_supabase_client, get_supabase_env

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_CSV_PATH = Path("./data/judgments_batch.csv")
BATCH_SIZE = 100

# CSV column → DB column mapping (CSV names are normalized to lowercase)
COLUMN_MAP: dict[str, str] = {
    "casenumber": "case_index_number",
    "defendantname": "debtor_name",
    "plaintiffname": "original_creditor",
    "judgmentdate": "judgment_date",
    "judgmentamount": "principal_amount",
    "court": "court_name",
    "county": "county",
}

REQUIRED_CSV_COLUMNS = {"casenumber"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class IngestConfig:
    csv_path: Path
    dry_run: bool
    batch_size: int = BATCH_SIZE


@dataclass
class IngestSummary:
    rows_read: int = 0
    valid_rows: int = 0
    would_insert: int = 0
    would_skip: int = 0
    inserted: int = 0
    skipped: int = 0
    errors: int = 0
    warnings: int = 0
    error_details: list[str] = field(default_factory=list)
    warning_details: list[str] = field(default_factory=list)

    def print_summary(self, dry_run: bool) -> None:
        if dry_run:
            print("\n" + "=" * 50)
            print("            DRY RUN SUMMARY")
            print("=" * 50)
            print(f"{'Metric':<25} {'Count':>10}")
            print("-" * 36)
            print(f"{'total_rows':<25} {self.rows_read:>10}")
            print(f"{'valid_rows':<25} {self.valid_rows:>10}")
            print(f"{'rows_with_errors':<25} {self.errors:>10}")
            print(f"{'rows_with_warnings':<25} {self.warnings:>10}")
            print("-" * 36)
            print(f"{'would_insert':<25} {self.would_insert:>10}")
            print(f"{'would_skip (existing)':<25} {self.would_skip:>10}")
            print("=" * 50)
        else:
            print("\n" + "=" * 50)
            print("            INGEST SUMMARY")
            print("=" * 50)
            print(f"{'Metric':<25} {'Count':>10}")
            print("-" * 36)
            print(f"{'total_rows':<25} {self.rows_read:>10}")
            print(f"{'valid_rows':<25} {self.valid_rows:>10}")
            print(f"{'rows_with_errors':<25} {self.errors:>10}")
            print(f"{'rows_with_warnings':<25} {self.warnings:>10}")
            print("-" * 36)
            print(f"{'inserted':<25} {self.inserted:>10}")
            print(f"{'skipped (existing)':<25} {self.skipped:>10}")
            print("=" * 50)

        # Print warnings first (non-fatal)
        if self.warning_details:
            print("\n⚠️  Warnings (records still processed):")
            for detail in self.warning_details[:10]:
                print(f"    - {detail}")
            if len(self.warning_details) > 10:
                print(f"    ... and {len(self.warning_details) - 10} more warnings")

        # Print errors (fatal for that row)
        if self.error_details:
            print("\n❌ Errors (records skipped):")
            for detail in self.error_details[:10]:
                print(f"    - {detail}")
            if len(self.error_details) > 10:
                print(f"    ... and {len(self.error_details) - 10} more errors")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest judgments from CSV into public.core_judgments table.",
        epilog="Set SUPABASE_MODE=dev|prod and ensure credentials are in env.",
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help=f"Path to the CSV file (default: {DEFAULT_CSV_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse CSV and print summary without writing to Supabase",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Number of rows per insert batch (default: {BATCH_SIZE})",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _clean(value: Any) -> str:
    """Normalize a cell value to a stripped string."""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _parse_amount(raw: Any) -> Optional[float]:
    """Parse a currency/decimal string to a float, or None if empty/invalid."""
    cleaned = _clean(raw)
    if not cleaned:
        return None
    try:
        # Remove currency symbols and commas
        normalized = cleaned.replace("$", "").replace(",", "").replace(" ", "")
        return float(Decimal(normalized))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(raw: Any, row_idx: int = -1) -> tuple[Optional[date], Optional[str]]:
    """Parse a date string to a date object, supporting YYYY-MM-DD and MM/DD/YYYY.

    Returns:
        tuple of (parsed_date, error_message). If parsing succeeds, error is None.
        If parsing fails, date is None and error contains a short description.
    """
    cleaned = _clean(raw)
    if not cleaned:
        return None, None  # Empty is valid (no error)

    # Try ISO format first (YYYY-MM-DD)
    try:
        return date.fromisoformat(cleaned), None
    except ValueError:
        pass

    # Try MM/DD/YYYY explicitly
    try:
        parsed = pd.to_datetime(cleaned, format="%m/%d/%Y", errors="raise")
        return parsed.date(), None
    except (ValueError, TypeError):
        pass

    # Try pandas flexible parsing as fallback
    try:
        parsed = pd.to_datetime(cleaned, errors="coerce")
        if pd.notna(parsed):
            return parsed.date(), None
    except Exception:
        pass

    # Parsing failed – return error message
    row_info = f"row {row_idx}: " if row_idx >= 0 else ""
    return None, f"{row_info}invalid date '{cleaned}'"


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase and strip whitespace from column names."""
    df.columns = df.columns.str.lower().str.strip().str.replace(" ", "")
    return df


def _validate_columns(df: pd.DataFrame) -> list[str]:
    """Check that required columns are present. Return list of missing cols."""
    actual = set(df.columns)
    missing = REQUIRED_CSV_COLUMNS - actual
    return list(missing)


def _map_row_to_judgment(
    row: pd.Series, row_idx: int = -1
) -> tuple[Optional[dict[str, Any]], list[str]]:
    """Transform a CSV row into a core_judgments record dict.

    Returns:
        tuple of (record_dict, list_of_warnings). Record is None if row is invalid.
        Warnings list contains non-fatal parse issues (e.g., unparseable dates).
    """
    warnings: list[str] = []

    case_index_number = _clean(row.get("casenumber", ""))
    if not case_index_number:
        return None, [f"row {row_idx}: missing case_index_number"]

    # Parse date with error tracking
    judgment_date, date_error = _parse_date(row.get("judgmentdate"), row_idx)
    if date_error:
        warnings.append(date_error)

    record: dict[str, Any] = {
        "case_index_number": case_index_number,
        "debtor_name": _clean(row.get("defendantname", "")) or None,
        "original_creditor": _clean(row.get("plaintiffname", "")) or None,
        "judgment_date": judgment_date.isoformat() if judgment_date else None,
        "principal_amount": _parse_amount(row.get("judgmentamount")),
        "court_name": _clean(row.get("court", "")) or None,
        "county": _clean(row.get("county", "")) or None,
    }
    return record, warnings


# ---------------------------------------------------------------------------
# Supabase operations
# ---------------------------------------------------------------------------
def _fetch_existing_case_numbers(client: Any, case_numbers: list[str]) -> set[str]:
    """Query core_judgments for existing case_index_numbers."""
    if not case_numbers:
        return set()

    try:
        response = (
            client.table("core_judgments")
            .select("case_index_number")
            .in_("case_index_number", case_numbers)
            .execute()
        )
        return {r["case_index_number"] for r in response.data}
    except Exception as exc:
        logger.error("Failed to fetch existing case numbers: %s", exc)
        return set()


def _insert_batch(client: Any, records: list[dict[str, Any]]) -> int:
    """Insert a batch of records into core_judgments. Return count inserted."""
    if not records:
        return 0

    try:
        response = client.table("core_judgments").insert(records).execute()
        return len(response.data) if response.data else 0
    except Exception as exc:
        logger.error("Batch insert failed: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# Main ingestion logic
# ---------------------------------------------------------------------------
def ingest_judgments(config: IngestConfig) -> IngestSummary:
    """Read CSV and insert judgments into Supabase (or simulate if dry_run)."""
    summary = IngestSummary()

    # --- Validate CSV file exists ---
    if not config.csv_path.exists():
        logger.error("CSV file not found: %s", config.csv_path)
        summary.errors = 1
        summary.error_details.append(f"File not found: {config.csv_path}")
        return summary

    # --- Read CSV ---
    logger.info("Reading CSV: %s", config.csv_path)
    try:
        df = pd.read_csv(config.csv_path, dtype=str, keep_default_na=False)
    except Exception as exc:
        logger.error("Failed to read CSV: %s", exc)
        summary.errors = 1
        summary.error_details.append(f"CSV read error: {exc}")
        return summary

    df = _normalize_columns(df)
    summary.rows_read = len(df)
    logger.info("Read %d rows from CSV", summary.rows_read)

    # --- Validate required columns ---
    missing_cols = _validate_columns(df)
    if missing_cols:
        msg = f"Missing required CSV columns: {', '.join(missing_cols)}"
        logger.error(msg)
        summary.errors = 1
        summary.error_details.append(msg)
        return summary

    # --- Transform rows ---
    records: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        try:
            record, row_warnings = _map_row_to_judgment(row, idx)

            # Track warnings (non-fatal issues like unparseable dates)
            if row_warnings:
                summary.warnings += 1
                summary.warning_details.extend(row_warnings)
                for warn in row_warnings:
                    logger.warning(warn)

            if record:
                records.append(record)
            else:
                summary.errors += 1
                # Error details already in row_warnings for missing case_index_number
                if row_warnings:
                    summary.error_details.extend(row_warnings)
                else:
                    summary.error_details.append(f"row {idx}: invalid record")
        except Exception as exc:
            summary.errors += 1
            summary.error_details.append(f"row {idx}: {exc}")
            logger.error("row %d: %s", idx, exc)

    summary.valid_rows = len(records)

    if not records:
        logger.warning("No valid records to insert")
        return summary

    logger.info("Transformed %d valid records (%d warnings)", len(records), summary.warnings)

    # --- Connect to Supabase ---
    if not config.dry_run:
        env = get_supabase_env()
        logger.info("Connecting to Supabase (env=%s)", env)
        client = create_supabase_client(env)
    else:
        client = None
        env = get_supabase_env()
        logger.info("DRY RUN mode – will not write to Supabase (env=%s)", env)

    # --- Process in batches ---
    for batch_start in range(0, len(records), config.batch_size):
        batch = records[batch_start : batch_start + config.batch_size]
        batch_case_numbers = [r["case_index_number"] for r in batch]

        if config.dry_run:
            # In dry run, we can't check existing – assume all are new
            # For a more accurate dry run, we'd need to query Supabase
            summary.would_insert += len(batch)
        else:
            # Check which case numbers already exist
            existing = _fetch_existing_case_numbers(client, batch_case_numbers)

            # Filter to only new records
            new_records = [r for r in batch if r["case_index_number"] not in existing]
            skipped_count = len(batch) - len(new_records)
            summary.skipped += skipped_count

            if new_records:
                inserted = _insert_batch(client, new_records)
                summary.inserted += inserted
                if inserted < len(new_records):
                    summary.errors += len(new_records) - inserted

            logger.info(
                "Batch %d-%d: inserted=%d, skipped=%d",
                batch_start,
                batch_start + len(batch),
                len(new_records) if new_records else 0,
                skipped_count,
            )

    # --- Dry run: query for accurate skip count ---
    if config.dry_run and client is None:
        # Try to get existing count for accurate dry-run summary
        try:
            temp_env = get_supabase_env()
            temp_client = create_supabase_client(temp_env)
            all_case_numbers = [r["case_index_number"] for r in records]
            existing = _fetch_existing_case_numbers(temp_client, all_case_numbers)
            summary.would_skip = len(existing)
            summary.would_insert = len(records) - len(existing)
        except Exception:
            # If we can't connect, leave estimates as-is
            pass

    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    config = IngestConfig(
        csv_path=args.csv_path,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
    )

    logger.info(
        "Starting judgment ingestion (csv=%s, dry_run=%s, batch_size=%d)",
        config.csv_path,
        config.dry_run,
        config.batch_size,
    )

    summary = ingest_judgments(config)
    summary.print_summary(config.dry_run)

    # Return non-zero if there were errors
    return 1 if summary.errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
