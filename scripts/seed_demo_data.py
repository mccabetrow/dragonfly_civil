"""Seed deterministic demo data for Dragonfly Civil dashboards.

The script targets Supabase Postgres directly because PostgREST does not expose
the private ``judgments`` schema. To avoid accidents we enforce explicit demo
environment guards before touching the database.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple
from uuid import UUID, uuid5

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.supabase_client import (
    create_supabase_client,
    get_supabase_db_url,
    get_supabase_env,
)

logger = logging.getLogger(__name__)


DEMO_PREFIX = "DEMO-CASE-"
CASE_NAMESPACE = UUID("1f914a93-38a3-4aa0-b756-a9d0f7fd5408")
ALLOWED_DEMO_ENVS = {"local", "demo"}
PRODUCTION_NODE_ENV = "production"
COLUMN_CACHE: Dict[Tuple[str, str], Set[str]] = {}
CASE_FK_CACHE: Dict[Tuple[str, str], str] = {}
DECISION_TYPE_VALUES: Set[str] = {"final", "interlocutory", "summary", "default"}


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _ensure_demo_environment() -> None:
    demo_env = os.getenv("DEMO_ENV")
    if demo_env not in ALLOWED_DEMO_ENVS:
        raise RuntimeError(
            "DEMO_ENV must be one of %s (got %r)"
            % (sorted(ALLOWED_DEMO_ENVS), demo_env)
        )

    node_env = os.getenv("NODE_ENV")
    if node_env == PRODUCTION_NODE_ENV:
        raise RuntimeError(
            "NODE_ENV=production is not allowed for demo seed operations"
        )

    supabase_env = get_supabase_env()
    if supabase_env == "prod":
        raise RuntimeError(
            "Supabase demo seeding blocked: SUPABASE_MODE=prod selects production credentials. "
            "Set SUPABASE_MODE=demo before running demo reset scripts."
        )

    logger.info(
        "demo_guard_verified demo_env=%s node_env=%s supabase_env=%s",
        demo_env,
        node_env or "<unset>",
        supabase_env,
    )


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _decimal_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    try:
        return f"{Decimal(str(value)):.2f}"
    except (ArithmeticError, ValueError):
        return None


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in payload.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (date, datetime)):
            normalized[key] = _iso_date(value)
        elif isinstance(value, Decimal):
            normalized[key] = _decimal_str(value)
        else:
            normalized[key] = value
    return normalized


def _coerce_uuid(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, UUID):
        return str(raw)
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        for key in ("case_id", "id", "value"):
            if key in raw:
                return _coerce_uuid(raw[key])
    return None


def _extract_case_id(raw: Any) -> str | None:
    if isinstance(raw, list):
        for entry in raw:
            candidate = _coerce_uuid(entry)
            if candidate:
                return candidate
        return None
    return _coerce_uuid(raw)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _predict_case_id(case_number: str) -> str:
    return str(uuid5(CASE_NAMESPACE, case_number))


def _decision_type_for_entry(entry: Dict[str, Any]) -> str:
    for candidate in (
        entry.get("decision_type"),
        entry.get("judgment_type"),
        "final",
    ):
        if isinstance(candidate, str):
            lowered = candidate.lower()
            if lowered in DECISION_TYPE_VALUES:
                return lowered
    return "final"


def _verify_case_exists(
    conn: psycopg.Connection,
    rpc_case_id: str,
    *,
    case_number: str,
) -> Tuple[str, str]:
    columns = _table_columns(conn, "judgments", "cases")
    lookup_column = "case_id" if "case_id" in columns else "id"

    case_expr = (
        sql.SQL("case_id::text") if "case_id" in columns else sql.SQL("NULL::text")
    )
    id_expr = sql.SQL("id::text") if "id" in columns else sql.SQL("NULL::text")

    query = sql.SQL(
        "select {case_expr}, {id_expr} from judgments.cases where {lookup} = %s"
    ).format(case_expr=case_expr, id_expr=id_expr, lookup=sql.Identifier(lookup_column))

    with conn.cursor() as cur:
        cur.execute(query, (rpc_case_id,))
        row = cur.fetchone()

    if row is None:
        logger.error(
            "case_verification_failed case=%s rpc_case_id=%s lookup=%s",
            case_number,
            rpc_case_id,
            lookup_column,
        )
        raise RuntimeError(
            "Case verification failed for %s (case_id=%s)" % (case_number, rpc_case_id)
        )

    db_case_id_raw, db_case_pk_raw = row
    db_case_id = str(db_case_id_raw or rpc_case_id)
    db_case_pk = str(db_case_pk_raw or db_case_id_raw or rpc_case_id)

    logger.info(
        "case_verified case=%s rpc_case_id=%s case_id=%s case_pk=%s lookup=%s",
        case_number,
        rpc_case_id,
        db_case_id,
        db_case_pk,
        lookup_column,
    )

    return db_case_id, db_case_pk


def _case_specs(today: date) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    case_a_judgment = today - timedelta(days=90)
    case_b_judgment = today - timedelta(days=520)
    case_c_judgment = today - timedelta(days=1320)

    return [
        {
            "case_number": f"{DEMO_PREFIX}001",
            "title": "Acme Funding LLC v. Jordan Rivera",
            "source": "demo_seed",
            "source_system": "demo_seed",
            "docket_number": "CV-2024-001",
            "court": "Kings County Civil Court",
            "state": "NY",
            "county": "Kings",
            "case_type": "Consumer Debt",
            "case_status": "outreach_stubbed",
            "owner": "control@dragonflycivil.com",
            "case_url": "https://demo.dragonflycivil.local/cases/DEMO-CASE-001",
            "filing_date": case_a_judgment - timedelta(days=60),
            "judgment_date": case_a_judgment,
            "amount_awarded": Decimal("18750.00"),
            "currency": "USD",
            "metadata": {
                "demo": True,
                "segment": "control_tower",
                "tier_hint": "A",
            },
            "judgments": [
                {
                    "judgment_date": case_a_judgment,
                    "amount": Decimal("18750.00"),
                    "status": "unsatisfied",
                    "judgment_type": "default",
                    "notes": "Principal and interest confirmed",
                }
            ],
            "parties": [
                {
                    "role": "plaintiff",
                    "name_full": "Acme Funding LLC",
                    "is_business": True,
                    "address_line1": "100 Market Street",
                    "city": "Brooklyn",
                    "state": "NY",
                    "zip": "11201",
                },
                {
                    "role": "defendant",
                    "name_full": "Jordan Rivera",
                    "address_line1": "55 Linden Boulevard",
                    "city": "Brooklyn",
                    "state": "NY",
                    "zip": "11226",
                },
            ],
            "enrichment_runs": [
                {
                    "status": "completed",
                    "summary": "Assets validated; wage garnishment viable.",
                    "created_at": now - timedelta(days=30),
                    "raw": {
                        "source": "seed_demo",
                        "outcome": "assets_verified",
                        "confidence": 0.82,
                    },
                },
                {
                    "status": "queued_outreach",
                    "summary": "Queued for outreach script handoff.",
                    "created_at": now - timedelta(days=2),
                    "raw": {"source": "seed_demo", "queue": "outreach"},
                },
            ],
            "foil_responses": [
                {
                    "agency": "NYC Department of Finance",
                    "received_date": today - timedelta(days=15),
                    "created_at": now - timedelta(days=15),
                    "payload": {
                        "document": "lien_search.pdf",
                        "status": "received",
                        "notes": "Confirmed tax lien released",
                    },
                }
            ],
        },
        {
            "case_number": f"{DEMO_PREFIX}002",
            "title": "Empire Credit Partners v. Alicia Patel",
            "source": "demo_seed",
            "source_system": "demo_seed",
            "docket_number": "CV-2022-014",
            "court": "Queens County Civil Court",
            "state": "NY",
            "county": "Queens",
            "case_type": "Commercial Lease",
            "case_status": "enrich_pending",
            "owner": "operations@dragonflycivil.com",
            "case_url": "https://demo.dragonflycivil.local/cases/DEMO-CASE-002",
            "filing_date": case_b_judgment - timedelta(days=120),
            "judgment_date": case_b_judgment,
            "amount_awarded": Decimal("2450.00"),
            "currency": "USD",
            "metadata": {
                "demo": True,
                "segment": "collectability",
                "tier_hint": "B",
            },
            "judgments": [
                {
                    "judgment_date": case_b_judgment,
                    "amount": Decimal("2450.00"),
                    "status": "unsatisfied",
                    "judgment_type": "stipulated",
                    "notes": "Installment plan in negotiation",
                }
            ],
            "parties": [
                {
                    "role": "plaintiff",
                    "name_full": "Empire Credit Partners",
                    "is_business": True,
                    "address_line1": "75 Queens Plaza",
                    "city": "Long Island City",
                    "state": "NY",
                    "zip": "11101",
                },
                {
                    "role": "defendant",
                    "name_full": "Alicia Patel",
                    "address_line1": "21-18 31st Road",
                    "city": "Astoria",
                    "state": "NY",
                    "zip": "11102",
                },
            ],
            "enrichment_runs": [
                {
                    "status": "completed",
                    "summary": "Employer verified; awaiting payroll contact.",
                    "created_at": now - timedelta(days=75),
                    "raw": {
                        "source": "seed_demo",
                        "outcome": "employment_identified",
                        "confidence": 0.64,
                    },
                },
                {
                    "status": "no_hit",
                    "summary": "Bank account enrichment returned no matching assets.",
                    "created_at": now - timedelta(days=40),
                    "raw": {
                        "source": "seed_demo",
                        "outcome": "asset_search_empty",
                    },
                },
            ],
            "foil_responses": [
                {
                    "agency": "NYC Business Integrity Commission",
                    "received_date": today - timedelta(days=60),
                    "created_at": now - timedelta(days=60),
                    "payload": {
                        "document": "license_status.json",
                        "status": "pending_review",
                    },
                }
            ],
        },
        {
            "case_number": f"{DEMO_PREFIX}003",
            "title": "New Horizon Finance v. Malik Thompson",
            "source": "demo_seed",
            "source_system": "demo_seed",
            "docket_number": "CV-2019-333",
            "court": "Bronx County Civil Court",
            "state": "NY",
            "county": "Bronx",
            "case_type": "Small Claims",
            "case_status": "monitoring",
            "owner": "observability@dragonflycivil.com",
            "case_url": "https://demo.dragonflycivil.local/cases/DEMO-CASE-003",
            "filing_date": case_c_judgment - timedelta(days=90),
            "judgment_date": case_c_judgment,
            "amount_awarded": Decimal("860.00"),
            "currency": "USD",
            "metadata": {
                "demo": True,
                "segment": "watchlist",
                "tier_hint": "C",
            },
            "judgments": [
                {
                    "judgment_date": case_c_judgment,
                    "amount": Decimal("860.00"),
                    "status": "unsatisfied",
                    "judgment_type": "default",
                    "notes": "Older balance awaiting fresh leads",
                }
            ],
            "parties": [
                {
                    "role": "plaintiff",
                    "name_full": "New Horizon Finance",
                    "is_business": True,
                    "address_line1": "310 Grand Concourse",
                    "city": "Bronx",
                    "state": "NY",
                    "zip": "10451",
                },
                {
                    "role": "defendant",
                    "name_full": "Malik Thompson",
                    "address_line1": "1475 Walton Avenue",
                    "city": "Bronx",
                    "state": "NY",
                    "zip": "10452",
                },
            ],
            "enrichment_runs": [
                {
                    "status": "queued_enrichment",
                    "summary": "Scheduled refresh against skip-tracing provider.",
                    "created_at": now - timedelta(days=5),
                    "raw": {
                        "source": "seed_demo",
                        "outcome": "refresh_requested",
                    },
                }
            ],
            "foil_responses": [],
        },
    ]


def _table_columns(conn: psycopg.Connection, schema: str, table: str) -> Set[str]:
    cache_key = (schema, table)
    cached = COLUMN_CACHE.get(cache_key)
    if cached is not None:
        return cached

    with conn.cursor() as cur:
        cur.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = %s and table_name = %s
            """,
            (schema, table),
        )
        columns = {row[0] for row in cur.fetchall()}

    COLUMN_CACHE[cache_key] = columns
    return columns


