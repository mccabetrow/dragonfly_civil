"""
backend/ingest/intake_csv.py
=============================
Idempotent CSV-based plaintiff ingestion with full audit trail.

This module implements the "Plaintiff Intake Moat" - a system that ensures:
1. Same file imported twice = no duplicates (batch-level idempotency)
2. Same plaintiff in different files = deduplicated (row-level idempotency)
3. Every import is fully auditable (ingest.import_runs + ingest.plaintiffs_raw)
4. Every INSERT uses ON CONFLICT DO NOTHING semantics

Usage:
    from backend.ingest.intake_csv import PlaintiffIntakePipeline

    pipeline = PlaintiffIntakePipeline(db_url)
    result = await pipeline.import_csv(
        filepath="data_in/plaintiffs.csv",
        source_system="simplicity",
    )
    print(result.summary())

CLI:
    python -m backend.ingest.intake_csv --file data.csv --source simplicity

Design:
    1. Compute SHA-256 hash of the file
    2. Attempt INSERT into ingest.import_runs with ON CONFLICT DO NOTHING
    3. If row inserted (affected=1), parse and process CSV
    4. If row not inserted (affected=0), return "duplicate batch" result
    5. Each row gets a deterministic dedupe_key
    6. Bulk INSERT with ON CONFLICT DO NOTHING
    7. Count inserted vs skipped rows
    8. Update import_run with final stats
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import logging
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore

# Local imports - graceful fallback for standalone testing
try:
    from src.supabase_client import get_supabase_db_url, get_supabase_env
except ImportError:

    def get_supabase_env() -> str:
        return os.environ.get("SUPABASE_MODE", "dev")

    def get_supabase_db_url(env: str = "dev") -> str:
        env_var = f"SUPABASE_DB_URL_{env.upper()}"
        url = os.environ.get(env_var) or os.environ.get("SUPABASE_DB_URL")
        if not url:
            raise RuntimeError(f"No database URL found. Set {env_var} or SUPABASE_DB_URL")
        return url


logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Canonical CSV headers (case-insensitive matching)
CANONICAL_HEADERS = {
    "plaintiffname": "plaintiff_name",
    "plaintiff_name": "plaintiff_name",
    "name": "plaintiff_name",
    "firmname": "firm_name",
    "firm_name": "firm_name",
    "firm": "firm_name",
    "shortname": "short_name",
    "short_name": "short_name",
    "contactname": "contact_name",
    "contact_name": "contact_name",
    "contactemail": "contact_email",
    "contact_email": "contact_email",
    "email": "contact_email",
    "contactphone": "contact_phone",
    "contact_phone": "contact_phone",
    "phone": "contact_phone",
    "contactaddress": "contact_address",
    "contact_address": "contact_address",
    "address": "contact_address",
    "sourcereference": "source_reference",
    "source_reference": "source_reference",
    "external_id": "source_reference",
    "externalid": "source_reference",
}

REQUIRED_COLUMNS = ["plaintiff_name"]


# =============================================================================
# Data Classes
# =============================================================================


@dataclass(slots=True)
class PlaintiffRow:
    """Parsed and normalized plaintiff row from CSV."""

    row_index: int
    plaintiff_name: str
    plaintiff_name_normalized: str
    firm_name: Optional[str] = None
    short_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_address: Optional[str] = None
    source_reference: Optional[str] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    dedupe_key: str = ""
    error: Optional[str] = None


@dataclass(slots=True)
class ImportResult:
    """Result of a CSV import operation."""

    import_run_id: str
    source_system: str
    source_batch_id: str
    file_hash: str
    filename: str

    # Status
    status: str = "pending"
    is_duplicate_batch: bool = False

    # Row counts
    rows_fetched: int = 0
    rows_inserted: int = 0
    rows_skipped: int = 0
    rows_errored: int = 0

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Errors
    error_message: Optional[str] = None
    errored_rows: List[Tuple[int, str]] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable summary of the import."""
        if self.is_duplicate_batch:
            return (
                f"DUPLICATE BATCH: File '{self.filename}' with hash {self.file_hash[:16]}... "
                f"has already been imported. No action taken."
            )

        duration = ""
        if self.started_at and self.completed_at:
            delta = (self.completed_at - self.started_at).total_seconds()
            duration = f" in {delta:.2f}s"

        return (
            f"Import {self.status.upper()}{duration}: "
            f"{self.rows_fetched} fetched, "
            f"{self.rows_inserted} inserted, "
            f"{self.rows_skipped} skipped, "
            f"{self.rows_errored} errored"
        )


