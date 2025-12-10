"""Utilities for parsing and importing Simplicity plaintiff judgment exports."""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

import psycopg
from psycopg import errors as psycopg_errors
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ValidationError, field_validator

from src.supabase_client import create_supabase_client, get_supabase_db_url, get_supabase_env

from .core_judgment_bridge import CoreJudgmentBridge
from .pipeline_support import (
    ContactSync,
    QueueJobManager,
    RawImportWriter,
    ensure_follow_up_task,
    initialize_enforcement_stage,
    sync_row_contacts,
)

__all__ = [
    "SimplicityImportRow",
    "ParseIssue",
    "LAST_PARSE_ERRORS",
    "parse_simplicity_csv",
    "run_simplicity_import",
]


_WHITESPACE_RE = re.compile(r"\s+")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


logger = logging.getLogger(__name__)


def _jsonify_metadata(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_jsonify_metadata(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonify_metadata(item) for key, item in value.items()}
    return value


@dataclass(slots=True)
class ParseIssue:
    """Information about a row that failed validation."""

    row_number: int
    error: str
    raw: Optional[Dict[str, Any]] = None


class SimplicityImportRow(BaseModel):
    plaintiff_name: str
    plaintiff_address_1: Optional[str] = None
    plaintiff_address_2: Optional[str] = None
    plaintiff_city: Optional[str] = None
    plaintiff_state: Optional[str] = None
    plaintiff_zip: Optional[str] = None
    plaintiff_phone: Optional[str] = None
    plaintiff_email: Optional[str] = None

    judgment_number: str
    court_name: Optional[str] = None
    judgment_amount: Decimal
    judgment_date: Optional[date] = None

    case_number: Optional[str] = None
    docket_number: Optional[str] = None
    filing_date: Optional[date] = None
    status: Optional[str] = None
    county: Optional[str] = None
    state: Optional[str] = None
    defendant_name: Optional[str] = None
    lead_id: Optional[str] = None
    best_contact_method: Optional[str] = None

    raw_row_number: Optional[int] = None

    model_config = {
        "extra": "ignore",
        "validate_assignment": True,
    }

    @staticmethod
    def _clean(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator(
        "plaintiff_name",
        "judgment_number",
        mode="before",
    )
    @classmethod
    def _require_and_strip(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("value is required")
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("value is required")
            return stripped
        return value

    @field_validator(
        "plaintiff_address_1",
        "plaintiff_address_2",
        "plaintiff_city",
        "court_name",
        "status",
        "county",
        "state",
        "defendant_name",
        "best_contact_method",
        mode="before",
    )
    @classmethod
    def _strip_optional(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("plaintiff_state", mode="before")
    @classmethod
    def _normalize_state(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
        return value

    @field_validator("plaintiff_state", mode="after")
    @classmethod
    def _validate_state(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if len(value) != 2 or not value.isalpha():
            raise ValueError("state must be a two-letter code")
        return value

    @field_validator("plaintiff_zip", mode="before")
    @classmethod
    def _clean_zip(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            digits: str | None = value.strip()
            digits = digits or None
            return digits
        return value

    @field_validator("plaintiff_phone", mode="before")
    @classmethod
    def _normalize_phone(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            digits = re.sub(r"\D", "", value)
            return digits or None
        return value

    @field_validator("plaintiff_phone", mode="after")
    @classmethod
    def _validate_phone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if len(value) < 7 or len(value) > 15:
            raise ValueError("phone number must contain between 7 and 15 digits")
        return value

    @field_validator("plaintiff_email", mode="before")
    @classmethod
    def _clean_email(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("plaintiff_email", mode="after")
    @classmethod
    def _validate_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not _EMAIL_RE.match(value):
            raise ValueError("invalid email address")
        return value

    @field_validator("judgment_amount", mode="before")
    @classmethod
    def _parse_amount(cls, value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        if value is None:
            raise ValueError("judgment_amount is required")
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        if isinstance(value, str):
            cleaned = value.strip().replace("$", "").replace(",", "")
            if not cleaned:
                raise ValueError("judgment_amount is required")
            try:
                return Decimal(cleaned)
            except InvalidOperation as exc:  # pragma: no cover - guarded by tests
                raise ValueError("invalid judgment amount") from exc
        raise ValueError("unsupported type for judgment_amount")

    @field_validator("judgment_date", "filing_date", mode="before")
    @classmethod
    def _parse_dates(cls, value: Any) -> Any:
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
                try:
                    return datetime.strptime(text, fmt).date()
                except ValueError:
                    continue
            try:
                return datetime.fromisoformat(text).date()
            except ValueError as exc:  # pragma: no cover - defensive fallback
                raise ValueError("invalid date format") from exc
        raise ValueError("invalid date value")


EXPECTED_HEADERS: List[str] = [
    "LeadID",
    "LeadSource",
    "Court",
    "IndexNumber",
    "JudgmentDate",
    "JudgmentAmount",
    "County",
    "State",
    "PlaintiffName",
    "PlaintiffAddress",
    "Phone",
    "Email",
    "BestContactMethod",
]


_HEADER_TO_FIELDS: Dict[str, tuple[str, ...]] = {
    "LeadID": ("lead_id",),
    "Court": ("court_name",),
    "IndexNumber": ("judgment_number", "case_number"),
    "JudgmentDate": ("judgment_date",),
    "JudgmentAmount": ("judgment_amount",),
    "County": ("county",),
    "State": ("state", "plaintiff_state"),
    "PlaintiffName": ("plaintiff_name",),
    "PlaintiffAddress": ("plaintiff_address_1",),
    "Phone": ("plaintiff_phone",),
    "Email": ("plaintiff_email",),
    "BestContactMethod": ("best_contact_method",),
}


def _clean_cell(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return str(value)


def _construct_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for header, fields in _HEADER_TO_FIELDS.items():
        cleaned = _clean_cell(row.get(header))
        if cleaned is None:
            continue
        for field in fields:
            payload[field] = cleaned

    state_value = payload.get("plaintiff_state") or payload.get("state")
    if state_value:
        payload.setdefault("state", state_value)
        payload.setdefault("plaintiff_state", state_value)

    if payload.get("lead_id") and not payload.get("judgment_number"):
        payload["judgment_number"] = payload["lead_id"]

    return payload


LAST_PARSE_ERRORS: List[ParseIssue] = []


STORAGE_BUCKET = "imports"


def _upload_csv_to_storage(
    *,
    supabase_client: Any,
    bucket: str,
    storage_path: str,
    csv_path: Path,
) -> None:
    storage = supabase_client.storage.from_(bucket)
    with csv_path.open("rb") as handle:
        payload = handle.read()
    response = storage.upload(storage_path, payload, {"content-type": "text/csv"})
    error = getattr(response, "error", None)
    status_code = getattr(response, "status_code", None)
    if error:
        raise RuntimeError(f"Supabase storage upload failed: {error}")

    if status_code is not None and status_code >= 400:
        raise RuntimeError(f"Supabase storage upload failed with status {status_code}")


def parse_simplicity_csv(path: str) -> List[SimplicityImportRow]:
    """Parse a Simplicity export CSV into validated import rows."""

    LAST_PARSE_ERRORS[:] = []
    rows: List[SimplicityImportRow] = []
    csv_path = Path(path)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file is missing a header row")
        header = [name.strip() if isinstance(name, str) else name for name in reader.fieldnames]
        if header != EXPECTED_HEADERS:
            raise ValueError("Unexpected Simplicity CSV header")

        for index, raw_row in enumerate(reader, start=2):
            if raw_row is None:
                continue

            if None in raw_row and raw_row[None]:
                error = ValueError("row contains unexpected extra columns")
                LAST_PARSE_ERRORS.append(
                    ParseIssue(
                        row_number=index,
                        error=str(error),
                        raw=dict(raw_row),
                    )
                )
                continue

            if not any(_clean_cell(value) for key, value in raw_row.items() if key is not None):
                continue

            try:
                payload = _construct_payload(raw_row)
                payload["raw_row_number"] = index
                model = SimplicityImportRow.model_validate(payload)
                rows.append(model)
            except (ValidationError, ValueError) as exc:
                LAST_PARSE_ERRORS.append(
                    ParseIssue(
                        row_number=index,
                        error=str(exc),
                        raw=dict(raw_row),
                    )
                )

    return rows


def _normalize_name(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value.strip().lower())


def _normalize_email(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def _normalize_phone(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits or None


def _fetch_columns(conn: psycopg.Connection, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = 'public' and table_name = %s
            """,
            (table,),
        )
        return {row[0] for row in cur.fetchall()}


def _find_existing_plaintiff(
    cur: psycopg.Cursor[Any],
    *,
    name: str,
    email: Optional[str],
    phone: Optional[str],
) -> Optional[dict[str, Any]]:
    email_norm = _normalize_email(email)
    if email_norm:
        cur.execute(
            """
            select id, name, email, phone, source_system
            from public.plaintiffs
            where lower(email) = %s
            order by updated_at desc
            limit 1
            """,
            (email_norm,),
        )
        record = cur.fetchone()
        if record:
            return {
                "id": str(record[0]),
                "name": record[1],
                "email": record[2],
                "phone": record[3],
                "source_system": record[4],
            }

    phone_norm = _normalize_phone(phone)
    if phone_norm:
        cur.execute(
            """
            select id, name, email, phone, source_system
            from public.plaintiffs
            where regexp_replace(coalesce(phone, ''), '\\D', '', 'g') = %s
            order by updated_at desc
            limit 1
            """,
            (phone_norm,),
        )
        record = cur.fetchone()
        if record:
            return {
                "id": str(record[0]),
                "name": record[1],
                "email": record[2],
                "phone": record[3],
                "source_system": record[4],
            }

    normalized_name = _normalize_name(name)
    cur.execute(
        """
        select id, name, email, phone, source_system
        from public.plaintiffs
        where regexp_replace(lower(trim(name)), '\\s+', ' ', 'g') = %s
        order by updated_at desc
        limit 1
        """,
        (normalized_name,),
    )
    record = cur.fetchone()
    if not record:
        return None
    return {
        "id": str(record[0]),
        "name": record[1],
        "email": record[2],
        "phone": record[3],
        "source_system": record[4],
    }


def _upsert_plaintiff(
    cur: psycopg.Cursor[Any],
    row: SimplicityImportRow,
    *,
    dry_run: bool,
    existing: Optional[dict[str, Any]] = None,
    source_system: Optional[str] = None,
) -> tuple[Optional[str], bool]:
    if existing is None:
        existing = _find_existing_plaintiff(
            cur,
            name=row.plaintiff_name,
            email=row.plaintiff_email,
            phone=row.plaintiff_phone,
        )
    if existing:
        if not dry_run:
            if row.plaintiff_email and not existing.get("email"):
                cur.execute(
                    """
                    update public.plaintiffs
                    set email = %s,
                        updated_at = timezone('utc', now())
                    where id = %s
                    """,
                    (row.plaintiff_email, existing["id"]),
                )
            if row.plaintiff_phone and not existing.get("phone"):
                cur.execute(
                    """
                    update public.plaintiffs
                    set phone = %s,
                        updated_at = timezone('utc', now())
                    where id = %s
                    """,
                    (row.plaintiff_phone, existing["id"]),
                )
            if source_system and (
                not existing.get("source_system") or existing.get("source_system") == "unknown"
            ):
                cur.execute(
                    """
                    update public.plaintiffs
                    set source_system = %s,
                        updated_at = timezone('utc', now())
                    where id = %s
                    """,
                    (source_system, existing["id"]),
                )
        return existing["id"], False

    if dry_run:
        return None, True

    insert_columns = ["name", "firm_name", "email", "phone", "status"]
    insert_values: List[Any] = [
        row.plaintiff_name,
        None,
        row.plaintiff_email,
        row.plaintiff_phone,
        "new",
    ]
    if source_system:
        insert_columns.append("source_system")
        insert_values.append(source_system)

    columns_sql = sql.SQL(", ").join(sql.Identifier(col) for col in insert_columns)
    values_sql = sql.SQL(", ").join(sql.Placeholder() for _ in insert_columns)
    insert_sql = sql.SQL(
        "INSERT INTO public.plaintiffs ({columns}) VALUES ({values}) RETURNING id"
    ).format(columns=columns_sql, values=values_sql)

    cur.execute(insert_sql, insert_values)
    created = cur.fetchone()
    if created is None:
        raise RuntimeError("failed to insert plaintiff")
    return str(created[0]), True


def _judgment_exists(
    cur: psycopg.Cursor[Any],
    *,
    judgment_number: str,
    case_number: Optional[str],
) -> bool:
    try:
        cur.execute(
            """
            select 1
            from public.judgments
            where judgment_number = %s
               or case_number = %s
            limit 1
            """,
            (judgment_number, case_number),
        )
    except psycopg_errors.UndefinedColumn:
        cur.execute(
            """
            select 1
            from public.judgments
            where case_number = %s
            limit 1
            """,
            (case_number,),
        )
    return cur.fetchone() is not None


def _insert_judgment(
    cur: psycopg.Cursor[Any],
    *,
    row: SimplicityImportRow,
    plaintiff_id: Optional[str],
    judgment_columns: set[str],
) -> str:
    fields: List[str] = [
        "case_number",
        "plaintiff_name",
        "judgment_amount",
        "entry_date",
    ]
    values: List[Any] = []

    case_number = row.case_number or row.judgment_number
    entry_date = row.judgment_date or row.filing_date or date.today()

    values.extend(
        [
            case_number,
            row.plaintiff_name,
            row.judgment_amount,
            entry_date,
        ]
    )

    optional_fields: List[tuple[str, Any]] = []
    if "plaintiff_id" in judgment_columns and plaintiff_id is not None:
        optional_fields.append(("plaintiff_id", plaintiff_id))
    if "defendant_name" in judgment_columns and row.defendant_name:
        optional_fields.append(("defendant_name", row.defendant_name))
    if "judgment_number" in judgment_columns:
        optional_fields.append(("judgment_number", row.judgment_number))
    if "judgment_date" in judgment_columns and row.judgment_date:
        optional_fields.append(("judgment_date", row.judgment_date))
    if "court_name" in judgment_columns and row.court_name:
        optional_fields.append(("court_name", row.court_name))
    if "county" in judgment_columns and row.county:
        optional_fields.append(("county", row.county))
    if "state" in judgment_columns and row.state:
        optional_fields.append(("state", row.state))

    for column, value in optional_fields:
        fields.append(column)
        values.append(value)

    column_sql = sql.SQL(", ").join(sql.Identifier(col) for col in fields)
    value_sql = sql.SQL(", ").join(sql.Placeholder() for _ in fields)
    insert_sql = sql.SQL(
        "INSERT INTO public.judgments ({columns}) VALUES ({values}) RETURNING id"
    ).format(columns=column_sql, values=value_sql)

    cur.execute(insert_sql, values)
    created = cur.fetchone()
    if created is None:
        raise RuntimeError("failed to insert judgment")
    return str(created[0])


def _insert_status_history(
    cur: psycopg.Cursor[Any],
    *,
    plaintiff_id: str,
    batch_name: str,
    note_prefix: str = "Simplicity import",
    changed_by: str = "simplicity_import",
) -> None:
    note_text = f"{note_prefix} batch {batch_name}".strip()
    cur.execute(
        """
        insert into public.plaintiff_status_history (plaintiff_id, status, note, changed_by)
        values (%s, %s, %s, %s)
        """,
        (
            plaintiff_id,
            "new",
            note_text,
            changed_by,
        ),
    )


def _start_import_run(
    cur: psycopg.Cursor[Any],
    *,
    csv_path: Path,
    batch_name: str,
    dry_run: bool,
    source_reference: str | None,
    import_kind: str = "simplicity_plaintiffs",
    source_system: str = "simplicity",
    created_by: str = "simplicity_import",
) -> str:
    cur.execute(
        """
        insert into public.import_runs (
            import_kind,
            source_system,
            source_reference,
            file_name,
            status,
            started_at,
            metadata,
            row_count,
            insert_count,
            update_count,
            error_count,
            created_by
        )
        values (%s, %s, %s, %s, %s, timezone('utc', now()), %s, 0, 0, 0, 0, %s)
        returning id
        """,
        (
            import_kind,
            source_system,
            source_reference,
            csv_path.name,
            "running",
            Jsonb({"batch_name": batch_name, "dry_run": dry_run}),
            created_by,
        ),
    )
    created = cur.fetchone()
    if created is None:
        raise RuntimeError("failed to record import run")

    import_run_id: Optional[str] = None
    if isinstance(created, dict):
        value = created.get("id")
        import_run_id = str(value) if value is not None else None
    else:
        try:
            import_run_id = str(created[0])
        except (IndexError, KeyError, TypeError):
            import_run_id = None

    if not import_run_id:
        raise RuntimeError("import run insert did not return an id")
    return import_run_id


def _finalize_import_run(
    cur: psycopg.Cursor[Any],
    *,
    import_run_id: str,
    batch_name: str,
    dry_run: bool,
    status: str,
    row_count: int,
    insert_count: int,
    update_count: int,
    error_count: int,
    source_reference: str | None,
    metadata: Dict[str, Any],
) -> None:
    json_metadata = _jsonify_metadata(metadata)
    cur.execute(
        """
        update public.import_runs
        set status = %s,
            finished_at = timezone('utc', now()),
            row_count = %s,
            insert_count = %s,
            update_count = %s,
            error_count = %s,
            metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
        where id = %s
        """,
        (
            status,
            row_count,
            insert_count,
            update_count,
            error_count,
            Jsonb(json_metadata),
            import_run_id,
        ),
    )


def run_simplicity_import(
    csv_path: str,
    batch_name: str,
    dry_run: bool = True,
    source_reference: str | None = None,
    *,
    connection: psycopg.Connection | None = None,
    storage_client: Any | None = None,
    enqueue_jobs: bool = True,
    skip_row_numbers: set[int] | None = None,
    enable_new_pipeline: bool = False,
) -> dict[str, Any]:
    """Parse and reconcile a Simplicity CSV into Supabase domain tables.

    Args:
        csv_path: Path to the Simplicity CSV file.
        batch_name: Label for this import batch.
        dry_run: If True, don't write to the database.
        source_reference: External reference for the import.
        connection: Optional psycopg connection to reuse.
        storage_client: Optional Supabase client for storage uploads.
        enqueue_jobs: If True, enqueue queue_job RPC calls.
        skip_row_numbers: Set of row numbers to skip (for resume support).
        enable_new_pipeline: If True, also insert into core_judgments to
            trigger the new enrichment pipeline via the judgment_enrich queue.
    """

    good_rows = parse_simplicity_csv(csv_path)
    resume_hint: Dict[str, int] | None = None
    requested_skip_rows = {
        row_number
        for row_number in (skip_row_numbers or set())
        if isinstance(row_number, int) and row_number > 0
    }
    if requested_skip_rows:
        original_count = len(good_rows)
        good_rows = [
            row for row in good_rows if (row.raw_row_number or 0) not in requested_skip_rows
        ]
        resume_hint = {
            "requested_skip_rows": len(requested_skip_rows),
            "rows_dropped": max(original_count - len(good_rows), 0),
        }

    source_ref = source_reference or batch_name
    source_system = "simplicity"

    row_operations: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {
        "batch_name": batch_name,
        "source_reference": source_ref,
        "dry_run": dry_run,
        "row_operations": row_operations,
    }
    if resume_hint:
        metadata["resume"] = resume_hint
    metadata["parse_errors"] = [
        {"row_number": issue.row_number, "error": issue.error} for issue in LAST_PARSE_ERRORS
    ]
    parse_errors = metadata["parse_errors"]

    metadata["queued_jobs"] = []
    metadata["raw_import_log"] = {"enabled": False}
    metadata["contact_inserts"] = {"primary": 0, "address": 0}
    metadata["follow_up_tasks"] = {"created": 0, "existing": 0}
    metadata["enforcement_initializations"] = 0
    metadata["core_judgments_bridge"] = {"enabled": enable_new_pipeline}

    if dry_run:
        metadata["planned_storage_path"] = f"simplicity_imports/DRY_RUN/{Path(csv_path).name}"

    row_count = len(good_rows) + len(parse_errors)
    insert_count = 0
    update_count = 0
    skipped_rows = 0
    row_failure_count = 0
    error_count = len(parse_errors)

    db_conn = connection
    managed_connection = False
    if db_conn is None:
        env = get_supabase_env()
        db_url = get_supabase_db_url(env)
        db_conn = psycopg.connect(db_url, autocommit=False)
        managed_connection = True

    import_run_id: Optional[str] = None

    raw_writer: RawImportWriter | None = None
    contact_sync: ContactSync | None = None
    queue_manager: QueueJobManager | None = None
    core_judgment_bridge: CoreJudgmentBridge | None = None

    contact_totals = {"primary": 0, "address": 0}
    follow_up_totals = {"created": 0, "existing": 0}
    enforcement_initializations = 0
    core_judgments_stats = {"inserted": 0, "skipped": 0, "errors": 0}

    def _record_row_status(
        row_model: SimplicityImportRow,
        status: str,
        error: Optional[str] = None,
    ) -> Optional[int]:
        if raw_writer is None:
            return None
        return raw_writer.record(
            row_number=row_model.raw_row_number or 0,
            payload=row_model.model_dump(mode="json"),
            status=status,
            batch_name=batch_name,
            source_system=source_system,
            source_reference=source_ref,
            error=error,
        )

    def _refresh_runtime_metadata() -> None:
        metadata["contact_inserts"] = dict(contact_totals)
        metadata["follow_up_tasks"] = dict(follow_up_totals)
        metadata["enforcement_initializations"] = enforcement_initializations
        metadata["queued_jobs"] = queue_manager.summary() if queue_manager is not None else []
        metadata["raw_import_log"] = (
            raw_writer.summary() if raw_writer is not None else {"enabled": False}
        )
        if core_judgment_bridge is not None:
            metadata["core_judgments_bridge"] = core_judgment_bridge.summary()
        else:
            metadata["core_judgments_bridge"] = {
                "enabled": enable_new_pipeline,
                **core_judgments_stats,
            }

    try:
        if not dry_run:
            with db_conn.cursor() as cur:
                import_run_id = _start_import_run(
                    cur,
                    csv_path=Path(csv_path),
                    batch_name=batch_name,
                    dry_run=dry_run,
                    source_reference=source_ref,
                )
            db_conn.commit()

            supabase_client = storage_client or create_supabase_client(get_supabase_env())
            storage_path = f"simplicity_imports/{import_run_id}/{Path(csv_path).name}"
            try:
                _upload_csv_to_storage(
                    supabase_client=supabase_client,
                    bucket=STORAGE_BUCKET,
                    storage_path=storage_path,
                    csv_path=Path(csv_path),
                )
            except Exception as exc:  # noqa: BLE001
                metadata["upload_error"] = str(exc)
                raise
            else:
                metadata["storage_path"] = storage_path
                with db_conn.cursor() as cur:
                    cur.execute(
                        "update public.import_runs set storage_path = %s where id = %s",
                        (storage_path, import_run_id),
                    )
                db_conn.commit()

            raw_writer = RawImportWriter(db_conn)
            contact_sync = ContactSync(db_conn)
            queue_manager = QueueJobManager(db_conn) if enqueue_jobs else None

            # Initialize core_judgments bridge if new pipeline is enabled
            if enable_new_pipeline:
                core_judgment_bridge = CoreJudgmentBridge(db_conn)
                logger.info(
                    "core_judgments_bridge_enabled batch=%s source=%s",
                    batch_name,
                    source_system,
                )

            if LAST_PARSE_ERRORS:
                for idx, issue in enumerate(LAST_PARSE_ERRORS):
                    record_id = raw_writer.record(
                        row_number=issue.row_number,
                        payload=issue.raw or {},
                        status="parse_error",
                        batch_name=batch_name,
                        source_system=source_system,
                        source_reference=source_ref,
                        error=issue.error,
                    )
                    if idx < len(parse_errors):
                        parse_errors[idx]["raw_import_id"] = record_id

        judgment_columns: set[str] = set()
        if not dry_run:
            judgment_columns = _fetch_columns(db_conn, "judgments")
            if not judgment_columns:
                raise RuntimeError("public.judgments table is not accessible")

        for row in good_rows:
            case_number = row.case_number or row.judgment_number
            operation: Dict[str, Any] = {
                "row_number": row.raw_row_number,
                "case_number": case_number,
                "judgment_number": row.judgment_number,
            }

            with db_conn.cursor() as cur:
                duplicate = _judgment_exists(
                    cur,
                    judgment_number=row.judgment_number,
                    case_number=case_number,
                )
                existing_plaintiff = _find_existing_plaintiff(
                    cur,
                    name=row.plaintiff_name,
                    email=row.plaintiff_email,
                    phone=row.plaintiff_phone,
                )

            if duplicate:
                skipped_rows += 1
                operation["action"] = "skip_existing_judgment"
                operation["status"] = "skipped"
                if not dry_run:
                    operation["raw_import_id"] = _record_row_status(row, "skipped")
                row_operations.append(operation)
                continue

            action_name = (
                "attach_judgment_to_existing_plaintiff"
                if existing_plaintiff
                else "create_plaintiff_and_judgment"
            )
            operation["action"] = action_name
            operation["new_plaintiff"] = existing_plaintiff is None
            if existing_plaintiff:
                operation["existing_plaintiff_id"] = existing_plaintiff["id"]

            if dry_run:
                operation["status"] = "planned"
                row_operations.append(operation)
                continue

            contacts_info: Optional[Dict[str, int]] = None
            follow_up_result: Optional[Dict[str, Any]] = None
            enforcement_set = False
            queued_jobs: List[Dict[str, Any]] = []

            try:
                with db_conn.transaction():
                    with db_conn.cursor() as cur:
                        plaintiff_id, created = _upsert_plaintiff(
                            cur,
                            row,
                            dry_run=False,
                            existing=existing_plaintiff,
                            source_system=source_system,
                        )
                        judgment_id = _insert_judgment(
                            cur,
                            row=row,
                            plaintiff_id=plaintiff_id,
                            judgment_columns=judgment_columns,
                        )
                        if plaintiff_id is not None:
                            _insert_status_history(
                                cur,
                                plaintiff_id=plaintiff_id,
                                batch_name=batch_name,
                            )

                if contact_sync is not None and plaintiff_id is not None:
                    contacts_info = sync_row_contacts(
                        contact_sync,
                        plaintiff_id=plaintiff_id,
                        row=row,
                    )
                    for key, value in contacts_info.items():
                        contact_totals[key] += value

                if plaintiff_id is not None:
                    follow_up_result = ensure_follow_up_task(
                        db_conn,
                        plaintiff_id=plaintiff_id,
                        batch_name=batch_name,
                        created_by="simplicity_import",
                    )
                    if follow_up_result.get("created"):
                        follow_up_totals["created"] += 1
                    else:
                        follow_up_totals["existing"] += 1

                if judgment_id is not None:
                    enforcement_set = initialize_enforcement_stage(
                        db_conn,
                        judgment_id=judgment_id,
                        actor="simplicity_import",
                    )
                    if enforcement_set:
                        enforcement_initializations += 1

                # Insert into core_judgments if new pipeline is enabled
                # This triggers the judgment_enrich queue via DB trigger
                core_judgment_result = None
                if core_judgment_bridge is not None and judgment_id is not None:
                    core_judgment_result = core_judgment_bridge.insert_judgment(
                        case_index_number=case_number,
                        debtor_name=row.defendant_name,
                        original_creditor=row.plaintiff_name,
                        judgment_date=row.judgment_date or row.filing_date,
                        principal_amount=row.judgment_amount,
                        court_name=row.court_name,
                        county=row.county,
                    )
                    if core_judgment_result.inserted:
                        core_judgments_stats["inserted"] += 1
                        operation["core_judgment_id"] = core_judgment_result.judgment_id
                    elif core_judgment_result.skipped:
                        core_judgments_stats["skipped"] += 1
                        operation["core_judgment_skipped"] = True
                        if core_judgment_result.judgment_id:
                            operation["core_judgment_id"] = core_judgment_result.judgment_id
                    elif core_judgment_result.error:
                        core_judgments_stats["errors"] += 1
                        operation["core_judgment_error"] = core_judgment_result.error

                if queue_manager is not None and judgment_id is not None:
                    queued_jobs.append(
                        queue_manager.enqueue(
                            kind="enrich",
                            payload={
                                "plaintiff_id": plaintiff_id,
                                "judgment_id": judgment_id,
                                "source": source_system,
                                "batch_name": batch_name,
                                "source_reference": source_ref,
                            },
                            idempotency_key=f"simplicity:enrich:{judgment_id}",
                        )
                    )
                    queued_jobs.append(
                        queue_manager.enqueue(
                            kind="enforce",
                            payload={
                                "plaintiff_id": plaintiff_id,
                                "judgment_id": judgment_id,
                                "source": source_system,
                                "batch_name": batch_name,
                                "source_reference": source_ref,
                            },
                            idempotency_key=f"simplicity:enforce:{judgment_id}",
                        )
                    )

                insert_count += 1
                operation["status"] = "inserted"
                operation["plaintiff_id"] = plaintiff_id
                operation["judgment_id"] = judgment_id
                operation["new_plaintiff"] = created
            except Exception as exc:  # noqa: BLE001
                row_failure_count += 1
                error_count += 1
                operation["status"] = "error"
                operation["error"] = str(exc)
                logger.exception("simplicity import row failure", exc_info=exc)
            finally:
                if not dry_run:
                    raw_id = _record_row_status(
                        row,
                        operation.get("status", "error"),
                        operation.get("error"),
                    )
                    if raw_id is not None:
                        operation["raw_import_id"] = raw_id

            if contacts_info is not None:
                operation["contacts"] = contacts_info
            if follow_up_result:
                operation["follow_up_task"] = follow_up_result
            operation["enforcement_stage_initialized"] = enforcement_set
            if queued_jobs:
                operation["queued_jobs"] = queued_jobs

            row_operations.append(operation)

        metadata["summary"] = {
            "row_count": row_count,
            "insert_count": insert_count,
            "update_count": update_count,
            "error_count": error_count,
            "skipped_rows": skipped_rows,
            "total_rows": row_count,
            "inserted_rows": insert_count,
            "error_rows": error_count,
        }

        summary_block: Dict[str, Any] = metadata["summary"]
        summary_block["contact_inserts"] = dict(contact_totals)
        summary_block["follow_up_tasks"] = dict(follow_up_totals)
        summary_block["enforcement_initializations"] = enforcement_initializations

        _refresh_runtime_metadata()

        if not dry_run and import_run_id is not None:
            status = "completed"
            with db_conn.cursor() as cur:
                _finalize_import_run(
                    cur,
                    import_run_id=import_run_id,
                    batch_name=batch_name,
                    dry_run=dry_run,
                    status=status,
                    row_count=row_count,
                    insert_count=insert_count,
                    update_count=update_count,
                    error_count=error_count,
                    source_reference=source_ref,
                    metadata=metadata,
                )
            db_conn.commit()
        elif dry_run and managed_connection:
            db_conn.rollback()
    except Exception as exc:
        if managed_connection:
            db_conn.rollback()
            if import_run_id is not None and not dry_run:
                metadata["exception"] = str(exc)
                metadata.setdefault(
                    "summary",
                    {
                        "row_count": row_count,
                        "insert_count": insert_count,
                        "update_count": update_count,
                        "error_count": error_count,
                        "skipped_rows": skipped_rows,
                        "row_failures": row_failure_count,
                        "total_rows": row_count,
                        "inserted_rows": insert_count,
                        "error_rows": error_count,
                    },
                )
                _refresh_runtime_metadata()
                try:
                    with db_conn.cursor() as cur:
                        _finalize_import_run(
                            cur,
                            import_run_id=import_run_id,
                            batch_name=batch_name,
                            dry_run=dry_run,
                            status="failed",
                            row_count=row_count,
                            insert_count=insert_count,
                            update_count=update_count,
                            error_count=error_count,
                            source_reference=source_ref,
                            metadata=metadata,
                        )
                    db_conn.commit()
                except Exception:  # pragma: no cover - best effort
                    db_conn.rollback()
        raise
    finally:
        if managed_connection:
            db_conn.close()

    _refresh_runtime_metadata()
    final_metadata = _jsonify_metadata(metadata)

    return {
        "import_run_id": import_run_id,
        "total_rows": row_count,
        "inserted_rows": insert_count,
        "skipped_rows": skipped_rows,
        "error_rows": error_count,
        "row_count": row_count,
        "insert_count": insert_count,
        "update_count": update_count,
        "error_count": error_count,
        "dry_run": dry_run,
        "metadata": final_metadata,
    }