def _resolve_case_fk_target(
    conn: psycopg.Connection,
    schema: str,
    table: str,
) -> str:
    cache_key = (schema, table)
    cached = CASE_FK_CACHE.get(cache_key)
    if cached is not None:
        return cached

    query = sql.SQL(
        """
        select pg_get_constraintdef(oid)
        from pg_constraint
        where conrelid = %s::regclass
          and confrelid = 'judgments.cases'::regclass
        order by oid
        limit 1
        """
    )

    constraint_def = None
    with conn.cursor() as cur:
        cur.execute(query, (f"{schema}.{table}",))
        row = cur.fetchone()
        if row:
            constraint_def = row[0] or ""

    target = "case_id"
    if constraint_def:
        lowered = constraint_def.lower()
        if "cases(id" in lowered:
            target = "id"
        elif "cases(case_id" in lowered:
            target = "case_id"

    CASE_FK_CACHE[cache_key] = target
    return target


def _filter_existing_columns(
    available: Iterable[str], payload: Dict[str, Any]
) -> Dict[str, Any]:
    available_set = set(available)
    return {key: value for key, value in payload.items() if key in available_set}


def _filter_columns_for_insert(
    available: Set[str],
    columns_and_values: Sequence[Tuple[str, Any]],
    *,
    context: str,
) -> Tuple[List[str], List[Any]]:
    columns: List[str] = []
    values: List[Any] = []
    for column, value in columns_and_values:
        if column not in available:
            logger.debug("Skipping column %s for %s (column missing)", column, context)
            continue
        columns.append(column)
        values.append(value)
    return columns, values


