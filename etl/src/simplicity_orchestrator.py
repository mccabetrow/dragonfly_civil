"""Bulletproof Simplicity plaintiff import orchestrator.

Invoke via:
    .venv\\Scripts\\python.exe -m etl.src.simplicity_orchestrator \\
        --batch-file=data_in/simplicity_sample.csv \\
        --run-id=UUID \\
        [--commit]

Features:
    - Idempotent: Duplicate plaintiffs (same external_id/email/name) update
      existing records rather than creating new ones.
    - Robust: Failed rows are quarantined to `failed_rows_<run_id>.csv`
      with full error detail; no silent data loss.
    - Well-typed: mypy-clean with explicit type annotations.
    - Transactional: Each row is processed in its own savepoint; a failure
      rolls back only that row and continues processing the batch.

Exit codes:
    0 - Success (all rows processed, no failures)
    1 - Partial failure (some rows quarantined)
    2 - Fatal failure (cannot proceed)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Sequence, TypedDict

import psycopg
from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.supabase_client import describe_db_url, get_supabase_db_url, get_supabase_env

__all__ = [
    "ImportConfig",
    "ImportResult",
    "FailedRow",
    "run_import",
    "main",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SOURCE: Final[str] = "simplicity"
QUARANTINE_DIR: Final[str] = "data_error"
MAX_ERROR_DETAIL_LEN: Final[int] = 2000

# Canonical headers we accept (case-insensitive, whitespace-trimmed)
REQUIRED_HEADERS: Final[frozenset[str]] = frozenset({"plaintiffname", "judgmentnumber"})
OPTIONAL_HEADERS: Final[frozenset[str]] = frozenset(
    {
        "leadid",
        "court",
        "indexnumber",
        "judgmentdate",
        "judgmentamount",
        "county",
        "state",
        "plaintiffaddress",
        "phone",
        "email",
        "bestcontactmethod",
        "status",
        "defendantname",
        "filingdate",
        "docketnumber",
        "casenumber",
    }
)


# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------


class ParsedRow(TypedDict, total=False):
    """Typed structure for a parsed CSV row."""

    row_number: int
    lead_id: Optional[str]
    plaintiff_name: str
    judgment_number: str
    case_number: Optional[str]
    docket_number: Optional[str]
    court: Optional[str]
    county: Optional[str]
    state: Optional[str]
    judgment_date: Optional[date]
    filing_date: Optional[date]
    judgment_amount: Optional[Decimal]
    plaintiff_address: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    best_contact_method: Optional[str]
    status: Optional[str]
    defendant_name: Optional[str]
    raw: Dict[str, str]


@dataclass(slots=True)
class FailedRow:
    """A row that could not be imported."""

    row_number: int
    raw_data: Dict[str, str]
    error_type: str
    error_message: str
    stage: str  # "parse", "validate", "insert", "commit"


@dataclass(slots=True)
class ImportConfig:
    """Configuration for an import run."""

    batch_file: Path
    run_id: str
    source: str = DEFAULT_SOURCE
    commit: bool = False
    skip_jobs: bool = False
    batch_name: Optional[str] = None

    @property
    def effective_batch_name(self) -> str:
        return self.batch_name or f"{self.source}:{self.run_id[:8]}"


@dataclass(slots=True)
class ImportResult:
    """Summary of an import run."""

    run_id: str
    total_rows: int = 0
    processed_rows: int = 0
    inserted_plaintiffs: int = 0
    updated_plaintiffs: int = 0
    skipped_duplicates: int = 0
    failed_rows: List[FailedRow] = field(default_factory=list)
    quarantine_file: Optional[Path] = None
    committed: bool = False

    @property
    def success(self) -> bool:
        return len(self.failed_rows) == 0

    @property
    def has_failures(self) -> bool:
        return len(self.failed_rows) > 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total_rows": self.total_rows,
            "processed_rows": self.processed_rows,
            "inserted_plaintiffs": self.inserted_plaintiffs,
            "updated_plaintiffs": self.updated_plaintiffs,
            "skipped_duplicates": self.skipped_duplicates,
            "failed_count": len(self.failed_rows),
            "quarantine_file": (str(self.quarantine_file) if self.quarantine_file else None),
            "committed": self.committed,
            "success": self.success,
        }


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _clean(value: Optional[str]) -> str:
    """Strip whitespace, return empty string for None."""
    return (value or "").strip()


def _normalize_header(header: str) -> str:
    """Lowercase, strip whitespace and underscores for header matching."""
    return header.strip().lower().replace("_", "").replace(" ", "")


def _normalize_name(name: str) -> str:
    """Normalize a name for deduplication matching."""
    cleaned = _clean(name)
    return " ".join(cleaned.lower().split())


def _normalize_email(email: Optional[str]) -> Optional[str]:
    """Normalize email to lowercase, return None if blank."""
    cleaned = _clean(email)
    return cleaned.lower() if cleaned else None


def _normalize_phone(phone: Optional[str]) -> Optional[str]:
    """Extract digits only from phone, return None if insufficient."""
    import re

    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    return digits if len(digits) >= 7 else None


def _parse_date(value: Optional[str]) -> Optional[date]:
    """Parse date from various formats, return None if unparseable."""
    if not value:
        return None
    cleaned = _clean(value)
    if not cleaned:
        return None

    formats = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    # Try ISO format
    try:
        return datetime.fromisoformat(cleaned).date()
    except ValueError:
        return None


def _parse_amount(value: Optional[str]) -> Optional[Decimal]:
    """Parse monetary amount, return None if unparseable."""
    if not value:
        return None
    cleaned = _clean(value).replace("$", "").replace(",", "")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


# ---------------------------------------------------------------------------
# CSV Parsing
# ---------------------------------------------------------------------------


def _build_header_map(fieldnames: List[str]) -> Dict[str, str]:
    """Map normalized header names to original header names."""
    header_map: Dict[str, str] = {}
    for original in fieldnames:
        normalized = _normalize_header(original)
        header_map[normalized] = original
    return header_map


def _extract_field(
    raw_row: Dict[str, str], header_map: Dict[str, str], *candidate_keys: str
) -> Optional[str]:
    """Extract a field value trying multiple candidate header names."""
    for key in candidate_keys:
        normalized_key = _normalize_header(key)
        if normalized_key in header_map:
            original_header = header_map[normalized_key]
            value = _clean(raw_row.get(original_header, ""))
            if value:
                return value
    return None


def _parse_row(raw_row: Dict[str, str], header_map: Dict[str, str], row_number: int) -> ParsedRow:
    """Parse a raw CSV row into a typed ParsedRow structure."""
    plaintiff_name = _extract_field(
        raw_row, header_map, "plaintiffname", "plaintiff_name", "plaintiff"
    )
    judgment_number = _extract_field(
        raw_row,
        header_map,
        "judgmentnumber",
        "judgment_number",
        "indexnumber",
        "index_number",
        "leadid",
        "lead_id",
    )

    if not plaintiff_name:
        raise ValueError("Missing required field: PlaintiffName")
    if not judgment_number:
        raise ValueError("Missing required field: JudgmentNumber")

    return ParsedRow(
        row_number=row_number,
        lead_id=_extract_field(raw_row, header_map, "leadid", "lead_id"),
        plaintiff_name=plaintiff_name,
        judgment_number=judgment_number,
        case_number=_extract_field(raw_row, header_map, "casenumber", "case_number", "indexnumber"),
        docket_number=_extract_field(raw_row, header_map, "docketnumber", "docket_number"),
        court=_extract_field(raw_row, header_map, "court", "court_name"),
        county=_extract_field(raw_row, header_map, "county"),
        state=_extract_field(raw_row, header_map, "state", "plaintiff_state"),
        judgment_date=_parse_date(
            _extract_field(raw_row, header_map, "judgmentdate", "judgment_date")
        ),
        filing_date=_parse_date(_extract_field(raw_row, header_map, "filingdate", "filing_date")),
        judgment_amount=_parse_amount(
            _extract_field(raw_row, header_map, "judgmentamount", "judgment_amount", "amount")
        ),
        plaintiff_address=_extract_field(
            raw_row, header_map, "plaintiffaddress", "plaintiff_address", "address"
        ),
        phone=_extract_field(raw_row, header_map, "phone", "plaintiff_phone"),
        email=_extract_field(raw_row, header_map, "email", "plaintiff_email"),
        best_contact_method=_extract_field(
            raw_row, header_map, "bestcontactmethod", "best_contact_method"
        ),
        status=_extract_field(raw_row, header_map, "status"),
        defendant_name=_extract_field(
            raw_row, header_map, "defendantname", "defendant_name", "defendant"
        ),
        raw=dict(raw_row),
    )


def _read_csv(batch_file: Path) -> tuple[List[ParsedRow], List[FailedRow]]:
    """Read and parse CSV file, separating successful parses from failures."""
    rows: List[ParsedRow] = []
    failures: List[FailedRow] = []

    with batch_file.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV file is missing a header row")

        header_map = _build_header_map(list(reader.fieldnames))

        for row_index, raw_row in enumerate(reader, start=2):
            # Skip completely blank rows
            if not any(_clean(v) for v in raw_row.values()):
                continue

            try:
                parsed = _parse_row(raw_row, header_map, row_index)
                rows.append(parsed)
            except ValueError as exc:
                failures.append(
                    FailedRow(
                        row_number=row_index,
                        raw_data=dict(raw_row),
                        error_type="ValidationError",
                        error_message=str(exc),
                        stage="parse",
                    )
                )
            except Exception as exc:
                failures.append(
                    FailedRow(
                        row_number=row_index,
                        raw_data=dict(raw_row),
                        error_type=type(exc).__name__,
                        error_message=str(exc)[:MAX_ERROR_DETAIL_LEN],
                        stage="parse",
                    )
                )

    return rows, failures


# ---------------------------------------------------------------------------
# Database operations with idempotency
# ---------------------------------------------------------------------------


def _get_table_columns(conn: Connection, table_name: str) -> set[str]:
    """Get the set of column names in a table."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table_name,),
        )
        return {row[0] for row in cur.fetchall()}


