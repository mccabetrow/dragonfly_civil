"""CSV-driven plaintiff importer with dry-run and transactional safeguards.

This module consumes **canonical** plaintiff CSV files (headers such as
``PlaintiffName`` and ``ContactName``) and synchronises them with the Supabase
``public.plaintiffs`` domain tables. Use ``python -m
etl.src.plaintiff_vendor_adapter`` to reshape vendor-specific exports into this
canonical layout before importing. The workflow emphasises safety and
observability:

* CSV rows missing the required ``PlaintiffName`` or ``ContactName`` columns are
  skipped with a warning.
* By default the CLI operates in **dry-run** mode and prints a summary of what
  would happen without touching the database. Pass ``--commit`` to apply the
  changes inside a single transaction.
* Plaintiffs are matched using contact email first (case-insensitive) and then
  by normalised name. Field updates only populate empty columns so manual edits
  are preserved.
* Contacts are deduplicated per plaintiff by email (preferred) or contact name,
  preventing duplicate inserts when a CSV is replayed.
* A short summary of the actions appears at the end along with a preview of up
  to three affected plaintiffs.

The module reuses the psycopg connection helpers from ``foil_utils`` so it can
run in automation contexts as well as locally via ``python -m
etl.src.plaintiff_importer``.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, cast

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from src.supabase_client import describe_db_url, get_supabase_db_url, get_supabase_env

logger = logging.getLogger(__name__)

# Canonical CSV inputs must already provide these headings. See
# ``plaintiff_vendor_adapter`` for mapping vendor-specific exports into this
# schema.
REQUIRED_HEADERS = {"plaintiffname", "contactname"}


def _resolve_db_target() -> tuple[str, str, str, str]:
    env = get_supabase_env()
    url = get_supabase_db_url(env)
    host, dbname, user = describe_db_url(url)
    logger.info(
        "[plaintiff_importer] Connecting to db host=%s dbname=%s user=%s env=%s",
        host,
        dbname,
        user,
        env,
    )
    return env, url, host, dbname


def _ensure_required_table(
    conn: Connection,
    schema: str,
    table: str,
    *,
    env: str,
    host: str,
    dbname: str,
) -> bool:
    query = "select 1 from information_schema.tables where table_schema = %s and table_name = %s"
    with conn.cursor() as cur:
        cur.execute(query, (schema, table))
        exists = cur.fetchone()
    if exists:
        return True

    logger.error(
        "[plaintiff_importer] ERROR: %s.%s does not exist in this database (host=%s dbname=%s env=%s). "
        "Are you pointing at the right Supabase project/env and have migrations 0071–0073 been applied?",
        schema,
        table,
        host,
        dbname,
        env,
    )
    return False


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")


def _clean(value: Optional[str]) -> str:
    return (value or "").strip()


def _normalize_header(value: Optional[str]) -> str:
    return _clean(value).lower()


def _normalize_name(value: str) -> str:
    cleaned = _clean(value)
    return " ".join(cleaned.lower().split())


def _normalize_email(value: Optional[str]) -> Optional[str]:
    cleaned = _clean(value)
    return cleaned.lower() or None


def _is_blank(value: Optional[str]) -> bool:
    return value is None or _clean(value) == ""


def _parse_decimal(value: Optional[str]) -> Optional[Decimal]:
    cleaned = _clean(value)
    if not cleaned:
        return None
    candidate = cleaned.replace(",", "").replace("$", "")
    try:
        return Decimal(candidate)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value {value!r}") from exc


# ---------------------------------------------------------------------------
# CSV aggregation structures
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ContactCandidate:
    name: str
    normalized_name: str
    email: Optional[str]
    normalized_email: Optional[str]
    phone: Optional[str]
    role: str


@dataclass(slots=True)
class PlaintiffCandidate:
    name: str
    normalized_name: str
    firm_name: Optional[str] = None
    email: Optional[str] = None
    normalized_email: Optional[str] = None
    phone: Optional[str] = None
    total_judgment_amount: Decimal = Decimal("0")
    contacts: List[ContactCandidate] = field(default_factory=list)
    row_numbers: List[int] = field(default_factory=list)
    preview_contact: Optional[str] = None
    _contact_keys: set[str] = field(default_factory=set, init=False, repr=False)

    def add_amount(self, value: Optional[Decimal]) -> None:
        if value is None:
            return
        self.total_judgment_amount += value

    def update_profile(
        self, *, firm_name: Optional[str], email: Optional[str], phone: Optional[str]
    ) -> None:
        if firm_name and not self.firm_name:
            self.firm_name = firm_name
        if email and not self.email:
            self.email = email
            self.normalized_email = _normalize_email(email)
        if phone and not self.phone:
            self.phone = phone

    def add_contact(self, contact: ContactCandidate) -> None:
        key = contact.normalized_email or f"name:{contact.normalized_name}"
        if not key:
            return
        if key in self._contact_keys:
            return
        self.contacts.append(contact)
        self._contact_keys.add(key)
        if self.preview_contact is None:
            descriptor = contact.email or contact.phone or contact.name
            self.preview_contact = descriptor


@dataclass(slots=True)
class ParseResult:
    candidates: List[PlaintiffCandidate]
    total_rows: int
    rows_skipped: int


# ---------------------------------------------------------------------------
# Database lookup caches
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ExistingPlaintiff:
    id: str
    name: str
    firm_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    normalized_name: str
    normalized_email: Optional[str]


class ExistingIndex:
    """Lookup helper keyed by normalised email and name."""

    def __init__(self) -> None:
        self.by_email: Dict[str, ExistingPlaintiff] = {}
        self.by_name: Dict[str, ExistingPlaintiff] = {}

    @classmethod
    def load(cls, conn: Connection, candidates: Iterable[PlaintiffCandidate]) -> "ExistingIndex":
        normalized_names = sorted({candidate.normalized_name for candidate in candidates})
        normalized_emails = sorted(
            {candidate.normalized_email for candidate in candidates if candidate.normalized_email}
        )

        query = """
        WITH shaped AS (
            SELECT
                id,
                name,
                firm_name,
                email,
                phone,
                regexp_replace(lower(trim(name)), '\\s+', ' ', 'g') AS normalized_name,
                lower(email) AS normalized_email
            FROM public.plaintiffs
        )
        SELECT * FROM shaped
        """
        clauses: List[str] = []
        params: List[object] = []
        if normalized_names:
            clauses.append("normalized_name = ANY(%s)")
            params.append(normalized_names)
        if normalized_emails:
            clauses.append("normalized_email = ANY(%s)")
            params.append(normalized_emails)
        if clauses:
            query += " WHERE " + " OR ".join(clauses)

        index = cls()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(cast(Any, query), params)
            for row in cur.fetchall():
                index.register(
                    ExistingPlaintiff(
                        id=str(row["id"]),
                        name=row["name"],
                        firm_name=row.get("firm_name"),
                        email=row.get("email"),
                        phone=row.get("phone"),
                        normalized_name=row["normalized_name"],
                        normalized_email=row.get("normalized_email"),
                    )
                )
        return index

    def register(self, record: ExistingPlaintiff) -> None:
        if record.normalized_email:
            self.by_email.setdefault(record.normalized_email, record)
        self.by_name.setdefault(record.normalized_name, record)

    def refresh(self, record: ExistingPlaintiff) -> None:
        if record.normalized_email:
            self.by_email[record.normalized_email] = record
        self.by_name[record.normalized_name] = record

    def lookup(self, candidate: PlaintiffCandidate) -> Optional[ExistingPlaintiff]:
        if candidate.normalized_email and candidate.normalized_email in self.by_email:
            return self.by_email[candidate.normalized_email]
        return self.by_name.get(candidate.normalized_name)


@dataclass(slots=True)
class ContactLedger:
    emails: set[str] = field(default_factory=set)
    names: set[str] = field(default_factory=set)


class ContactCache:
    """Lazy-load contact deduplication data per plaintiff."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self._cache: Dict[str, ContactLedger] = {}

    def get(self, plaintiff_id: str) -> ContactLedger:
        if plaintiff_id in self._cache:
            return self._cache[plaintiff_id]
        ledger = ContactLedger()
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    lower(email) AS normalized_email,
                    regexp_replace(lower(trim(name)), '\\s+', ' ', 'g') AS normalized_name
                FROM public.plaintiff_contacts
                WHERE plaintiff_id = %s
                """,
                (plaintiff_id,),
            )
            for row in cur.fetchall():
                if row.get("normalized_email"):
                    ledger.emails.add(row["normalized_email"])
                if row.get("normalized_name"):
                    ledger.names.add(row["normalized_name"])
        self._cache[plaintiff_id] = ledger
        return ledger

    def add(self, plaintiff_id: str, contact: ContactCandidate) -> None:
        ledger = self._cache.setdefault(plaintiff_id, ContactLedger())
        if contact.normalized_email:
            ledger.emails.add(contact.normalized_email)
        ledger.names.add(contact.normalized_name)


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------


def _validate_headers(fieldnames: Iterable[str]) -> None:
    normalized = {_normalize_header(name) for name in fieldnames if name is not None}
    missing = sorted(REQUIRED_HEADERS - normalized)
    if missing:
        raise ValueError("CSV is missing required column(s): " + ", ".join(missing))


def _read_csv(csv_path: Path, *, limit: Optional[int] = None) -> ParseResult:
    total_rows = 0
    skipped_rows = 0
    aggregates: Dict[str, PlaintiffCandidate] = {}

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file is missing a header row")
        _validate_headers(reader.fieldnames)

        for row_index, raw_row in enumerate(reader, start=2):
            total_rows += 1
            normalized_row = {
                _normalize_header(key): _clean(value)
                for key, value in raw_row.items()
                if key is not None
            }

            plaintiff_name = normalized_row.get("plaintiffname", "")
            contact_name = normalized_row.get("contactname", "")
            if not plaintiff_name or not contact_name:
                skipped_rows += 1
                logger.warning(
                    "row %s missing required plaintiff/contact name; skipping",
                    row_index,
                )
                if limit is not None and total_rows >= limit:
                    break
                continue

            normalized_name = _normalize_name(plaintiff_name)
            candidate = aggregates.get(normalized_name)
            if candidate is None:
                candidate = PlaintiffCandidate(name=plaintiff_name, normalized_name=normalized_name)
                aggregates[normalized_name] = candidate

            candidate.row_numbers.append(row_index)

            amount_value = normalized_row.get("totaljudgmentamount")
            try:
                candidate.add_amount(_parse_decimal(amount_value))
            except ValueError as exc:
                logger.warning("row %s invalid TotalJudgmentAmount: %s", row_index, exc)

            firm_name = normalized_row.get("firmname")
            plaintiff_email = normalized_row.get("plaintiffemail")
            plaintiff_phone = normalized_row.get("plaintiffphone")
            candidate.update_profile(
                firm_name=firm_name or None,
                email=plaintiff_email or None,
                phone=plaintiff_phone or None,
            )

            contact_email = normalized_row.get("contactemail") or None
            contact_phone = normalized_row.get("contactphone") or None
            contact = ContactCandidate(
                name=contact_name,
                normalized_name=_normalize_name(contact_name),
                email=contact_email,
                normalized_email=_normalize_email(contact_email),
                phone=contact_phone,
                role="primary" if not candidate.contacts else "secondary",
            )
            candidate.add_contact(contact)
            if candidate.email is None and contact.email:
                candidate.email = contact.email
                candidate.normalized_email = contact.normalized_email
            if candidate.phone is None and contact.phone:
                candidate.phone = contact.phone

            if limit is not None and total_rows >= limit:
                break

    return ParseResult(list(aggregates.values()), total_rows, skipped_rows)


# Backwards-compatibility shim for existing tests/imports.
def aggregate_plaintiffs(
    csv_path: Path, *, limit: Optional[int] = None
) -> List[PlaintiffCandidate]:
    return _read_csv(csv_path, limit=limit).candidates


# ---------------------------------------------------------------------------
# Database write helpers
# ---------------------------------------------------------------------------


def _determine_updates(
    candidate: PlaintiffCandidate, existing: ExistingPlaintiff
) -> Dict[str, str]:
    updates: Dict[str, str] = {}

    def maybe(field: str, new_value: Optional[str]) -> None:
        if _is_blank(new_value):
            return
        current = getattr(existing, field)
        if _is_blank(current):
            updates[field] = new_value  # type: ignore[assignment]

    maybe("firm_name", candidate.firm_name)
    maybe("email", candidate.email)
    maybe("phone", candidate.phone)
    return updates


def _insert_plaintiff(conn: Connection, candidate: PlaintiffCandidate) -> str:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO public.plaintiffs (name, firm_name, email, phone, status)
            VALUES (%s, %s, %s, %s, 'new')
            RETURNING id
            """,
            (candidate.name, candidate.firm_name, candidate.email, candidate.phone),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"Failed to insert plaintiff {candidate.name}")
        return str(row["id"])