# =============================================================================
# Helper Functions
# =============================================================================


def compute_file_hash(content: bytes) -> str:
    """Compute SHA-256 hash of file content."""
    return hashlib.sha256(content).hexdigest()


def compute_file_hash_from_path(filepath: Path) -> str:
    """Compute SHA-256 hash of file at path."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def normalize_name(name: str) -> str:
    """Normalize a name: lowercase, collapse whitespace."""
    if not name:
        return ""
    return re.sub(r"\s+", " ", name.lower().strip())


def normalize_email(email: Optional[str]) -> Optional[str]:
    """Normalize an email: lowercase, strip."""
    if not email:
        return None
    cleaned = email.lower().strip()
    return cleaned if cleaned else None


def compute_dedupe_key(source_system: str, name: str, email: Optional[str] = None) -> str:
    """
    Compute deterministic dedupe key for a plaintiff record.

    Formula: SHA-256(source_system|normalized_name|normalized_email)
    """
    normalized_name = normalize_name(name)
    normalized_email = normalize_email(email) or ""
    composite = f"{source_system}|{normalized_name}|{normalized_email}"
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()


def map_headers(raw_headers: List[str]) -> Dict[str, str]:
    """Map raw CSV headers to canonical column names."""
    mapping = {}
    for raw in raw_headers:
        normalized = raw.lower().strip().replace(" ", "").replace("-", "").replace("_", "")
        # Also try with underscores
        with_underscores = raw.lower().strip().replace(" ", "_").replace("-", "_")

        if normalized in CANONICAL_HEADERS:
            mapping[raw] = CANONICAL_HEADERS[normalized]
        elif with_underscores in CANONICAL_HEADERS:
            mapping[raw] = CANONICAL_HEADERS[with_underscores]
        else:
            # Keep original for raw_payload
            mapping[raw] = None

    return mapping


def sanitize_for_log(value: str, max_len: int = 100) -> str:
    """Sanitize a value for logging (no secrets, truncated)."""
    if not value:
        return ""
    # Remove potential secrets (patterns that look like SSN, CC, etc.)
    sanitized = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED-SSN]", value)
    sanitized = re.sub(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b", "[REDACTED-CC]", sanitized)
    if len(sanitized) > max_len:
        return sanitized[:max_len] + "..."
    return sanitized


# =============================================================================
# CSV Parser
# =============================================================================


@dataclass(slots=True)
class ParseResult:
    """Result of CSV parsing."""

    rows: List[PlaintiffRow]
    headers: List[str]
    header_mapping: Dict[str, Optional[str]]
    errors: List[Tuple[int, str]]

    @property
    def valid_rows(self) -> List[PlaintiffRow]:
        return [r for r in self.rows if r.error is None]

    @property
    def errored_rows(self) -> List[PlaintiffRow]:
        return [r for r in self.rows if r.error is not None]


def parse_csv(
    filepath: Path,
    source_system: str,
    encoding: str = "utf-8",
) -> ParseResult:
    """
    Parse a CSV file into PlaintiffRow records.

    Args:
        filepath: Path to the CSV file
        source_system: Source system identifier
        encoding: File encoding (default utf-8)

    Returns:
        ParseResult with rows and any parsing errors
    """
    rows: List[PlaintiffRow] = []
    errors: List[Tuple[int, str]] = []

    with open(filepath, "r", encoding=encoding, newline="") as f:
        # Sniff dialect
        sample = f.read(8192)
        f.seek(0)

        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        except csv.Error:
            dialect = csv.excel  # type: ignore

        reader = csv.DictReader(f, dialect=dialect)
        headers = reader.fieldnames or []
        header_mapping = map_headers(headers)

        # Validate required columns
        mapped_cols = set(v for v in header_mapping.values() if v)
        missing = set(REQUIRED_COLUMNS) - mapped_cols
        if missing:
            raise ValueError(
                f"Missing required columns: {missing}. Found: {list(header_mapping.keys())}"
            )

        for row_idx, row in enumerate(reader):
            try:
                parsed = _parse_row(row_idx, row, header_mapping, source_system)
                rows.append(parsed)
            except Exception as e:
                errors.append((row_idx, str(e)))
                # Create error row for tracking
                rows.append(
                    PlaintiffRow(
                        row_index=row_idx,
                        plaintiff_name="[PARSE_ERROR]",
                        plaintiff_name_normalized="",
                        raw_payload=dict(row),
                        error=str(e),
                    )
                )

    return ParseResult(
        rows=rows,
        headers=headers,
        header_mapping=header_mapping,
        errors=errors,
    )


def _parse_row(
    row_idx: int,
    row: Dict[str, str],
    header_mapping: Dict[str, Optional[str]],
    source_system: str,
) -> PlaintiffRow:
    """Parse a single CSV row into a PlaintiffRow."""
    # Map columns
    mapped: Dict[str, Any] = {}
    for raw_col, canonical_col in header_mapping.items():
        value = row.get(raw_col, "").strip()
        if canonical_col and value:
            mapped[canonical_col] = value

    # Validate required fields
    plaintiff_name = mapped.get("plaintiff_name")
    if not plaintiff_name:
        raise ValueError("Missing or empty plaintiff_name")

    # Normalize
    plaintiff_name_normalized = normalize_name(plaintiff_name)
    contact_email = normalize_email(mapped.get("contact_email"))

    # Compute dedupe key
    dedupe_key = compute_dedupe_key(source_system, plaintiff_name, contact_email)

    return PlaintiffRow(
        row_index=row_idx,
        plaintiff_name=plaintiff_name,
        plaintiff_name_normalized=plaintiff_name_normalized,
        firm_name=mapped.get("firm_name"),
        short_name=mapped.get("short_name"),
        contact_name=mapped.get("contact_name"),
        contact_email=contact_email,
        contact_phone=mapped.get("contact_phone"),
        contact_address=mapped.get("contact_address"),
        source_reference=mapped.get("source_reference"),
        raw_payload=dict(row),  # Original row data
        dedupe_key=dedupe_key,
    )


# =============================================================================
# Plaintiff Intake Pipeline
# =============================================================================


class PlaintiffIntakePipeline:
    """
    Idempotent plaintiff intake pipeline.

    Implements the "Plaintiff Intake Moat" pattern:
    1. Batch-level idempotency via import_runs unique constraint
    2. Row-level idempotency via plaintiffs_raw dedupe_key
    3. All INSERTs use ON CONFLICT DO NOTHING
    """

    def __init__(
        self,
        db_url: Optional[str] = None,
        batch_size: int = 100,
    ):
        """
        Initialize the pipeline.

        Args:
            db_url: Database connection URL. If None, uses get_supabase_db_url().
            batch_size: Number of rows to insert in each batch.
        """
        if psycopg is None:
            raise ImportError("psycopg is required. Install with: pip install psycopg[binary]")

        self._db_url = db_url
        self._batch_size = batch_size

    @property
    def db_url(self) -> str:
        if self._db_url:
            return self._db_url
        env = get_supabase_env()
        return get_supabase_db_url(env)

    def import_csv(
        self,
        filepath: str | Path,
        source_system: str,
        source_batch_id: Optional[str] = None,
        import_kind: str = "plaintiff",
        dry_run: bool = False,
    ) -> ImportResult:
        """
        Import a CSV file with full idempotency guarantees.

        Args:
            filepath: Path to the CSV file
            source_system: Source system identifier (e.g., 'simplicity', 'jbi')
            source_batch_id: Optional batch ID. Defaults to filename.
            import_kind: Type of import (default 'plaintiff')
            dry_run: If True, parse but don't write to database

        Returns:
            ImportResult with counts and status
        """
        filepath = Path(filepath)

        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        # Compute file hash for idempotency
        file_hash = compute_file_hash_from_path(filepath)
        filename = filepath.name
        batch_id = source_batch_id or filename

        logger.info(
            "[intake] Starting import: file=%s source=%s hash=%s",
            filename,
            source_system,
            file_hash[:16],
        )

        # Create result object
        result = ImportResult(
            import_run_id="",  # Will be set after claim
            source_system=source_system,
            source_batch_id=batch_id,
            file_hash=file_hash,
            filename=filename,
            started_at=datetime.utcnow(),
        )

        if dry_run:
            return self._dry_run_import(filepath, source_system, result)

        return self._execute_import(
            filepath, source_system, batch_id, file_hash, import_kind, result
        )

    def _dry_run_import(
        self,
        filepath: Path,
        source_system: str,
        result: ImportResult,
    ) -> ImportResult:
        """Execute a dry run (parse only, no database writes)."""
        try:
            parsed = parse_csv(filepath, source_system)
            result.rows_fetched = len(parsed.rows)
            result.rows_errored = len(parsed.errored_rows)
            result.rows_inserted = len(parsed.valid_rows)  # Would be inserted
            result.status = "dry_run"
            result.completed_at = datetime.utcnow()

            logger.info("[intake] Dry run complete: %s", result.summary())

        except Exception as e:
            result.status = "failed"
            result.error_message = str(e)
            result.completed_at = datetime.utcnow()
            logger.error("[intake] Dry run failed: %s", e)

        return result

    def _execute_import(
        self,
        filepath: Path,
        source_system: str,
        batch_id: str,
        file_hash: str,
        import_kind: str,
        result: ImportResult,
    ) -> ImportResult:
        """Execute the actual import with database writes."""
        with psycopg.connect(self.db_url) as conn:
            # Step 1: Claim the import run (atomic)
            run_id, is_duplicate = self._claim_import_run(
                conn, source_system, batch_id, file_hash, filepath.name, import_kind
            )

            if is_duplicate:
                result.is_duplicate_batch = True
                result.status = "skipped"
                result.completed_at = datetime.utcnow()
                logger.info("[intake] Duplicate batch, skipping: %s", result.summary())
                return result

            result.import_run_id = str(run_id)

            try:
                # Step 2: Parse CSV
                parsed = parse_csv(filepath, source_system)
                result.rows_fetched = len(parsed.rows)
                result.rows_errored = len(parsed.errored_rows)

                # Step 3: Insert rows with ON CONFLICT DO NOTHING
                inserted, skipped = self._insert_rows(
                    conn, run_id, source_system, parsed.valid_rows
                )
                result.rows_inserted = inserted
                result.rows_skipped = skipped

                # Step 4: Update import run with final stats
                self._complete_import_run(conn, run_id, result)
                result.status = "completed"
                result.completed_at = datetime.utcnow()

                conn.commit()
                logger.info("[intake] Import complete: %s", result.summary())

            except Exception as e:
                conn.rollback()
                result.status = "failed"
                result.error_message = str(e)
                result.completed_at = datetime.utcnow()

                # Mark import run as failed
                self._fail_import_run(conn, run_id, str(e))
                conn.commit()

                logger.error("[intake] Import failed: %s", e)
                raise

        return result

    def _claim_import_run(
        self,
        conn: psycopg.Connection,
        source_system: str,
        batch_id: str,
        file_hash: str,
        filename: str,
        import_kind: str,
    ) -> Tuple[uuid.UUID, bool]:
        """
        Claim an import run atomically via RPC.

        Uses ingest.claim_import_run() stored procedure for concurrency-safe claiming.
        Returns (run_id, is_duplicate).
        """
        with conn.cursor() as cur:
            # Call the RPC for atomic claim
            cur.execute(
                """
                SELECT run_id, claim_status, existing_run_id, existing_status
                FROM ingest.claim_import_run(%s, %s, %s, %s, %s)
            """,
                (source_system, batch_id, file_hash, filename, import_kind),
            )

            row = cur.fetchone()

            if row is None:
                # Should never happen - RPC always returns a row
                raise RuntimeError("claim_import_run RPC returned no result")

            run_id, claim_status, existing_run_id, existing_status = row

            if claim_status == "claimed":
                logger.debug(
                    "[intake] Claimed new import run: run_id=%s",
                    run_id,
                )
                return run_id, False
            else:
                # Duplicate - return existing run info
                logger.info(
                    "[intake] Duplicate batch detected: existing_run=%s status=%s",
                    existing_run_id,
                    existing_status,
                )
                return existing_run_id, True

    def _insert_rows(
        self,
        conn: psycopg.Connection,
        run_id: uuid.UUID,
        source_system: str,
        rows: List[PlaintiffRow],
    ) -> Tuple[int, int]:
        """
        Insert rows with ON CONFLICT DO NOTHING.

        Returns (inserted_count, skipped_count).
        """
        if not rows:
            return 0, 0

        inserted = 0
        skipped = 0

        with conn.cursor() as cur:
            for batch_start in range(0, len(rows), self._batch_size):
                batch = rows[batch_start : batch_start + self._batch_size]

                # Build VALUES clause
                values = []
                params: List[Any] = []

                for row in batch:
                    values.append(
                        """(
                        gen_random_uuid(),
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )"""
                    )
                    params.extend(
                        [
                            str(run_id),
                            row.row_index,
                            row.plaintiff_name,
                            row.firm_name,
                            row.short_name,
                            row.contact_name,
                            row.contact_email,
                            row.contact_phone,
                            row.contact_address,
                            source_system,
                            row.source_reference,
                            psycopg.types.json.Jsonb(row.raw_payload),
                            row.dedupe_key,
                        ]
                    )

                sql = f"""
                    INSERT INTO ingest.plaintiffs_raw (
                        id,
                        import_run_id,
                        row_index,
                        plaintiff_name,
                        firm_name,
                        short_name,
                        contact_name,
                        contact_email,
                        contact_phone,
                        contact_address,
                        source_system,
                        source_reference,
                        raw_payload,
                        dedupe_key
                    ) VALUES {", ".join(values)}
                    ON CONFLICT (dedupe_key) DO NOTHING
                """

                cur.execute(sql, params)
                batch_inserted = cur.rowcount
                batch_skipped = len(batch) - batch_inserted

                inserted += batch_inserted
                skipped += batch_skipped

                logger.debug(
                    "[intake] Batch %d-%d: inserted=%d skipped=%d",
                    batch_start,
                    batch_start + len(batch),
                    batch_inserted,
                    batch_skipped,
                )

        return inserted, skipped

    def _complete_import_run(
        self,
        conn: psycopg.Connection,
        run_id: uuid.UUID,
        result: ImportResult,
    ) -> None:
        """Update import run with completion stats."""
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingest.import_runs
                SET
                    status = 'completed',
                    completed_at = now(),
                    rows_fetched = %s,
                    rows_inserted = %s,
                    rows_skipped = %s,
                    rows_errored = %s
                WHERE id = %s
            """,
                (
                    result.rows_fetched,
                    result.rows_inserted,
                    result.rows_skipped,
                    result.rows_errored,
                    str(run_id),
                ),
            )

    def _fail_import_run(
        self,
        conn: psycopg.Connection,
        run_id: uuid.UUID,
        error_message: str,
    ) -> None:
        """Mark import run as failed."""
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingest.import_runs
                SET
                    status = 'failed',
                    completed_at = now(),
                    error_details = %s
                WHERE id = %s
            """,
                (
                    psycopg.types.json.Jsonb({"message": error_message}),
                    str(run_id),
                ),
            )


# =============================================================================
# CLI
# =============================================================================


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Idempotent plaintiff CSV importer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Dry run (no database writes)
    python -m backend.ingest.intake_csv --file data.csv --source simplicity --dry-run

    # Actual import
    python -m backend.ingest.intake_csv --file data.csv --source simplicity

    # With custom batch ID
    python -m backend.ingest.intake_csv --file data.csv --source jbi --batch-id batch-001
""",
    )
    parser.add_argument(
        "--file",
        "-f",
        required=True,
        help="Path to the CSV file to import",
    )
    parser.add_argument(
        "--source",
        "-s",
        required=True,
        help="Source system identifier (e.g., 'simplicity', 'jbi', 'manual')",
    )
    parser.add_argument(
        "--batch-id",
        help="Optional batch ID. Defaults to filename.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate without writing to database",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args(argv)

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        pipeline = PlaintiffIntakePipeline()
        result = pipeline.import_csv(
            filepath=args.file,
            source_system=args.source,
            source_batch_id=args.batch_id,
            dry_run=args.dry_run,
        )

        print("\n" + "=" * 60)
        print(result.summary())
        print("=" * 60)

        if result.status == "failed":
            print(f"\nError: {result.error_message}")
            return 1

        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        logger.exception("Import failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