def _find_existing_plaintiff(
    conn: Connection, parsed: ParsedRow, columns: set[str]
) -> Optional[Dict[str, Any]]:
    """
    Find existing plaintiff by external_id, email, or normalized name.

    Returns dict with id and current field values if found, None otherwise.
    This is the core idempotency lookup.
    """
    name = parsed.get("plaintiff_name") or ""
    email = parsed.get("email")
    lead_id = parsed.get("lead_id")

    has_external_id = "external_id" in columns
    base_cols = "id, name, email, phone, source_system"
    select_cols = f"{base_cols}, external_id" if has_external_id else base_cols

    with conn.cursor(row_factory=dict_row) as cur:
        # Priority 1: Match by external_id (lead_id) if present and column exists
        if lead_id and has_external_id:
            cur.execute(
                sql.SQL(
                    """
                    SELECT {}
                    FROM public.plaintiffs
                    WHERE external_id = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                ).format(sql.SQL(select_cols)),
                (lead_id,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)

        # Priority 2: Match by email (case-insensitive)
        email_norm = _normalize_email(email)
        if email_norm:
            cur.execute(
                sql.SQL(
                    """
                    SELECT {}
                    FROM public.plaintiffs
                    WHERE lower(email) = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                ).format(sql.SQL(select_cols)),
                (email_norm,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)

        # Priority 3: Match by normalized name
        name_norm = _normalize_name(name)
        cur.execute(
            sql.SQL(
                """
                SELECT {}
                FROM public.plaintiffs
                WHERE regexp_replace(lower(trim(name)), '\\s+', ' ', 'g') = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ).format(sql.SQL(select_cols)),
            (name_norm,),
        )
        row = cur.fetchone()
        if row:
            return dict(row)

    return None


def _check_judgment_exists(conn: Connection, parsed: ParsedRow) -> bool:
    """Check if a judgment with this number already exists."""
    judgment_number = parsed.get("judgment_number") or ""
    case_number = parsed.get("case_number")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM public.judgments
            WHERE judgment_number = %s
               OR case_number = %s
            LIMIT 1
            """,
            (judgment_number, case_number),
        )
        return cur.fetchone() is not None


def _upsert_plaintiff(
    conn: Connection,
    parsed: ParsedRow,
    existing: Optional[Dict[str, Any]],
    config: ImportConfig,
    columns: set[str],
) -> tuple[str, bool]:
    """
    Insert or update plaintiff record.

    Returns (plaintiff_id, was_created).
    """
    has_external_id = "external_id" in columns

    if existing:
        plaintiff_id = str(existing["id"])

        # Update fields that are currently blank
        updates: Dict[str, Any] = {}
        if parsed.get("email") and not existing.get("email"):
            updates["email"] = parsed.get("email")
        if parsed.get("phone") and not existing.get("phone"):
            updates["phone"] = _normalize_phone(parsed.get("phone"))
        if has_external_id and parsed.get("lead_id") and not existing.get("external_id"):
            updates["external_id"] = parsed.get("lead_id")

        if updates:
            update_cols = list(updates.keys())
            set_clause = sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(col)) for col in update_cols
            )
            query = sql.SQL(
                "UPDATE public.plaintiffs SET {}, updated_at = now() WHERE id = %s"
            ).format(set_clause)

            with conn.cursor() as cur:
                cur.execute(query, [*updates.values(), plaintiff_id])

        return plaintiff_id, False

    # Insert new plaintiff - build column list dynamically
    insert_cols = ["name", "email", "phone", "status", "source_system"]
    insert_vals: List[Any] = [
        parsed.get("plaintiff_name"),
        parsed.get("email"),
        _normalize_phone(parsed.get("phone")),
        "new",
        config.source,
    ]

    if has_external_id:
        insert_cols.append("external_id")
        insert_vals.append(parsed.get("lead_id"))

    cols_sql = sql.SQL(", ").join(sql.Identifier(c) for c in insert_cols)
    vals_sql = sql.SQL(", ").join(sql.Placeholder() for _ in insert_cols)
    insert_query = sql.SQL("INSERT INTO public.plaintiffs ({}) VALUES ({}) RETURNING id").format(
        cols_sql, vals_sql
    )

    with conn.cursor() as cur:
        cur.execute(insert_query, insert_vals)
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Failed to insert plaintiff")
        return str(row[0]), True