def _update_plaintiff(conn: Connection, plaintiff_id: str, updates: Dict[str, str]) -> None:
    if not updates:
        return
    assignments = [f"{field} = %s" for field in updates]
    params: List[object] = list(updates.values())
    assignments.append("updated_at = now()")
    params.append(plaintiff_id)
    query = "UPDATE public.plaintiffs SET " + ", ".join(assignments) + " WHERE id = %s"
    with conn.cursor() as cur:
        cur.execute(cast(Any, query), params)


def _insert_status_entry(conn: Connection, plaintiff_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.plaintiff_status_history (plaintiff_id, status, note, changed_by)
            VALUES (%s, 'new', 'Imported from CSV', 'plaintiff_importer')
            """,
            (plaintiff_id,),
        )


def _insert_contact(conn: Connection, plaintiff_id: str, contact: ContactCandidate) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.plaintiff_contacts (plaintiff_id, name, email, phone, role)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (plaintiff_id, contact.name, contact.email, contact.phone, contact.role),
        )


# ---------------------------------------------------------------------------
# Import orchestration
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ImportStats:
    total_rows: int = 0
    rows_skipped: int = 0
    created_plaintiffs: int = 0
    updated_plaintiffs: int = 0
    created_contacts: int = 0
    duplicate_contacts: int = 0
    status_entries: int = 0
    examples: List[str] = field(default_factory=list)


def _process_candidates(
    conn: Connection,
    candidates: Sequence[PlaintiffCandidate],
    *,
    commit: bool,
    stats: ImportStats,
) -> ImportStats:
    if not candidates:
        return stats

    index = ExistingIndex.load(conn, candidates)
    contact_cache = ContactCache(conn)

    for candidate in candidates:
        existing = index.lookup(candidate)
        action_description = None
        new_contacts = 0
        duplicate_contacts = 0

        if existing is None:
            action_description = "create plaintiff"
            if commit:
                plaintiff_id = _insert_plaintiff(conn, candidate)
                index.refresh(
                    ExistingPlaintiff(
                        id=plaintiff_id,
                        name=candidate.name,
                        firm_name=candidate.firm_name,
                        email=candidate.email,
                        phone=candidate.phone,
                        normalized_name=candidate.normalized_name,
                        normalized_email=candidate.normalized_email,
                    )
                )
                _insert_status_entry(conn, plaintiff_id)
                stats.status_entries += 1
                for contact in candidate.contacts:
                    _insert_contact(conn, plaintiff_id, contact)
                    contact_cache.add(plaintiff_id, contact)
                new_contacts = len(candidate.contacts)
            else:
                new_contacts = len(candidate.contacts)
            stats.created_plaintiffs += 1
            stats.created_contacts += new_contacts
        else:
            updates = _determine_updates(candidate, existing)
            if updates:
                action_description = "update plaintiff"
            ledger = contact_cache.get(existing.id)
            for contact in candidate.contacts:
                email_key = contact.normalized_email
                name_key = contact.normalized_name
                if email_key and email_key in ledger.emails:
                    duplicate_contacts += 1
                    continue
                if not email_key and name_key in ledger.names:
                    duplicate_contacts += 1
                    continue
                new_contacts += 1
                if commit:
                    _insert_contact(conn, existing.id, contact)
                    contact_cache.add(existing.id, contact)
                else:
                    ledger.emails.update([email_key] if email_key else [])
                    ledger.names.add(name_key)
            if updates:
                if commit:
                    _update_plaintiff(conn, existing.id, updates)
                    if "email" in updates:
                        existing.email = updates["email"]
                        existing.normalized_email = _normalize_email(updates["email"])
                    if "firm_name" in updates:
                        existing.firm_name = updates["firm_name"]
                    if "phone" in updates:
                        existing.phone = updates["phone"]
                    index.refresh(existing)
                stats.updated_plaintiffs += 1
            stats.created_contacts += new_contacts
            stats.duplicate_contacts += duplicate_contacts
            if action_description is None and new_contacts > 0:
                action_description = "add contacts"

        if action_description and len(stats.examples) < 3:
            stats.examples.append(
                f"{candidate.name} — {action_description} (contacts+{new_contacts}, dupes={duplicate_contacts})"
            )

    return stats


def _log_summary(stats: ImportStats, *, commit: bool) -> None:
    mode = "commit" if commit else "dry-run"
    logger.info(
        "Import summary (%s): created_plaintiffs=%d updated_plaintiffs=%d created_contacts=%d duplicate_contacts=%d rows_skipped=%d total_rows=%d",
        mode,
        stats.created_plaintiffs,
        stats.updated_plaintiffs,
        stats.created_contacts,
        stats.duplicate_contacts,
        stats.rows_skipped,
        stats.total_rows,
    )
    if stats.status_entries:
        logger.info("Status history entries queued: %d", stats.status_entries)
    if stats.examples:
        logger.info("Example actions:")
        for example in stats.examples:
            logger.info(" • %s", example)
    if not commit:
        logger.info("Dry run complete. Re-run with --commit to persist changes.")


# ---------------------------------------------------------------------------
# CLI orchestration
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import plaintiffs and contacts from a CSV file")
    parser.add_argument(
        "--csv",
        dest="csv_path",
        required=True,
        help="Path to the CSV file containing plaintiffs",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report without writing to the database (default)",
    )
    mode_group.add_argument(
        "--commit", action="store_true", help="Apply the changes to the database"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N data rows (for smoke tests)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser


def _run_cli(argv: Optional[Sequence[str]]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        logger.error("CSV file not found: %s", csv_path)
        return 1

    dry_run = True
    if args.commit:
        dry_run = False
    elif args.dry_run:
        dry_run = True
    else:
        logger.warning(
            "No mode flag supplied; defaulting to dry-run. Pass --commit to persist changes."
        )

    try:
        target_env, db_url, host, dbname = _resolve_db_target()
    except Exception as exc:  # pragma: no cover - configuration guard
        logger.error("Unable to resolve Supabase database URL: %s", exc)
        return 1

    stats: Optional[ImportStats] = None

    try:
        with psycopg.connect(db_url, autocommit=dry_run) as conn:
            if not _ensure_required_table(
                conn,
                "public",
                "plaintiffs",
                env=target_env,
                host=host,
                dbname=dbname,
            ):
                return 1

            try:
                parse_result = _read_csv(csv_path, limit=args.limit)
            except ValueError as exc:
                logger.error("CSV validation failed: %s", exc)
                return 1

            if not parse_result.candidates:
                logger.warning("No valid plaintiff rows parsed from %s", csv_path)
                return 0

            stats = ImportStats(
                total_rows=parse_result.total_rows,
                rows_skipped=parse_result.rows_skipped,
            )

            _process_candidates(conn, parse_result.candidates, commit=not dry_run, stats=stats)
            if not dry_run:
                conn.commit()
    except Exception as exc:  # pragma: no cover - runtime guard
        logger.error("plaintiff import failed: %s", exc)
        logger.debug("Traceback", exc_info=True)
        return 1

    if stats is None:
        return 0

    _log_summary(stats, commit=not dry_run)
    return 0


async def main(argv: Optional[Sequence[str]] = None) -> int:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run_cli, argv)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(asyncio.run(main()))