def _execute_insert(
    cur: psycopg.Cursor[Any],
    schema: str,
    table: str,
    columns: Sequence[str],
    values: Sequence[Any],
) -> None:
    identifiers = [sql.Identifier(column) for column in columns]
    placeholders = [sql.Placeholder() for _ in columns]
    query = sql.SQL("insert into {}.{} ({}) values ({})").format(
        sql.Identifier(schema),
        sql.Identifier(table),
        sql.SQL(", ").join(identifiers),
        sql.SQL(", ").join(placeholders),
    )
    cur.execute(query, list(values))


def _refresh_parties(
    conn: psycopg.Connection,
    case_id: str,
    case_pk: str,
    parties: Sequence[Dict[str, Any]],
    *,
    case_number: str,
    dry_run: bool,
) -> None:
    if not parties:
        return

    available_columns = _table_columns(conn, "judgments", "parties")
    fk_target = _resolve_case_fk_target(conn, "judgments", "parties")
    case_foreign_value = case_pk if fk_target == "id" else case_id

    if dry_run:
        logger.info(
            "demo_parties_dry_run case=%s case_id=%s case_fk=%s count=%d",
            case_number,
            case_id,
            case_foreign_value,
            len(parties),
        )
        return

    deleted = 0
    inserted = 0
    with conn.cursor() as cur:
        # Demo-only cleanup: reset seeded parties before inserting fresh copies.
        cur.execute(
            "delete from judgments.parties where case_id = %s", (case_foreign_value,)
        )
        deleted = cur.rowcount or 0

        for party in parties:
            address_raw = " ".join(
                part
                for part in (
                    party.get("address_line1"),
                    party.get("address_line2"),
                    party.get("city"),
                    party.get("state"),
                    party.get("zip"),
                )
                if part
            )
            contact_payload = {
                "address": {
                    "line1": party.get("address_line1"),
                    "line2": party.get("address_line2"),
                    "city": party.get("city"),
                    "state": party.get("state"),
                    "zip": party.get("zip"),
                },
                "is_business": party.get("is_business", False),
                "address_raw": address_raw or None,
            }
            metadata_payload = {
                "demo": True,
                "seed_payload": _json_safe(party),
            }

            columns, values = _filter_columns_for_insert(
                available_columns,
                [
                    ("case_id", case_foreign_value),
                    ("role", party.get("role")),
                    ("party_type", party.get("role")),
                    ("name", party.get("name_full") or party.get("name")),
                    ("name_full", party.get("name_full")),
                    ("is_business", party.get("is_business", False)),
                    ("address_line1", party.get("address_line1")),
                    ("address_line2", party.get("address_line2")),
                    ("city", party.get("city")),
                    ("state", party.get("state")),
                    ("zip", party.get("zip")),
                    ("address_raw", address_raw or None),
                    ("legal_representation", party.get("legal_representation")),
                    ("contact_info", Json(contact_payload)),
                    ("metadata", Json(metadata_payload)),
                ],
                context="judgments.parties",
            )

            if not columns:
                logger.debug(
                    "No writable party columns detected for %s (case=%s)",
                    party.get("name_full") or party.get("name"),
                    case_number,
                )
                continue

            _execute_insert(cur, "judgments", "parties", columns, values)
            inserted += cur.rowcount or 0

    logger.info(
        "demo_parties_refreshed case=%s case_id=%s case_fk=%s deleted=%d inserted=%d",
        case_number,
        case_id,
        case_foreign_value,
        deleted,
        inserted,
    )


