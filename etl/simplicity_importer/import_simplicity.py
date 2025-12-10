"""Simplicity importer scaffolding.

Purpose
=======

Transform Simplicity exports (CSV/JSON) into the Dragonfly canonical
tables and bookkeeping structures:

* ``public.plaintiffs`` and ``public.plaintiff_contacts`` receive the
  normalized creditor/representative information.
* ``judgments.cases`` / ``judgments.judgments`` receive case + judgment
  metadata so enforcement + dashboards stay in sync.
* ``public.import_runs`` captures file lineage, parse errors, and row
  level outcomes for QA + replay.

The importer will remain idempotent. Re-running the same source file
should update existing rows (or no-op) rather than duplicating data. All
database writes will be orchestrated via transactions so the workflow is
safe to execute in dev environments while remaining production-ready
through the standard Dragonfly deployment scripts.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.supabase_client import SupabaseEnv, get_supabase_db_url, get_supabase_env

logger = logging.getLogger(__name__)

IMPORT_KIND = "simplicity_plaintiffs"
DEFAULT_SOURCE = "simplicity"
_DECISION_TYPE_CHOICES = {"final", "interlocutory", "summary", "default"}
_DECISION_TYPE_FALLBACK = "final"

# Natural-key summary & assumptions
# ---------------------------------
# - plaintiffs: (source_system, source_reference) is the preferred key,
#   falling back to email, then (source_system, normalized name).
# - judgments.cases: keyed by (source, source_system, case_number, state)
#   so replays touch the same rows instead of duplicating case_ids.
# - judgments.judgments: keyed by (case_id, judgment_date) so repeated
#   imports touch the same legal judgment row regardless of auxiliary
#   metadata like amount or external judgment numbers.
# - plaintiff_contacts: deduped by (plaintiff_id, kind, value) to avoid
#   inserting duplicate email/phone rows on replays.
#
# Assumed Simplicity fields: LeadID, Court, IndexNumber, County, State,
# Status, CaseURL, FilingDate, JudgmentDate, JudgmentAmount, Judgment-
# Number, JudgmentType, RenewalDate, ExpirationDate, Plaintiff/Defendant
# party details, and email/phone contact info.
#
# TODO (schema follow-ups):
# 1. Persist plaintiff mailing addresses as structured contacts once the
#    address contact_type schema is finalized.
# 2. Capture defendant entities via judgments.parties when that importer
#    path is available; the Simplicity DefendantName column is preserved
#    in metadata until then.
# 3. Introduce public.plaintiffs.source_reference (backed by lead_id) so
#    plaintiffs can be deduped without relying on emails or display names.


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _clean_or_none(value: str | None) -> str | None:
    cleaned = _clean(value)
    return cleaned or None


def _normalize_state(value: str | None) -> str | None:
    cleaned = _clean_or_none(value)
    if not cleaned:
        return None
    return cleaned.upper()


def _normalize_decision_type(value: str | None) -> str:
    cleaned = _clean_or_none(value)
    if not cleaned:
        return _DECISION_TYPE_FALLBACK
    lowered = cleaned.lower()
    return lowered if lowered in _DECISION_TYPE_CHOICES else _DECISION_TYPE_FALLBACK


def _normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits or None


def _parse_decimal(value: str | None) -> Decimal | None:
    cleaned = _clean_or_none(value)
    if not cleaned:
        return None
    normalized = cleaned.replace(",", "").replace("$", "")
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid decimal value: {value}") from exc


def _parse_date(value: str | None) -> date | None:
    cleaned = _clean_or_none(value)
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(cleaned).date()
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid date value: {value}") from exc


class RawSimplicityRow(BaseModel):
    """Representation of a single Simplicity export row."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    lead_id: str | None = Field(default=None, alias="LeadID")
    lead_source: str | None = Field(default=None, alias="LeadSource")
    court_name: str | None = Field(default=None, alias="Court")
    index_number: str | None = Field(default=None, alias="IndexNumber")
    judgment_date: str | None = Field(default=None, alias="JudgmentDate")
    judgment_amount: str | None = Field(default=None, alias="JudgmentAmount")
    county: str | None = Field(default=None, alias="County")
    state: str | None = Field(default=None, alias="State")
    plaintiff_name: str | None = Field(default=None, alias="PlaintiffName")
    plaintiff_address: str | None = Field(default=None, alias="PlaintiffAddress")
    plaintiff_city: str | None = Field(default=None, alias="PlaintiffCity")
    plaintiff_state: str | None = Field(default=None, alias="PlaintiffState")
    plaintiff_zip: str | None = Field(default=None, alias="PlaintiffZip")
    phone: str | None = Field(default=None, alias="Phone")
    email: str | None = Field(default=None, alias="Email")
    best_contact_method: str | None = Field(default=None, alias="BestContactMethod")
    case_title: str | None = Field(default=None, alias="CaseTitle")
    case_type: str | None = Field(default=None, alias="CaseType")
    case_status: str | None = Field(default=None, alias="Status")
    case_url: str | None = Field(default=None, alias="CaseURL")
    filing_date: str | None = Field(default=None, alias="FilingDate")
    judgment_number: str | None = Field(default=None, alias="JudgmentNumber")
    judgment_type: str | None = Field(default=None, alias="JudgmentType")
    renewal_date: str | None = Field(default=None, alias="RenewalDate")
    expiration_date: str | None = Field(default=None, alias="ExpirationDate")
    defendant_name: str | None = Field(default=None, alias="DefendantName")
    metadata: dict[str, Any] | None = None

    def as_metadata(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.lead_id:
            payload["lead_id"] = self.lead_id
        if self.lead_source:
            payload["lead_source"] = self.lead_source
        if self.metadata:
            payload.update(self.metadata)
        return payload


class NormalizedPlaintiff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    firm_name: str | None = None
    email: str | None = None
    phone: str | None = None
    status: str = "new"
    source_system: str
    tier: str | None = "unknown"

    @classmethod
    def from_raw(cls, raw: RawSimplicityRow, *, source_system: str) -> "NormalizedPlaintiff":
        name = _clean_or_none(raw.plaintiff_name) or _clean_or_none(raw.case_title)
        if not name:
            identifier = raw.index_number or raw.lead_id
            if not identifier:
                raise ValueError("plaintiff name missing")
            name = identifier
        email = _clean_or_none(raw.email)
        phone = _normalize_phone(raw.phone)
        return cls(
            name=name,
            firm_name=_clean_or_none(raw.plaintiff_name),
            email=email,
            phone=phone,
            source_system=source_system,
        )


class NormalizedCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_number: str
    docket_number: str
    title: str
    state: str | None = None
    county: str | None = None
    court_name: str | None = None
    case_type: str | None = None
    case_status: str | None = None
    case_url: str | None = None
    filing_date: date | None = None
    judgment_date: date | None = None
    amount_awarded: Decimal | None = None
    source: str
    source_system: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_raw(
        cls,
        raw: RawSimplicityRow,
        *,
        source_system: str,
        default_source: str | None = None,
    ) -> "NormalizedCase":
        case_number = (
            _clean_or_none(raw.index_number)
            or _clean_or_none(raw.judgment_number)
            or _clean_or_none(raw.lead_id)
        )
        if not case_number:
            raise ValueError("case_number missing")
        docket_number = _clean_or_none(raw.index_number) or case_number
        title = _clean_or_none(raw.case_title) or case_number
        return cls(
            case_number=case_number,
            docket_number=docket_number,
            title=title,
            state=_normalize_state(raw.state or raw.plaintiff_state),
            county=_clean_or_none(raw.county),
            court_name=_clean_or_none(raw.court_name),
            case_type=_clean_or_none(raw.case_type),
            case_status=_clean_or_none(raw.case_status),
            case_url=_clean_or_none(raw.case_url),
            filing_date=_parse_date(raw.filing_date),
            judgment_date=_parse_date(raw.judgment_date),
            amount_awarded=_parse_decimal(raw.judgment_amount),
            source=default_source or source_system,
            source_system=source_system,
            metadata={"simplicity": raw.as_metadata()},
        )


class NormalizedJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    judgment_number: str
    judgment_date: date
    amount: Decimal
    amount_awarded: Decimal | None = None
    amount_remaining: Decimal | None = None
    judgment_type: str | None = None
    judgment_status: str = "unsatisfied"
    status: str = "unsatisfied"
    interest_rate: Decimal | None = None
    renewal_date: date | None = None
    expiration_date: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_raw(
        cls,
        raw: RawSimplicityRow,
        *,
        source_system: str,
    ) -> "NormalizedJudgment":
        judgment_number = (
            _clean_or_none(raw.judgment_number)
            or _clean_or_none(raw.index_number)
            or _clean_or_none(raw.lead_id)
        )
        if not judgment_number:
            raise ValueError("judgment_number missing")
        judgment_date = _parse_date(raw.judgment_date)
        if not judgment_date:
            raise ValueError("judgment_date missing")
        amount = _parse_decimal(raw.judgment_amount)
        if amount is None:
            raise ValueError("judgment amount missing")
        metadata = {"simplicity": raw.as_metadata(), "source_system": source_system}
        return cls(
            judgment_number=judgment_number,
            judgment_date=judgment_date,
            amount=amount,
            amount_awarded=amount,
            amount_remaining=amount,
            judgment_type=_clean_or_none(raw.judgment_type),
            renewal_date=_parse_date(raw.renewal_date),
            expiration_date=_parse_date(raw.expiration_date),
            metadata=metadata,
        )


class NormalizedContact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    email: str | None = None
    phone: str | None = None
    role: str | None = None
    kind: str | None = None
    value: str | None = None

    @classmethod
    def from_raw(cls, raw: RawSimplicityRow, *, channel: str) -> Optional["NormalizedContact"]:
        contact_name = _clean_or_none(raw.plaintiff_name) or "Simplicity Contact"
        role = _clean_or_none(raw.best_contact_method)
        if channel == "email":
            email = _clean_or_none(raw.email)
            if not email:
                return None
            return cls(name=contact_name, email=email, role=role, kind="email", value=email)
        if channel == "phone":
            normalized_phone = _normalize_phone(raw.phone)
            if not normalized_phone:
                return None
            return cls(
                name=contact_name,
                phone=raw.phone,
                role=role,
                kind="phone",
                value=normalized_phone,
            )
        return None


def _build_contacts(raw: RawSimplicityRow) -> list[NormalizedContact]:
    contacts: list[NormalizedContact] = []
    for channel in ("email", "phone"):
        contact = NormalizedContact.from_raw(raw, channel=channel)
        if contact is not None:
            contacts.append(contact)
    return contacts


def _load_simplicity_rows(csv_path: str | Path) -> list[RawSimplicityRow]:
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {path}")

    rows: list[RawSimplicityRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("Simplicity CSV requires a header row")
        for index, raw in enumerate(reader, start=2):
            if not raw:
                continue
            if not any(value and value.strip() for value in raw.values() if value):
                continue
            try:
                rows.append(RawSimplicityRow.model_validate(raw))
            except ValidationError as exc:
                raise ValueError(f"Row {index} failed validation: {exc}") from exc
    if not rows:
        raise ValueError("Simplicity CSV did not contain any rows")
    return rows


def _normalize_row(
    raw: RawSimplicityRow, *, source_system: str, default_source: str = DEFAULT_SOURCE
) -> tuple[
    NormalizedPlaintiff,
    NormalizedCase,
    NormalizedJudgment,
    list[NormalizedContact],
]:
    plaintiff = NormalizedPlaintiff.from_raw(raw, source_system=source_system)
    case = NormalizedCase.from_raw(raw, source_system=source_system, default_source=default_source)
    judgment = NormalizedJudgment.from_raw(raw, source_system=source_system)
    contacts = _build_contacts(raw)
    return plaintiff, case, judgment, contacts


@dataclass(slots=True)
class RowOutcome:
    inserted: bool = False
    updated: bool = False


def _jsonify_metadata(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_jsonify_metadata(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonify_metadata(item) for key, item in value.items()}
    return value


def _resolve_source_reference(raw: RawSimplicityRow) -> str | None:
    candidates = (
        raw.lead_id,
        raw.index_number,
        raw.judgment_number,
        raw.case_title,
    )
    for candidate in candidates:
        cleaned = _clean_or_none(candidate)
        if cleaned:
            return cleaned
    return None


def _table_identifier(schema: str | None, table: str) -> sql.Identifier:
    return sql.Identifier(schema, table) if schema else sql.Identifier(table)


def _insert_row_returning(
    conn: psycopg.Connection,
    *,
    schema: str | None,
    table: str,
    columns: dict[str, Any],
    returning: str = "id",
) -> Any:
    if not columns:
        raise ValueError("Cannot insert a row without columns")
    table_sql = _table_identifier(schema, table)
    column_sql = sql.SQL(", ").join(sql.Identifier(name) for name in columns.keys())
    values_sql = sql.SQL(", ").join(sql.Placeholder() for _ in columns)
    returning_sql = sql.Identifier(returning)
    query = sql.SQL(
        "INSERT INTO {table} ({columns}) VALUES ({values}) RETURNING {returning}"
    ).format(
        table=table_sql,
        columns=column_sql,
        values=values_sql,
        returning=returning_sql,
    )
    params = [columns[name] for name in columns.keys()]
    with conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
    if not row:
        raise RuntimeError("INSERT ... RETURNING did not yield a row")
    return row[0]


def _select_existing_plaintiff_id(
    conn: psycopg.Connection,
    *,
    source_system: str,
    source_reference: str | None,
    name: str,
    email: str | None,
) -> str | None:
    with conn.cursor() as cur:
        if source_reference:
            cur.execute(
                """
                SELECT id
                FROM public.plaintiffs
                WHERE source_system = %s
                  AND source_reference = %s
                LIMIT 1
                """,
                (source_system, source_reference),
            )
            row = cur.fetchone()
            if row:
                return row[0]
        cur.execute(
            """
            SELECT id
            FROM public.plaintiffs
            WHERE source_system = %s
              AND name = %s
            LIMIT 1
            """,
            (source_system, name),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        if email:
            cur.execute(
                """
                SELECT id
                FROM public.plaintiffs
                WHERE source_system = %s
                  AND email = %s
                LIMIT 1
                """,
                (source_system, email),
            )
            row = cur.fetchone()
            if row:
                return row[0]
    return None


def _plaintiff_metadata(raw: RawSimplicityRow) -> dict[str, Any]:
    payload = raw.model_dump(mode="json", exclude_none=True)
    return {"simplicity": payload}


def _upsert_plaintiff(
    conn: psycopg.Connection,
    *,
    plaintiff: NormalizedPlaintiff,
    raw: RawSimplicityRow,
    source_reference: str | None,
) -> tuple[str, bool]:
    metadata = Jsonb(_jsonify_metadata(_plaintiff_metadata(raw)))
    existing_id = _select_existing_plaintiff_id(
        conn,
        source_system=plaintiff.source_system,
        source_reference=source_reference,
        name=plaintiff.name,
        email=plaintiff.email,
    )

    if existing_id:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.plaintiffs
                SET name = %s,
                    firm_name = %s,
                    email = COALESCE(%s, email),
                    phone = COALESCE(%s, phone),
                    source_reference = COALESCE(source_reference, %s),
                    lead_metadata = COALESCE(lead_metadata, '{}'::jsonb) || %s,
                    updated_at = timezone('utc', now())
                WHERE id = %s
                """,
                (
                    plaintiff.name,
                    plaintiff.firm_name,
                    plaintiff.email,
                    plaintiff.phone,
                    source_reference,
                    metadata,
                    existing_id,
                ),
            )
        return existing_id, False

    columns = {
        "name": plaintiff.name,
        "firm_name": plaintiff.firm_name,
        "email": plaintiff.email,
        "phone": plaintiff.phone,
        "status": plaintiff.status,
        "source_system": plaintiff.source_system,
        "tier": plaintiff.tier,
        "source_reference": source_reference,
        "lead_metadata": metadata,
    }
    plaintiff_id = _insert_row_returning(
        conn,
        schema="public",
        table="plaintiffs",
        columns=columns,
    )
    return plaintiff_id, True


def _select_case_id(
    conn: psycopg.Connection,
    *,
    source_system: str,
    source: str,
    case_number: str,
    state: str | None,
) -> str | None:
    """Return an existing case id using the database uniqueness contracts."""

    clauses = [
        (
            sql.SQL(
                """
                SELECT id
                FROM judgments.cases
                WHERE source_system = %s
                  AND case_number = %s
                  AND COALESCE(state, '') = COALESCE(%s, '')
                LIMIT 1
                """
            ),
            (source_system, case_number, state),
        ),
        (
            sql.SQL(
                """
                SELECT id
                FROM judgments.cases
                WHERE source = %s
                  AND case_number = %s
                  AND COALESCE(state, '') = COALESCE(%s, '')
                LIMIT 1
                """
            ),
            (source, case_number, state),
        ),
    ]
    with conn.cursor() as cur:
        for query, params in clauses:
            cur.execute(query, params)
            row = cur.fetchone()
            if row:
                return row[0]
    return None


def _case_metadata(case: NormalizedCase, raw: RawSimplicityRow) -> dict[str, Any]:
    payload = case.model_dump(mode="json", exclude_none=True)
    payload.setdefault("simplicity", raw.as_metadata())
    payload["raw_row"] = raw.model_dump(mode="json", exclude_none=True)
    return payload


def _upsert_case(
    conn: psycopg.Connection,
    *,
    case: NormalizedCase,
    raw: RawSimplicityRow,
    source_reference: str | None,
) -> tuple[str, bool]:
    metadata = Jsonb(_jsonify_metadata(_case_metadata(case, raw)))
    existing_id = _select_case_id(
        conn,
        source_system=case.source_system,
        source=case.source,
        case_number=case.case_number,
        state=case.state,
    )

    amount_awarded = case.amount_awarded

    raw_json = Jsonb(_jsonify_metadata(raw.model_dump(mode="json", exclude_none=True)))

    if existing_id:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE judgments.cases
                SET title = %s,
                    county = COALESCE(%s, county),
                    court_name = COALESCE(%s, court_name),
                    case_type = COALESCE(%s, case_type),
                    case_status = COALESCE(%s, case_status),
                    case_url = COALESCE(%s, case_url),
                    filing_date = COALESCE(%s, filing_date),
                    judgment_date = COALESCE(%s, judgment_date),
                    docket_number = COALESCE(docket_number, %s),
                    case_id = id,
                    source_system = %s,
                    amount_awarded = COALESCE(%s, amount_awarded),
                    metadata = COALESCE(metadata, '{}'::jsonb) || %s,
                    raw = %s,
                    updated_at = timezone('utc', now())
                WHERE id = %s
                """,
                (
                    case.title,
                    case.county,
                    case.court_name,
                    case.case_type,
                    case.case_status,
                    case.case_url,
                    case.filing_date,
                    case.judgment_date,
                    case.docket_number,
                    case.source_system,
                    amount_awarded,
                    metadata,
                    raw_json,
                    existing_id,
                ),
            )
        return existing_id, False

    case_uuid = uuid4()
    columns = {
        "id": case_uuid,
        "case_id": case_uuid,
        "case_number": case.case_number,
        "docket_number": case.docket_number,
        "title": case.title,
        "state": case.state,
        "county": case.county,
        "court_name": case.court_name,
        "case_type": case.case_type,
        "case_status": case.case_status,
        "case_url": case.case_url,
        "filing_date": case.filing_date,
        "judgment_date": case.judgment_date,
        "amount_awarded": amount_awarded,
        "source": case.source,
        "source_system": case.source_system,
        "metadata": metadata,
        "raw": raw_json,
        "index_no": case.case_number,
        "source_url": case.case_url,
        "external_id": source_reference,
    }
    case_id = _insert_row_returning(
        conn,
        schema="judgments",
        table="cases",
        columns=columns,
    )
    return case_id, True


#! judgments.judgments schema:
# - id: uuid
# - case_id: uuid
# - judgment_date: date
# - decision_type: varchar
# - outcome: text
# - presiding_judge: varchar
# - summary: text
# - full_text: text
# - precedent_value: varchar
# - citations: text[]
# - metadata: jsonb
# - created_at: timestamptz
# - updated_at: timestamptz


def _select_judgment_id_sql(
    conn: psycopg.Connection,
    *,
    case_id: str,
    judgment: NormalizedJudgment,
) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM judgments.judgments
            WHERE case_id = %s
              AND judgment_date = %s
            LIMIT 1
            """,
            (case_id, judgment.judgment_date),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _judgment_metadata(judgment: NormalizedJudgment, raw: RawSimplicityRow) -> dict[str, Any]:
    payload = judgment.model_dump(mode="json", exclude_none=True)
    payload.setdefault("simplicity", raw.as_metadata())
    payload["judgment_number"] = judgment.judgment_number
    payload["amount_awarded"] = str(judgment.amount_awarded or judgment.amount)
    return payload


def _upsert_judgment(
    conn: psycopg.Connection,
    *,
    judgment: NormalizedJudgment,
    raw: RawSimplicityRow,
    case_id: str,
) -> tuple[str, bool]:
    metadata = Jsonb(_jsonify_metadata(_judgment_metadata(judgment, raw)))
    existing_id = _select_judgment_id_sql(
        conn,
        case_id=case_id,
        judgment=judgment,
    )

    decision_type = _normalize_decision_type(judgment.judgment_type)
    outcome = judgment.judgment_status or judgment.status
    presiding_judge: str | None = None
    summary: str | None = None

    if existing_id:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE judgments.judgments
                SET decision_type = %s,
                    outcome = %s,
                    judgment_number = COALESCE(%s, judgment_number),
                    metadata = COALESCE(metadata, '{}'::jsonb) || %s,
                    updated_at = timezone('utc', now())
                WHERE id = %s
                """,
                (
                    decision_type,
                    outcome,
                    judgment.judgment_number,
                    metadata,
                    existing_id,
                ),
            )
        return existing_id, False

    insert_columns: dict[str, Any] = {
        "case_id": case_id,
        "judgment_date": judgment.judgment_date,
        "decision_type": decision_type,
        "outcome": outcome,
        "judgment_number": judgment.judgment_number,
        "presiding_judge": presiding_judge,
        "summary": summary,
        "metadata": metadata,
    }

    judgment_id = _insert_row_returning(
        conn,
        schema="judgments",
        table="judgments",
        columns=insert_columns,
    )
    return judgment_id, True


def _sync_contacts(
    conn: psycopg.Connection,
    *,
    plaintiff_id: str,
    contacts: list[NormalizedContact],
) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    with conn.cursor() as cur:
        for contact in contacts:
            if not contact.value:
                continue
            cur.execute(
                """
                SELECT id
                FROM public.plaintiff_contacts
                WHERE plaintiff_id = %s
                  AND kind = %s
                  AND value = %s
                LIMIT 1
                """,
                (plaintiff_id, contact.kind, contact.value),
            )
            if cur.fetchone():
                skipped += 1
                continue
            cur.execute(
                """
                INSERT INTO public.plaintiff_contacts
                    (plaintiff_id, name, email, phone, role, kind, value)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    plaintiff_id,
                    contact.name,
                    contact.email,
                    contact.phone,
                    contact.role,
                    contact.kind,
                    contact.value,
                ),
            )
            inserted += 1
    return inserted, skipped


def _start_import_run(
    conn: psycopg.Connection,
    *,
    import_kind: str,
    source_system: str,
    source: str,
    total_rows: int,
    file_name: str,
    source_reference: str | None,
) -> str:
    started_at = datetime.now(timezone.utc)
    metadata = Jsonb(_jsonify_metadata({"skipped_rows": 0, "updated_rows": 0}))
    columns = {
        "import_kind": import_kind,
        "source_system": source_system,
        "source_reference": source_reference,
        "file_name": file_name,
        "storage_path": None,
        "status": "running",
        "total_rows": total_rows,
        "row_count": 0,
        "insert_count": 0,
        "update_count": 0,
        "error_count": 0,
        "started_at": started_at,
        "metadata": metadata,
        "source": source,
    }
    return _insert_row_returning(
        conn,
        schema="public",
        table="import_runs",
        columns=columns,
    )


def _finalize_import_run(
    conn: psycopg.Connection,
    *,
    run_id: str,
    status: str,
    stats: dict[str, int],
    errors: list[dict[str, Any]],
) -> None:
    finished_at = datetime.now(timezone.utc)
    metadata_payload: dict[str, Any] = {
        "skipped_rows": stats.get("skipped_rows", 0),
        "updated_rows": stats.get("updated_rows", 0),
    }
    if errors:
        metadata_payload["errors"] = errors[:50]
    metadata = Jsonb(_jsonify_metadata(metadata_payload))
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE public.import_runs
            SET status = %s,
                row_count = %s,
                insert_count = %s,
                update_count = %s,
                error_count = %s,
                finished_at = %s,
                metadata = COALESCE(metadata, '{}'::jsonb) || %s
            WHERE id = %s
            """,
            (
                status,
                stats.get("row_count", 0),
                stats.get("insert_count", 0),
                stats.get("update_count", 0),
                stats.get("error_count", 0),
                finished_at,
                metadata,
                run_id,
            ),
        )


def _process_row(
    conn: psycopg.Connection,
    *,
    raw: RawSimplicityRow,
    source_system: str,
) -> RowOutcome:
    source_reference = _resolve_source_reference(raw)
    plaintiff, case, judgment, contacts = _normalize_row(raw, source_system=source_system)

    plaintiff_id, plaintiff_inserted = _upsert_plaintiff(
        conn,
        plaintiff=plaintiff,
        raw=raw,
        source_reference=source_reference,
    )
    case_id, case_inserted = _upsert_case(
        conn,
        case=case,
        raw=raw,
        source_reference=source_reference,
    )
    _, judgment_inserted = _upsert_judgment(
        conn,
        judgment=judgment,
        raw=raw,
        case_id=case_id,
    )
    _sync_contacts(conn, plaintiff_id=plaintiff_id, contacts=contacts)

    inserted = plaintiff_inserted or case_inserted or judgment_inserted
    return RowOutcome(inserted=inserted, updated=not inserted)


def import_simplicity_batch(
    csv_path: str,
    *,
    source_system: str | None = None,
    supabase_env: SupabaseEnv | None = None,
) -> None:
    rows = _load_simplicity_rows(csv_path)
    env = supabase_env or get_supabase_env()
    resolved_system = source_system or f"{DEFAULT_SOURCE}_{env}"
    db_url = get_supabase_db_url(env)
    file_name = Path(csv_path).name

    stats = {
        "row_count": 0,
        "insert_count": 0,
        "update_count": 0,
        "error_count": 0,
        "skipped_rows": 0,
        "updated_rows": 0,
    }
    errors: list[dict[str, Any]] = []

    logger.info(
        "Starting Simplicity import",
        extra={"rows": len(rows), "source_system": resolved_system},
    )

    with psycopg.connect(db_url, autocommit=True) as conn:
        run_id = _start_import_run(
            conn,
            import_kind=IMPORT_KIND,
            source_system=resolved_system,
            source=DEFAULT_SOURCE,
            total_rows=len(rows),
            file_name=file_name,
            source_reference=file_name,
        )
        status = "completed"
        try:
            for index, raw in enumerate(rows, start=1):
                try:
                    with conn.transaction():
                        outcome = _process_row(
                            conn,
                            raw=raw,
                            source_system=resolved_system,
                        )
                    stats["row_count"] += 1
                    if outcome.inserted:
                        stats["insert_count"] += 1
                    else:
                        stats["update_count"] += 1
                        stats["updated_rows"] += 1
                except Exception as row_exc:  # pragma: no cover - defensive transactional guard
                    stats["error_count"] += 1
                    stats["skipped_rows"] += 1
                    error_entry = {"row": index, "error": str(row_exc)}
                    errors.append(error_entry)
                    logger.exception("Failed to process Simplicity row %s", index)
            if stats["error_count"]:
                status = "completed_with_errors"
        except Exception as exc:  # pragma: no cover - catastrophic failure
            status = "failed"
            stats["error_count"] += 1
            errors.append({"stage": "batch", "error": str(exc)})
            logger.exception("Simplicity import failed: %s", exc)
            raise
        finally:
            _finalize_import_run(
                conn,
                run_id=run_id,
                status=status,
                stats=stats,
                errors=errors,
            )
