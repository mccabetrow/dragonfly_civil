"""Shared helpers for Simplicity/JBI importer pipelines.

These utilities keep all production ETL entrypoints aligned on how we log raw
rows, hydrate plaintiff contacts, seed follow-up tasks, set enforcement stages,
and enqueue downstream jobs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb


def _normalize_email(value: Optional[str]) -> Optional[str]:
    return value.strip().lower() if value else None


def _normalize_phone(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits or None


def _jsonify(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonify(v) for v in value]
    return value


class RawImportWriter:
    """Best-effort logger for raw import rows and errors."""

    def __init__(
        self,
        conn: psycopg.Connection,
        table_candidates: Sequence[Tuple[str, str]] | None = None,
    ) -> None:
        self.conn = conn
        self.table_candidates = table_candidates or [
            ("public", "raw_simplicity_imports"),
            ("public", "raw_import_log"),
        ]
        self.table: Tuple[str, str] | None = self._detect_table()
        self.rows_written = 0
        self.failures: List[str] = []

    def _detect_table(self) -> Tuple[str, str] | None:
        query = sql.SQL(
            """
            select 1
            from information_schema.tables
            where table_schema = %s and table_name = %s
            limit 1
            """
        )
        for schema, table in self.table_candidates:
            with self.conn.cursor() as cur:
                cur.execute(query, (schema, table))
                if cur.fetchone():
                    return (schema, table)
        return None

    @property
    def enabled(self) -> bool:
        return self.table is not None

    @property
    def table_fqn(self) -> Optional[str]:
        if not self.table:
            return None
        return f"{self.table[0]}.{self.table[1]}"

    def record(
        self,
        *,
        row_number: int,
        payload: Dict[str, Any],
        status: str,
        batch_name: Optional[str] = None,
        source_system: Optional[str] = None,
        source_reference: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Optional[int]:
        if not self.enabled:
            if error:
                self.failures.append(error)
            return None

        record = {
            "row_number": row_number,
            "batch_name": batch_name,
            "source_system": source_system,
            "source_reference": source_reference,
            "payload": _jsonify(payload),
        }
        error_payload = {"message": error} if error else None
        assert self.table is not None  # guarded by enabled check
        insert_query = sql.SQL(
            """
            insert into {}.{} (raw_data, imported_at, status, error_log)
            values (%s, timezone('utc', now()), %s, %s)
            returning id
            """
        ).format(sql.Identifier(self.table[0]), sql.Identifier(self.table[1]))

        with self.conn.cursor() as cur:
            cur.execute(
                insert_query,
                (
                    Jsonb(record),
                    status,
                    Jsonb(error_payload) if error_payload else None,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            inserted_id: int = row[0]
        self.rows_written += 1
        return inserted_id

    def summary(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "table": self.table_fqn,
            "rows_written": self.rows_written,
            "failures": self.failures,
        }


class QueueJobManager:
    """Helper that wraps queue_job RPC calls and collects job metadata."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn
        self.available = self._check_available()
        self.jobs: List[Dict[str, Any]] = []

    def _check_available(self) -> bool:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                select 1
                from information_schema.routines
                where routine_schema = 'public' and routine_name = 'queue_job'
                limit 1
                """
            )
            return cur.fetchone() is not None

    def enqueue(
        self,
        *,
        kind: str,
        payload: Dict[str, Any],
        idempotency_key: str,
    ) -> Dict[str, Any]:
        job_meta: Dict[str, Any] = {
            "kind": kind,
            "idempotency_key": idempotency_key,
        }
        if not self.available:
            job_meta["status"] = "skipped"
            job_meta["reason"] = "queue_job RPC missing"
            self.jobs.append(job_meta)
            return job_meta

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "select public.queue_job(%s)",
                    (
                        Jsonb(
                            {
                                "kind": kind,
                                "payload": payload,
                                "idempotency_key": idempotency_key,
                            }
                        ),
                    ),
                )
                row = cur.fetchone()
                assert row is not None
                message_id: int = row[0]
                job_meta["status"] = "queued"
                job_meta["message_id"] = message_id
        except Exception as exc:  # noqa: BLE001 - bubble details into metadata
            job_meta["status"] = "error"
            job_meta["error"] = str(exc)
        self.jobs.append(job_meta)
        return job_meta

    def summary(self) -> List[Dict[str, Any]]:
        return self.jobs


@dataclass(slots=True)
class ContactLedger:
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    kv_pairs: set[Tuple[Optional[str], str]] = field(default_factory=set)


class ContactSync:
    """Minimal contact upsert helper with de-dup support."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn
        self._columns = self._fetch_columns()
        self._cache: Dict[str, ContactLedger] = {}

    def _fetch_columns(self) -> set[str]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                select column_name
                from information_schema.columns
                where table_schema = 'public' and table_name = 'plaintiff_contacts'
                """
            )
            return {row[0] for row in cur.fetchall()}

    def _ledger_for(self, plaintiff_id: str) -> ContactLedger:
        if plaintiff_id in self._cache:
            return self._cache[plaintiff_id]
        ledger = ContactLedger()
        with self.conn.cursor() as cur:
            cur.execute(
                """
                select lower(nullif(email, '')) as email,
                       regexp_replace(coalesce(phone, ''), '\\D', '', 'g') as phone,
                       kind,
                       coalesce(value, '') as value
                from public.plaintiff_contacts
                where plaintiff_id = %s
                """,
                (plaintiff_id,),
            )
            for email, phone, kind, value in cur.fetchall():
                if email:
                    ledger.emails.add(email)
                if phone:
                    ledger.phones.add(phone)
                if value:
                    ledger.kv_pairs.add((kind, value.strip().lower()))
        self._cache[plaintiff_id] = ledger
        return ledger

    def ensure_contact(
        self,
        plaintiff_id: str,
        *,
        name: str,
        role: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        kind: Optional[str] = None,
        value: Optional[str] = None,
    ) -> Optional[int]:
        normalized_email = _normalize_email(email)
        normalized_phone = _normalize_phone(phone)
        normalized_value = value.strip().lower() if value else None

        if not any([normalized_email, normalized_phone, normalized_value]):
            return None

        ledger = self._ledger_for(plaintiff_id)
        if normalized_email and normalized_email in ledger.emails:
            normalized_email = None
        if normalized_phone and normalized_phone in ledger.phones:
            normalized_phone = None
        if normalized_value and (kind, normalized_value) in ledger.kv_pairs:
            normalized_value = None

        if not any([normalized_email, normalized_phone, normalized_value]):
            return None

        columns = ["plaintiff_id", "name", "role"]
        values: List[Any] = [plaintiff_id, name, role]
        if "email" in self._columns:
            columns.append("email")
            values.append(email if normalized_email else None)
        if "phone" in self._columns:
            columns.append("phone")
            values.append(phone if normalized_phone else None)
        if normalized_value is not None and "value" in self._columns:
            columns.append("value")
            values.append(value)
        if kind and "kind" in self._columns:
            columns.append("kind")
            values.append(kind)

        insert_query = sql.SQL(
            """
            insert into public.plaintiff_contacts ({cols})
            values ({placeholders})
            returning id
            """
        ).format(
            cols=sql.SQL(", ").join(sql.Identifier(col) for col in columns),
            placeholders=sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        )

        with self.conn.cursor() as cur:
            cur.execute(insert_query, values)
            row = cur.fetchone()
            assert row is not None
            contact_id: int = row[0]

        ledger = self._ledger_for(plaintiff_id)
        if normalized_email:
            ledger.emails.add(normalized_email)
        if normalized_phone:
            ledger.phones.add(normalized_phone)
        if normalized_value is not None:
            ledger.kv_pairs.add((kind, normalized_value))
        return contact_id


FOLLOW_UP_TASK_KIND = "call"


def ensure_follow_up_task(
    conn: psycopg.Connection,
    *,
    plaintiff_id: str,
    batch_name: str,
    created_by: str,
    due_in_days: int = 7,
) -> Dict[str, Any]:
    """Create or fetch a follow-up call task and describe the outcome."""

    with conn.cursor() as cur:
        cur.execute(
            """
            select id
            from public.plaintiff_tasks
            where plaintiff_id = %s and kind = %s and status = 'open'
            order by created_at asc
            limit 1
            """,
            (plaintiff_id, FOLLOW_UP_TASK_KIND),
        )
        existing = cur.fetchone()
        if existing:
            return {"id": str(existing[0]), "created": False}

        cur.execute(
            """
            insert into public.plaintiff_tasks (
                plaintiff_id,
                kind,
                status,
                due_at,
                note,
                created_by,
                metadata
            )
            values (
                %s,
                %s,
                'open',
                timezone('utc', now()) + (%s || ' days')::interval,
                %s,
                %s,
                %s
            )
            returning id
            """,
            (
                plaintiff_id,
                FOLLOW_UP_TASK_KIND,
                due_in_days,
                f"Automated outreach task for batch {batch_name}",
                created_by,
                Jsonb(
                    {
                        "batch_name": batch_name,
                        "source": "importer",
                    }
                ),
            ),
        )
        created_row = cur.fetchone()
        if created_row is None:
            return {"id": None, "created": True}
        return {"id": str(created_row[0]), "created": True}


def initialize_enforcement_stage(
    conn: psycopg.Connection,
    *,
    judgment_id: str,
    actor: str,
    note: str = "Importer initialization",
    stage: str = "pre_enforcement",
) -> bool:
    """Ensure the judgment has a starting enforcement stage."""

    with conn.cursor() as cur:
        try:
            cur.execute(
                "select public.set_enforcement_stage(%s, %s, %s, %s)",
                (judgment_id, stage, note, actor),
            )
            cur.fetchone()
            return True
        except psycopg.errors.UndefinedFunction:
            cur.execute(
                """
                update public.judgments
                set enforcement_stage = %s,
                    enforcement_stage_updated_at = timezone('utc', now())
                where id = %s
                returning id
                """,
                (stage, judgment_id),
            )
            return bool(cur.fetchone())


def sync_row_contacts(
    contact_sync: ContactSync,
    *,
    plaintiff_id: str,
    row: Any,
) -> Dict[str, int]:
    """Insert the primary + address contacts for the row if missing."""

    inserted = {"primary": 0, "address": 0}
    name = getattr(row, "plaintiff_name", None) or "Unknown"
    primary_id = contact_sync.ensure_contact(
        plaintiff_id,
        name=name,
        role="primary",
        email=getattr(row, "plaintiff_email", None),
        phone=getattr(row, "plaintiff_phone", None),
    )
    if primary_id:
        inserted["primary"] = 1

    address_parts = [
        getattr(row, "plaintiff_address_1", None),
        getattr(row, "plaintiff_address_2", None),
        getattr(row, "plaintiff_city", None),
        getattr(row, "plaintiff_state", None),
        getattr(row, "plaintiff_zip", None),
    ]
    address_value = ", ".join(part for part in address_parts if part)
    if address_value:
        address_id = contact_sync.ensure_contact(
            plaintiff_id,
            name=f"{name} address",
            role="address",
            kind="address",
            value=address_value,
        )
        if address_id:
            inserted["address"] = 1
    return inserted


__all__ = [
    "ContactLedger",
    "ContactSync",
    "QueueJobManager",
    "RawImportWriter",
    "ensure_follow_up_task",
    "initialize_enforcement_stage",
    "sync_row_contacts",
]