def _refresh_judgments(
    conn: psycopg.Connection,
    case_id: str,
    case_pk: str,
    judgments: Sequence[Dict[str, Any]],
    *,
    case_number: str,
    dry_run: bool,
) -> None:
    if not judgments:
        return

    available_columns = _table_columns(conn, "judgments", "judgments")
    fk_target = _resolve_case_fk_target(conn, "judgments", "judgments")
    case_foreign_value = case_pk if fk_target == "id" else case_id

    if dry_run:
        logger.info(
            "demo_judgments_dry_run case=%s case_id=%s case_fk=%s count=%d",
            case_number,
            case_id,
            case_foreign_value,
            len(judgments),
        )
        return

    deleted = 0
    inserted = 0
    with conn.cursor() as cur:
        # Demo-only cleanup: remove existing synthetic judgments ahead of reseed.
        cur.execute(
            "delete from judgments.judgments where case_id = %s", (case_foreign_value,)
        )
        deleted = cur.rowcount or 0

        for entry in judgments:
            amount = entry.get("amount") or Decimal("0")
            metadata_payload = {
                "demo": True,
                "seed_payload": _json_safe(entry),
            }
            columns, values = _filter_columns_for_insert(
                available_columns,
                [
                    ("case_id", case_foreign_value),
                    ("judgment_date", entry.get("judgment_date")),
                    ("amount", amount),
                    ("amount_awarded", entry.get("amount_awarded", amount)),
                    ("amount_remaining", entry.get("amount_remaining")),
                    ("status", entry.get("status", "unsatisfied")),
                    ("judgment_status", entry.get("status", "unsatisfied")),
                    ("outcome", entry.get("status")),
                    ("judgment_type", entry.get("judgment_type")),
                    ("decision_type", _decision_type_for_entry(entry)),
                    ("notes", entry.get("notes")),
                    ("metadata", Json(metadata_payload)),
                ],
                context="judgments.judgments",
            )

            if not columns:
                logger.debug(
                    "No writable judgment columns detected for case=%s", case_number
                )
                continue

            _execute_insert(cur, "judgments", "judgments", columns, values)
            inserted += cur.rowcount or 0

    logger.info(
        "demo_judgments_refreshed case=%s case_id=%s case_fk=%s deleted=%d inserted=%d",
        case_number,
        case_id,
        case_foreign_value,
        deleted,
        inserted,
    )