def _insert_judgment(
    conn: Connection, parsed: ParsedRow, plaintiff_id: str, columns: set[str]
) -> str:
    """Insert a judgment record linked to the plaintiff, adapting to available columns."""
    # Required/always present columns
    insert_cols: List[str] = [
        "case_number",
        "judgment_number",
        "plaintiff_id",
        "plaintiff_name",
        "defendant_name",
        "judgment_amount",
        "entry_date",
    ]
    insert_vals: List[Any] = [
        parsed.get("case_number") or parsed.get("judgment_number") or "",
        parsed.get("judgment_number") or "",
        plaintiff_id,
        parsed.get("plaintiff_name") or "",
        parsed.get("defendant_name"),
        parsed.get("judgment_amount"),
        parsed.get("judgment_date") or parsed.get("filing_date") or date.today(),
    ]

    # Optional columns - only include if they exist in the schema
    optional_mappings: List[tuple[str, Any]] = [
        ("court_name", parsed.get("court")),
        ("county", parsed.get("county")),
        ("state", parsed.get("state")),
    ]
    for col_name, val in optional_mappings:
        if col_name in columns:
            insert_cols.append(col_name)
            insert_vals.append(val)

    cols_sql = sql.SQL(", ").join(sql.Identifier(c) for c in insert_cols)
    vals_sql = sql.SQL(", ").join(sql.Placeholder() for _ in insert_cols)
    insert_query = sql.SQL("INSERT INTO public.judgments ({}) VALUES ({}) RETURNING id").format(
        cols_sql, vals_sql
    )

    with conn.cursor() as cur:
        cur.execute(insert_query, insert_vals)
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Failed to insert judgment")
        return str(row[0])


