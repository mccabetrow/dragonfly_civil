from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Tuple

import psycopg2
from psycopg2.extras import Json

logger = logging.getLogger(__name__)


def _json(value: Any) -> Any:
    return Json(value) if value is not None else None


def _execute_upsert(
    conn: psycopg2.extensions.connection,
    sql: str,
    params: Mapping[str, Any],
) -> Tuple[str, bool]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        record = cur.fetchone()
        if not record:
            raise RuntimeError("Upsert failed to return identifier")
        record_id, inserted = record
        logger.debug("upsert result id=%s inserted=%s", record_id, inserted)
        return str(record_id), bool(inserted)


CASE_UPSERT_SQL = """
    INSERT INTO judgments.cases (
        case_number, court_name, county, state, case_type, filing_date,
        case_status, case_url, metadata, ingestion_run_id
    ) VALUES (
        %(case_number)s, %(court_name)s, %(county)s, %(state)s, %(case_type)s,
        %(filing_date)s, %(case_status)s, %(case_url)s, %(metadata)s, %(ingestion_run_id)s
    )
    ON CONFLICT (state, county, case_number) DO UPDATE SET
        court_name = COALESCE(EXCLUDED.court_name, judgments.cases.court_name),
        case_type = COALESCE(EXCLUDED.case_type, judgments.cases.case_type),
        filing_date = COALESCE(EXCLUDED.filing_date, judgments.cases.filing_date),
        case_status = COALESCE(EXCLUDED.case_status, judgments.cases.case_status),
        case_url = COALESCE(EXCLUDED.case_url, judgments.cases.case_url),
        metadata = COALESCE(judgments.cases.metadata, '{}'::jsonb) || COALESCE(EXCLUDED.metadata, '{}'::jsonb),
        ingestion_run_id = EXCLUDED.ingestion_run_id,
        updated_at = NOW()
    RETURNING id, (xmax = 0) AS inserted;
"""


def upsert_case(conn: psycopg2.extensions.connection, data: Dict[str, Any]) -> Tuple[str, bool]:
    payload = data.copy()
    payload.setdefault("state", "CA")
    payload.setdefault("ingestion_run_id", None)
    payload["metadata"] = _json(payload.get("metadata"))
    return _execute_upsert(conn, CASE_UPSERT_SQL, payload)


JUDGMENT_UPSERT_SQL = """
    INSERT INTO judgments.judgments (
        case_id, judgment_number, judgment_date, amount_awarded, amount_remaining,
        interest_rate, judgment_type, judgment_status, renewal_date, expiration_date,
        notes, metadata, ingestion_run_id
    ) VALUES (
        %(case_id)s, %(judgment_number)s, %(judgment_date)s, %(amount_awarded)s,
        %(amount_remaining)s, %(interest_rate)s, %(judgment_type)s, %(judgment_status)s,
        %(renewal_date)s, %(expiration_date)s, %(notes)s, %(metadata)s, %(ingestion_run_id)s
    )
    ON CONFLICT (case_id, judgment_date, amount_awarded) DO UPDATE SET
        judgment_number = COALESCE(EXCLUDED.judgment_number, judgments.judgments.judgment_number),
        amount_remaining = COALESCE(EXCLUDED.amount_remaining, judgments.judgments.amount_remaining),
        interest_rate = COALESCE(EXCLUDED.interest_rate, judgments.judgments.interest_rate),
        judgment_type = COALESCE(EXCLUDED.judgment_type, judgments.judgments.judgment_type),
    judgment_status = COALESCE(EXCLUDED.judgment_status, judgments.judgments.judgment_status),
        renewal_date = COALESCE(EXCLUDED.renewal_date, judgments.judgments.renewal_date),
        expiration_date = COALESCE(EXCLUDED.expiration_date, judgments.judgments.expiration_date),
        notes = COALESCE(EXCLUDED.notes, judgments.judgments.notes),
        metadata = COALESCE(judgments.judgments.metadata, '{}'::jsonb) || COALESCE(EXCLUDED.metadata, '{}'::jsonb),
        ingestion_run_id = EXCLUDED.ingestion_run_id,
        updated_at = NOW()
    RETURNING id, (xmax = 0) AS inserted;
"""


def upsert_judgment(conn: psycopg2.extensions.connection, data: Dict[str, Any]) -> Tuple[str, bool]:
    payload = data.copy()
    payload.setdefault("ingestion_run_id", None)
    payload["metadata"] = _json(payload.get("metadata"))
    return _execute_upsert(conn, JUDGMENT_UPSERT_SQL, payload)