def _refresh_enrichment_runs(
    conn: psycopg.Connection,
    case_id: str,
    case_pk: str,
    runs: Sequence[Dict[str, Any]],
    *,
    case_number: str,
    dry_run: bool,
) -> None:
    if not runs:
        return

    available_columns = _table_columns(conn, "judgments", "enrichment_runs")
    fk_target = _resolve_case_fk_target(conn, "judgments", "enrichment_runs")
    case_foreign_value = case_pk if fk_target == "id" else case_id

    if dry_run:
        logger.info(
            "demo_enrichment_dry_run case=%s case_id=%s case_fk=%s count=%d",
            case_number,
            case_id,
            case_foreign_value,
            len(runs),
        )
        return

    deleted = 0
    inserted = 0
    with conn.cursor() as cur:
        cur.execute(
            # Demo-only cleanup: drop synthetic enrichment runs so they can be recreated.
            "delete from judgments.enrichment_runs where case_id = %s",
            (case_foreign_value,),
        )
        deleted = cur.rowcount or 0

        for entry in runs:
            metadata_payload = {
                "demo": True,
                "seed_payload": _json_safe(entry),
            }
            columns, values = _filter_columns_for_insert(
                available_columns,
                [
                    ("case_id", case_foreign_value),
                    ("status", entry.get("status", "completed")),
                    ("summary", entry.get("summary")),
                    ("raw", Json(_json_safe(entry.get("raw", {})))),
                    ("created_at", entry.get("created_at")),
                    ("metadata", Json(metadata_payload)),
                ],
                context="judgments.enrichment_runs",
            )

            if not columns:
                logger.debug(
                    "No writable enrichment columns detected for case=%s", case_number
                )
                continue

            _execute_insert(cur, "judgments", "enrichment_runs", columns, values)
            inserted += cur.rowcount or 0

    logger.info(
        "demo_enrichment_refreshed case=%s case_id=%s case_fk=%s deleted=%d inserted=%d",
        case_number,
        case_id,
        case_foreign_value,
        deleted,
        inserted,
    )