def _insert_status_history(conn: Connection, plaintiff_id: str, batch_name: str) -> None:
    """Record initial status history entry."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.plaintiff_status_history (
                plaintiff_id, status, note, changed_by
            )
            VALUES (%s, 'new', %s, 'simplicity_orchestrator')
            """,
            (plaintiff_id, f"Import batch: {batch_name}"),
        )


def _insert_contact(conn: Connection, plaintiff_id: str, parsed: ParsedRow) -> Optional[int]:
    """Insert contact record if contact info is present."""
    email = parsed.get("email")
    phone = _normalize_phone(parsed.get("phone"))
    address = parsed.get("plaintiff_address")

    if not any([email, phone, address]):
        return None

    with conn.cursor() as cur:
        # Check for existing contact to avoid duplicates
        cur.execute(
            """
            SELECT id FROM public.plaintiff_contacts
            WHERE plaintiff_id = %s
              AND (
                  (email IS NOT NULL AND lower(email) = lower(%s))
                  OR (phone IS NOT NULL AND phone = %s)
              )
            LIMIT 1
            """,
            (plaintiff_id, email, phone),
        )
        if cur.fetchone():
            return None  # Contact already exists

        cur.execute(
            """
            INSERT INTO public.plaintiff_contacts (
                plaintiff_id, name, email, phone, role
            )
            VALUES (%s, %s, %s, %s, 'primary')
            RETURNING id
            """,
            (
                plaintiff_id,
                parsed.get("plaintiff_name") or "Unknown",
                email,
                phone,
            ),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None


def _queue_downstream_jobs(
    conn: Connection,
    plaintiff_id: str,
    judgment_id: str,
    config: ImportConfig,
) -> List[Dict[str, Any]]:
    """Queue enrichment and enforcement jobs if queue_job RPC exists."""
    jobs: List[Dict[str, Any]] = []

    if config.skip_jobs:
        return jobs

    # Check if queue_job exists
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.routines
            WHERE routine_schema = 'public' AND routine_name = 'queue_job'
            LIMIT 1
            """
        )
        if not cur.fetchone():
            return jobs

    batch_name = config.effective_batch_name

    for kind in ["enrich", "enforce"]:
        idempotency_key = f"{config.source}:{kind}:{judgment_id}"
        payload = Jsonb(
            {
                "kind": kind,
                "idempotency_key": idempotency_key,
                "payload": {
                    "plaintiff_id": plaintiff_id,
                    "judgment_id": judgment_id,
                    "source": config.source,
                    "batch_name": batch_name,
                    "run_id": config.run_id,
                },
            }
        )

        try:
            with conn.cursor() as cur:
                cur.execute("SELECT public.queue_job(%s)", (payload,))
                row = cur.fetchone()
                msg_id = row[0] if row else None
                jobs.append({"kind": kind, "message_id": msg_id, "status": "queued"})
        except Exception as exc:
            jobs.append({"kind": kind, "status": "error", "error": str(exc)})

    return jobs


# ---------------------------------------------------------------------------
# Quarantine (dead-letter) handling
# ---------------------------------------------------------------------------


def _write_quarantine_file(
    failures: List[FailedRow], run_id: str, base_dir: Path
) -> Optional[Path]:
    """Write failed rows to a quarantine CSV file."""
    if not failures:
        return None

    base_dir.mkdir(parents=True, exist_ok=True)
    quarantine_path = base_dir / f"failed_rows_{run_id}.csv"

    fieldnames = ["row_number", "stage", "error_type", "error_message", "raw_data"]

    with quarantine_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for fail in failures:
            writer.writerow(
                {
                    "row_number": fail.row_number,
                    "stage": fail.stage,
                    "error_type": fail.error_type,
                    "error_message": fail.error_message,
                    "raw_data": json.dumps(fail.raw_data),
                }
            )

    return quarantine_path


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def run_import(config: ImportConfig) -> ImportResult:
    """
    Execute the import with full idempotency and quarantine handling.

    Each row is processed in its own savepoint. Failures are captured
    and quarantined rather than aborting the entire batch.
    """
    result = ImportResult(run_id=config.run_id)

    # Validate input file exists
    if not config.batch_file.exists():
        raise FileNotFoundError(f"Batch file not found: {config.batch_file}")

    # Parse CSV
    logger.info("[orchestrator] Parsing %s (run_id=%s)", config.batch_file, config.run_id)
    parsed_rows, parse_failures = _read_csv(config.batch_file)
    result.total_rows = len(parsed_rows) + len(parse_failures)
    result.failed_rows.extend(parse_failures)

    if parse_failures:
        logger.warning("[orchestrator] %d rows failed parsing", len(parse_failures))

    if not parsed_rows:
        logger.warning("[orchestrator] No valid rows to process")
        return result

    # Connect to database
    env = get_supabase_env()
    db_url = get_supabase_db_url(env)
    host, dbname, user = describe_db_url(db_url)
    logger.info(
        "[orchestrator] Connecting: host=%s db=%s env=%s commit=%s",
        host,
        dbname,
        env,
        config.commit,
    )

    batch_name = config.effective_batch_name

    with psycopg.connect(db_url, autocommit=False) as conn:
        # Get available columns once for schema-aware operations
        plaintiff_columns = _get_table_columns(conn, "plaintiffs")
        judgment_columns = _get_table_columns(conn, "judgments")

        for parsed in parsed_rows:
            row_num = parsed.get("row_number", 0)
            savepoint_name = f"row_{row_num}"

            try:
                with conn.cursor() as cur:
                    cur.execute(sql.SQL("SAVEPOINT {}").format(sql.Identifier(savepoint_name)))

                # Check for duplicate judgment
                if _check_judgment_exists(conn, parsed):
                    result.skipped_duplicates += 1
                    result.processed_rows += 1
                    logger.debug("[orchestrator] row %d: skipped (judgment exists)", row_num)
                    with conn.cursor() as cur:
                        cur.execute(
                            sql.SQL("RELEASE SAVEPOINT {}").format(sql.Identifier(savepoint_name))
                        )
                    continue

                # Find or create plaintiff (idempotent)
                existing = _find_existing_plaintiff(conn, parsed, plaintiff_columns)
                plaintiff_id, was_created = _upsert_plaintiff(
                    conn, parsed, existing, config, plaintiff_columns
                )

                if was_created:
                    result.inserted_plaintiffs += 1
                    _insert_status_history(conn, plaintiff_id, batch_name)
                else:
                    result.updated_plaintiffs += 1

                # Insert judgment
                judgment_id = _insert_judgment(conn, parsed, plaintiff_id, judgment_columns)

                # Insert contact (idempotent)
                _insert_contact(conn, plaintiff_id, parsed)

                # Queue downstream jobs
                _queue_downstream_jobs(conn, plaintiff_id, judgment_id, config)

                result.processed_rows += 1

                # Release savepoint on success
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("RELEASE SAVEPOINT {}").format(sql.Identifier(savepoint_name))
                    )

                logger.debug(
                    "[orchestrator] row %d: %s (plaintiff=%s judgment=%s)",
                    row_num,
                    "created" if was_created else "updated",
                    plaintiff_id,
                    judgment_id,
                )

            except Exception as exc:
                # Rollback savepoint and record failure
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("ROLLBACK TO SAVEPOINT {}").format(sql.Identifier(savepoint_name))
                    )
                    cur.execute(
                        sql.SQL("RELEASE SAVEPOINT {}").format(sql.Identifier(savepoint_name))
                    )

                result.failed_rows.append(
                    FailedRow(
                        row_number=row_num,
                        raw_data=parsed.get("raw", {}),
                        error_type=type(exc).__name__,
                        error_message=str(exc)[:MAX_ERROR_DETAIL_LEN],
                        stage="insert",
                    )
                )
                logger.warning(
                    "[orchestrator] row %d: FAILED - %s: %s",
                    row_num,
                    type(exc).__name__,
                    exc,
                )

        # Commit or rollback
        if config.commit and result.processed_rows > 0:
            conn.commit()
            result.committed = True
            logger.info("[orchestrator] Committed %d rows", result.processed_rows)
        else:
            conn.rollback()
            logger.info("[orchestrator] Rolled back (dry-run or no rows processed)")

    # Write quarantine file if there are failures
    if result.failed_rows:
        quarantine_dir = config.batch_file.parent.parent / QUARANTINE_DIR
        result.quarantine_file = _write_quarantine_file(
            result.failed_rows, config.run_id, quarantine_dir
        )
        if result.quarantine_file:
            logger.warning(
                "[orchestrator] Quarantined %d failed rows to %s",
                len(result.failed_rows),
                result.quarantine_file,
            )

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bulletproof Simplicity plaintiff import orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run (default)
  python -m etl.src.simplicity_orchestrator --batch-file=data_in/intake.csv

  # Commit changes
  python -m etl.src.simplicity_orchestrator --batch-file=data_in/intake.csv --commit

  # With explicit run ID
  python -m etl.src.simplicity_orchestrator --batch-file=data_in/intake.csv --run-id=abc123 --commit
        """,
    )
    parser.add_argument(
        "--batch-file",
        required=True,
        type=Path,
        help="Path to the CSV file to import",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Unique run identifier (auto-generated if not provided)",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help=f"Source system identifier (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--batch-name",
        default=None,
        help="Human-readable batch name (auto-generated if not provided)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Commit changes to database (default: dry-run)",
    )
    parser.add_argument(
        "--skip-jobs",
        action="store_true",
        help="Skip queuing downstream enrichment/enforcement jobs",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Build config
    run_id = args.run_id or str(uuid.uuid4())
    config = ImportConfig(
        batch_file=args.batch_file,
        run_id=run_id,
        source=args.source,
        commit=args.commit,
        skip_jobs=args.skip_jobs,
        batch_name=args.batch_name,
    )

    try:
        result = run_import(config)
    except FileNotFoundError as exc:
        logger.error("[orchestrator] %s", exc)
        return 2
    except Exception as exc:
        logger.exception("[orchestrator] Fatal error: %s", exc)
        return 2

    # Output
    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        logger.info(
            "[orchestrator] Complete: total=%d processed=%d inserted=%d updated=%d skipped=%d failed=%d committed=%s",
            result.total_rows,
            result.processed_rows,
            result.inserted_plaintiffs,
            result.updated_plaintiffs,
            result.skipped_duplicates,
            len(result.failed_rows),
            result.committed,
        )
        if result.quarantine_file:
            logger.info("[orchestrator] Failures written to: %s", result.quarantine_file)

    # Exit code
    if result.has_failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