PARTY_UPSERT_SQL = """
    INSERT INTO judgments.parties (
        case_id, party_type, party_role, is_business, name_full,
        name_first, name_last, name_business, name_normalized,
        address_line1, address_line2, city, state, zip,
        phone, email, metadata, ingestion_run_id
    ) VALUES (
        %(case_id)s, %(party_type)s, %(party_role)s, %(is_business)s, %(name_full)s,
        %(name_first)s, %(name_last)s, %(name_business)s, %(name_normalized)s,
        %(address_line1)s, %(address_line2)s, %(city)s, %(state)s, %(zip)s,
        %(phone)s, %(email)s, %(metadata)s, %(ingestion_run_id)s
    )
    ON CONFLICT (case_id, party_role, name_normalized) DO UPDATE SET
    party_type = COALESCE(EXCLUDED.party_type, judgments.parties.party_type),
        is_business = EXCLUDED.is_business,
        name_full = COALESCE(EXCLUDED.name_full, judgments.parties.name_full),
        name_first = COALESCE(EXCLUDED.name_first, judgments.parties.name_first),
        name_last = COALESCE(EXCLUDED.name_last, judgments.parties.name_last),
        name_business = COALESCE(EXCLUDED.name_business, judgments.parties.name_business),
        address_line1 = COALESCE(EXCLUDED.address_line1, judgments.parties.address_line1),
        address_line2 = COALESCE(EXCLUDED.address_line2, judgments.parties.address_line2),
        city = COALESCE(EXCLUDED.city, judgments.parties.city),
        state = COALESCE(EXCLUDED.state, judgments.parties.state),
        zip = COALESCE(EXCLUDED.zip, judgments.parties.zip),
        phone = COALESCE(EXCLUDED.phone, judgments.parties.phone),
        email = COALESCE(EXCLUDED.email, judgments.parties.email),
        metadata = COALESCE(judgments.parties.metadata, '{}'::jsonb) || COALESCE(EXCLUDED.metadata, '{}'::jsonb),
        ingestion_run_id = EXCLUDED.ingestion_run_id,
        updated_at = NOW()
    RETURNING id, (xmax = 0) AS inserted;
"""


def upsert_party(conn: psycopg2.extensions.connection, data: Dict[str, Any]) -> Tuple[str, bool]:
    payload = data.copy()
    payload.setdefault("is_business", False)
    payload.setdefault("ingestion_run_id", None)
    payload["metadata"] = _json(payload.get("metadata"))
    return _execute_upsert(conn, PARTY_UPSERT_SQL, payload)


CONTACT_UPSERT_SQL = """
    INSERT INTO judgments.contacts (
        party_id, contact_type, contact_value, contact_label,
        is_verified, is_primary, source, last_verified_at,
        notes, metadata, ingestion_run_id
    ) VALUES (
        %(party_id)s, %(contact_type)s, %(contact_value)s, %(contact_label)s,
        %(is_verified)s, %(is_primary)s, %(source)s, %(last_verified_at)s,
        %(notes)s, %(metadata)s, %(ingestion_run_id)s
    )
    ON CONFLICT (party_id, contact_type, contact_value) DO UPDATE SET
        contact_label = COALESCE(EXCLUDED.contact_label, judgments.contacts.contact_label),
        is_verified = EXCLUDED.is_verified,
        is_primary = EXCLUDED.is_primary,
        source = COALESCE(EXCLUDED.source, judgments.contacts.source),
        last_verified_at = COALESCE(EXCLUDED.last_verified_at, judgments.contacts.last_verified_at),
        notes = COALESCE(EXCLUDED.notes, judgments.contacts.notes),
        metadata = COALESCE(judgments.contacts.metadata, '{}'::jsonb) || COALESCE(EXCLUDED.metadata, '{}'::jsonb),
        ingestion_run_id = EXCLUDED.ingestion_run_id,
        updated_at = NOW()
    RETURNING id, (xmax = 0) AS inserted;
"""


def upsert_contact(conn: psycopg2.extensions.connection, data: Dict[str, Any]) -> Tuple[str, bool]:
    payload = data.copy()
    payload.setdefault("is_verified", False)
    payload.setdefault("is_primary", False)
    payload.setdefault("ingestion_run_id", None)
    payload["metadata"] = _json(payload.get("metadata"))
    return _execute_upsert(conn, CONTACT_UPSERT_SQL, payload)