def _refresh_foil_responses(
    conn: psycopg.Connection,
    case_id: str,
    case_pk: str,
    responses: Sequence[Dict[str, Any]],
    *,
    case_number: str,
    dry_run: bool,
) -> None:
    if not responses:
        return

    available_columns = _table_columns(conn, "judgments", "foil_responses")
    fk_target = _resolve_case_fk_target(conn, "judgments", "foil_responses")
    case_foreign_value = case_pk if fk_target == "id" else case_id

    if dry_run:
        logger.info(
            "demo_foil_dry_run case=%s case_id=%s case_fk=%s count=%d",
            case_number,
            case_id,
            case_foreign_value,
            len(responses),
        )
        return

    deleted = 0
    inserted = 0
    with conn.cursor() as cur:
        cur.execute(
            # Demo-only cleanup: clear FOIL response stubs for this demo case.
            "delete from judgments.foil_responses where case_id = %s",
            (case_foreign_value,),
        )
        deleted = cur.rowcount or 0

        for entry in responses:
            metadata_payload = {
                "demo": True,
                "seed_payload": _json_safe(entry),
            }
            columns, values = _filter_columns_for_insert(
                available_columns,
                [
                    ("case_id", case_foreign_value),
                    ("agency", entry.get("agency")),
                    ("received_date", entry.get("received_date")),
                    ("created_at", entry.get("created_at")),
                    ("payload", Json(_json_safe(entry.get("payload", {})))),
                    ("metadata", Json(metadata_payload)),
                ],
                context="judgments.foil_responses",
            )

            if not columns:
                logger.debug(
                    "No writable FOIL response columns detected for case=%s",
                    case_number,
                )
                continue

            _execute_insert(cur, "judgments", "foil_responses", columns, values)
            inserted += cur.rowcount or 0

    logger.info(
        "demo_foil_refreshed case=%s case_id=%s case_fk=%s deleted=%d inserted=%d",
        case_number,
        case_id,
        case_foreign_value,
        deleted,
        inserted,
    )


def _update_case_record(
    conn: psycopg.Connection,
    case_id: str,
    payload: Dict[str, Any],
    *,
    case_number: str,
    dry_run: bool,
) -> None:
    if not payload:
        return

    columns = _table_columns(conn, "judgments", "cases")
    filtered_payload = _filter_existing_columns(columns, payload)
    if not filtered_payload:
        logger.debug("No update columns available for case %s", case_number)
        return

    pk_column = "case_id" if "case_id" in columns else "id"

    if dry_run:
        logger.info(
            "demo_case_update_dry_run case=%s case_id=%s columns=%s",
            case_number,
            case_id,
            sorted(filtered_payload.keys()),
        )
        return

    assignments: List[sql.Composed] = []
    values: List[Any] = []
    for column, value in filtered_payload.items():
        assignments.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
        if column == "metadata" and value is not None:
            values.append(Json(value))
        else:
            values.append(value)

    query = sql.SQL("update judgments.cases set {} where {} = %s").format(
        sql.SQL(", ").join(assignments),
        sql.Identifier(pk_column),
    )
    values.append(case_id)

    with conn.cursor() as cur:
        cur.execute(query, values)
        logger.info(
            "demo_case_updated case=%s case_id=%s columns=%s",
            case_number,
            case_id,
            sorted(filtered_payload.keys()),
        )


def cleanup_demo_data(conn: psycopg.Connection, *, dry_run: bool) -> None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select case_id, case_number from judgments.cases where case_number like %s",
            (f"{DEMO_PREFIX}%",),
        )
        rows = cur.fetchall()

    if not rows:
        logger.info("No demo cases found for prefix %s", DEMO_PREFIX)
        return

    case_ids = [str(row["case_id"]) for row in rows if row.get("case_id")]
    case_numbers = [row["case_number"] for row in rows if row.get("case_number")]

    logger.info(
        "demo_cleanup_target count=%d cases=%s case_ids=%s",
        len(case_ids),
        ",".join(case_numbers),
        ",".join(case_ids),
    )

    if dry_run:
        logger.info(
            "demo_cleanup_dry_run cases=%s case_ids=%s",
            ",".join(case_numbers),
            ",".join(case_ids),
        )
        return

    with conn.cursor() as cur:
        for schema, table in [
            ("judgments", "foil_responses"),
            ("judgments", "enrichment_runs"),
            ("judgments", "judgments"),
            ("judgments", "parties"),
        ]:
            if not case_ids:
                continue
            # Demo-only cleanup: wipe dependent rows tied to synthetic demo cases.
            cur.execute(
                sql.SQL("delete from {}.{} where case_id = any(%s)").format(
                    sql.Identifier(schema), sql.Identifier(table)
                ),
                (case_ids,),
            )
            logger.info(
                "demo_cleanup_deleted table=%s.%s count=%d",
                schema,
                table,
                cur.rowcount or 0,
            )

        if case_ids:
            cur.execute(
                # Demo-only cleanup: purge seeded case records for a full reset.
                "delete from judgments.cases where case_id = any(%s)",
                (case_ids,),
            )
            logger.info(
                "demo_cleanup_deleted table=judgments.cases count=%d",
                cur.rowcount or 0,
            )

        if case_numbers:
            cur.execute(
                # Demo-only cleanup: remove public surface rows tied to demo cases.
                "delete from public.judgments where case_number = any(%s)",
                (case_numbers,),
            )
            logger.info(
                "demo_cleanup_deleted table=public.judgments count=%d",
                cur.rowcount or 0,
            )


def _build_case_payload(spec: Dict[str, Any]) -> Dict[str, Any]:
    return _normalize_payload(
        {
            "case_number": spec["case_number"],
            "source": spec.get("source"),
            "title": spec.get("title"),
            "court": spec.get("court"),
            "filing_date": _iso_date(spec.get("filing_date")),
            "judgment_date": _iso_date(spec.get("judgment_date")),
            "amount_awarded": _decimal_str(spec.get("amount_awarded", "0")),
            "currency": spec.get("currency"),
        }
    )


def _build_case_update_payload(spec: Dict[str, Any]) -> Dict[str, Any]:
    return _normalize_payload(
        {
            "state": spec.get("state"),
            "county": spec.get("county"),
            "case_status": spec.get("case_status"),
            "case_type": spec.get("case_type"),
            "case_url": spec.get("case_url"),
            "owner": spec.get("owner"),
            "docket_number": spec.get("docket_number"),
            "source_system": spec.get("source_system"),
            "amount_awarded": spec.get("amount_awarded"),
            "judgment_date": spec.get("judgment_date"),
            "filing_date": spec.get("filing_date"),
            "metadata": spec.get("metadata"),
        }
    )


def seed_demo_dataset(
    client: Any | None,
    conn: psycopg.Connection,
    *,
    dry_run: bool,
) -> None:
    specs = _case_specs(date.today())
    logger.info("demo_seed_start count=%d dry_run=%s", len(specs), dry_run)

    for spec in specs:
        case_number = spec["case_number"]
        if dry_run:
            case_id = _predict_case_id(case_number)
            case_pk = case_id
            logger.info("demo_case_dry_run case=%s case_id=%s", case_number, case_id)
        else:
            if client is None:
                raise RuntimeError(
                    "Supabase client is required for non-dry-run seeding"
                )
            case_payload = _build_case_payload(spec)
            rpc_response = client.rpc(
                "insert_or_get_case", {"payload": case_payload}
            ).execute()
            rpc_case_id = _extract_case_id(getattr(rpc_response, "data", None))
            if not rpc_case_id:
                raise RuntimeError(f"Unable to resolve case_id for {case_number}")
            case_id, case_pk = _verify_case_exists(
                conn,
                rpc_case_id,
                case_number=case_number,
            )
            logger.info(
                "demo_case_ensured case=%s case_id=%s case_pk=%s",
                case_number,
                case_id,
                case_pk,
            )

        update_payload = _build_case_update_payload(spec)
        _update_case_record(
            conn, case_id, update_payload, case_number=case_number, dry_run=dry_run
        )

        _refresh_parties(
            conn,
            case_id,
            case_pk,
            spec.get("parties", []),
            case_number=case_number,
            dry_run=dry_run,
        )
        _refresh_judgments(
            conn,
            case_id,
            case_pk,
            spec.get("judgments", []),
            case_number=case_number,
            dry_run=dry_run,
        )
        _refresh_enrichment_runs(
            conn,
            case_id,
            case_pk,
            spec.get("enrichment_runs", []),
            case_number=case_number,
            dry_run=dry_run,
        )
        _refresh_foil_responses(
            conn,
            case_id,
            case_pk,
            spec.get("foil_responses", []),
            case_number=case_number,
            dry_run=dry_run,
        )

        if not dry_run:
            conn.commit()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed demo-friendly data for Dragonfly Civil dashboards"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview actions without mutating data"
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove previously seeded demo data before seeding",
    )
    parser.add_argument(
        "--only-cleanup",
        action="store_true",
        help="Remove demo data and skip seeding",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    _setup_logging()
    _ensure_demo_environment()

    if args.only_cleanup:
        args.cleanup = True

    dry_run = args.dry_run

    try:
        db_url = get_supabase_db_url()
    except RuntimeError as exc:
        logger.error("Supabase database configuration missing: %s", exc)
        return 1

    try:
        with psycopg.connect(db_url, autocommit=False) as conn:
            if args.cleanup:
                cleanup_demo_data(conn, dry_run=dry_run)
                if dry_run:
                    conn.rollback()
                else:
                    conn.commit()
                if args.only_cleanup:
                    logger.info("demo_cleanup_complete dry_run=%s", dry_run)
                    return 0

            client: Any | None = None
            if not dry_run and not args.only_cleanup:
                try:
                    client = create_supabase_client()
                except Exception as exc:  # pragma: no cover - configuration error
                    logger.error("Failed to create Supabase client: %s", exc)
                    return 1

            if not args.only_cleanup:
                seed_demo_dataset(client, conn, dry_run=dry_run)
                if dry_run:
                    conn.rollback()
                else:
                    conn.commit()
    except psycopg.Error as exc:
        logger.error("Database operation failed: %s", exc)
        return 1
    except Exception as exc:  # pragma: no cover - defensive log
        logger.error("Seeding demo data failed: %s", exc)
        return 1

    logger.info("demo_seed_complete dry_run=%s", dry_run)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
