from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any, Iterator, Sequence

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from etl.simplicity_importer.import_simplicity import import_simplicity_batch
from src.supabase_client import get_supabase_db_url, get_supabase_env

pytestmark = pytest.mark.integration

TEST_SOURCE_SYSTEM = "simplicity_test"
DATA_DIR = Path(__file__).resolve().parent / "data"
SAMPLE_CSV_PATH = DATA_DIR / "simplicity_sample.csv"


def _table_identifier(schema: str | None, table_name: str) -> sql.Composable:
    return sql.Identifier(schema, table_name) if schema else sql.Identifier(table_name)


def _build_filter_clauses(
    filters: dict[str, Any] | None,
) -> tuple[list[sql.Composable], list[Any]]:
    if not filters:
        return [], []
    clauses: list[sql.Composable] = []
    params: list[Any] = []
    for column, value in filters.items():
        identifier = sql.Identifier(column)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            seq_value = list(value)
            if not seq_value:
                continue
            clauses.append(sql.SQL("{} = ANY(%s)").format(identifier))
            params.append(seq_value)
        else:
            clauses.append(sql.SQL("{} = %s").format(identifier))
            params.append(value)
    return clauses, params


def _fetch_rows(
    conn: psycopg.Connection,
    *,
    schema: str | None,
    table: str,
    filters: dict[str, Any] | None = None,
    columns: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    table_sql = _table_identifier(schema, table)
    column_sql = (
        sql.SQL("*")
        if not columns
        else sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    )
    query = sql.SQL("SELECT {columns} FROM {table}").format(
        columns=column_sql,
        table=table_sql,
    )
    clauses, params = _build_filter_clauses(filters)
    if clauses:
        query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def _delete_rows(
    conn: psycopg.Connection,
    *,
    schema: str | None,
    table: str,
    filters: dict[str, Any],
) -> None:
    clauses, params = _build_filter_clauses(filters)
    if not clauses:
        return
    query = sql.SQL("DELETE FROM {table} WHERE ").format(
        table=_table_identifier(schema, table)
    ) + sql.SQL(" AND ").join(clauses)
    with conn.cursor() as cur:
        cur.execute(query, params)


def _disable_fcra_trigger(conn: psycopg.Connection) -> None:
    """Temporarily disable FCRA delete-blocking trigger for test cleanup."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE public.plaintiff_contacts "
                "DISABLE TRIGGER trg_plaintiff_contacts_block_delete"
            )
    except Exception:
        # Trigger may not exist in all environments
        pass


def _enable_fcra_trigger(conn: psycopg.Connection) -> None:
    """Re-enable FCRA delete-blocking trigger after test cleanup."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE public.plaintiff_contacts "
                "ENABLE TRIGGER trg_plaintiff_contacts_block_delete"
            )
    except Exception:
        pass


def _cleanup_simplicity_rows(conn: psycopg.Connection, source_system: str) -> None:
    cases = _fetch_rows(
        conn,
        schema="judgments",
        table="cases",
        filters={"source_system": source_system},
        columns=("case_id",),
    )
    case_ids = [row["case_id"] for row in cases if row.get("case_id")]
    if case_ids:
        _delete_rows(
            conn,
            schema="judgments",
            table="judgments",
            filters={"case_id": case_ids},
        )
        _delete_rows(
            conn,
            schema="judgments",
            table="cases",
            filters={"case_id": case_ids},
        )

    plaintiffs = _fetch_rows(
        conn,
        schema=None,
        table="plaintiffs",
        filters={"source_system": source_system},
        columns=("id",),
    )
    plaintiff_ids = [row["id"] for row in plaintiffs if row.get("id")]
    if plaintiff_ids:
        # Disable FCRA trigger before deleting from plaintiff_contacts
        _disable_fcra_trigger(conn)
        try:
            _delete_rows(
                conn,
                schema=None,
                table="plaintiff_contacts",
                filters={"plaintiff_id": plaintiff_ids},
            )
            _delete_rows(
                conn,
                schema=None,
                table="plaintiffs",
                filters={"id": plaintiff_ids},
            )
        finally:
            _enable_fcra_trigger(conn)

    _delete_rows(
        conn,
        schema=None,
        table="import_runs",
        filters={"source_system": source_system},
    )


def _collect_counts(conn: psycopg.Connection, source_system: str) -> dict[str, int]:
    plaintiffs = _fetch_rows(
        conn,
        schema=None,
        table="plaintiffs",
        filters={"source_system": source_system},
        columns=("id",),
    )
    plaintiff_ids = [row["id"] for row in plaintiffs if row.get("id")]

    cases = _fetch_rows(
        conn,
        schema="judgments",
        table="cases",
        filters={"source_system": source_system},
        columns=("case_id",),
    )
    case_ids = [row["case_id"] for row in cases if row.get("case_id")]

    judgments = (
        _fetch_rows(
            conn,
            schema="judgments",
            table="judgments",
            filters={"case_id": case_ids} if case_ids else None,
            columns=("id", "case_id"),
        )
        if case_ids
        else []
    )

    contacts = (
        _fetch_rows(
            conn,
            schema=None,
            table="plaintiff_contacts",
            filters={"plaintiff_id": plaintiff_ids} if plaintiff_ids else None,
            columns=("id", "plaintiff_id"),
        )
        if plaintiff_ids
        else []
    )

    return {
        "plaintiffs": len(plaintiff_ids),
        "cases": len(case_ids),
        "judgments": len(judgments),
        "contacts": len(contacts),
    }


def _sorted_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(runs, key=lambda row: row.get("created_at") or "")


def _load_sample_rows(sample_path: Path) -> list[dict[str, str]]:
    with sample_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [row for row in reader if row]


def _expected_case_number(row: dict[str, str]) -> str | None:
    candidates = [row.get("IndexNumber"), row.get("JudgmentNumber"), row.get("LeadID")]
    for candidate in candidates:
        if candidate and candidate.strip():
            return candidate.strip()
    return None


def _expected_judgment_number(row: dict[str, str]) -> str | None:
    candidates = [row.get("JudgmentNumber"), row.get("IndexNumber"), row.get("LeadID")]
    for candidate in candidates:
        if candidate and candidate.strip():
            return candidate.strip()
    return None


def _expected_contact_channels(rows: list[dict[str, str]]) -> int:
    total = 0
    for row in rows:
        if row.get("Email") and row["Email"].strip():
            total += 1
        if row.get("Phone") and row["Phone"].strip():
            total += 1
    return total


@pytest.fixture(scope="module")
def db_env() -> str:
    return os.getenv("SIMP_IMPORTER_SUPABASE_ENV") or get_supabase_env()


@pytest.fixture(scope="module")
def db_url(db_env: str) -> str:
    try:
        return get_supabase_db_url(db_env)
    except Exception as exc:  # pragma: no cover - integration guardrail
        pytest.skip(
            f"Supabase database credentials unavailable for Simplicity importer tests: {exc}"
        )


@pytest.fixture()
def db_conn(db_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        yield conn


@pytest.fixture(scope="module")
def simplicity_sample_path() -> Path:
    if not SAMPLE_CSV_PATH.is_file():
        pytest.fail(f"Missing Simplicity sample file: {SAMPLE_CSV_PATH}")
    return SAMPLE_CSV_PATH


@pytest.fixture(scope="module")
def simplicity_sample_rows(simplicity_sample_path: Path) -> list[dict[str, str]]:
    rows = _load_sample_rows(simplicity_sample_path)
    if not rows:
        pytest.fail("Simplicity sample file must contain at least one row")
    return rows


@pytest.fixture(autouse=True)
def reset_simplicity_state(db_conn: psycopg.Connection) -> Iterator[None]:
    _cleanup_simplicity_rows(db_conn, TEST_SOURCE_SYSTEM)
    yield
    _cleanup_simplicity_rows(db_conn, TEST_SOURCE_SYSTEM)


@pytest.mark.integration
def test_import_simplicity_batch_inserts_rows(
    db_conn: psycopg.Connection,
    simplicity_sample_path: Path,
    simplicity_sample_rows: list[dict[str, str]],
) -> None:
    expected_row_count = len(simplicity_sample_rows)
    expected_case_numbers = {
        number
        for number in (_expected_case_number(row) for row in simplicity_sample_rows)
        if number
    }
    expected_judgment_numbers = {
        number
        for number in (_expected_judgment_number(row) for row in simplicity_sample_rows)
        if number
    }
    expected_contacts = _expected_contact_channels(simplicity_sample_rows)

    counts_before = _collect_counts(db_conn, TEST_SOURCE_SYSTEM)
    import_simplicity_batch(str(simplicity_sample_path), source_system=TEST_SOURCE_SYSTEM)
    counts_after = _collect_counts(db_conn, TEST_SOURCE_SYSTEM)

    assert counts_after["plaintiffs"] == counts_before["plaintiffs"] + expected_row_count
    assert counts_after["cases"] == counts_before["cases"] + len(expected_case_numbers)
    assert counts_after["judgments"] == counts_before["judgments"] + len(expected_judgment_numbers)
    assert counts_after["contacts"] == counts_before["contacts"] + expected_contacts

    plaintiffs = _fetch_rows(
        db_conn,
        schema=None,
        table="plaintiffs",
        filters={"source_system": TEST_SOURCE_SYSTEM},
    )
    assert len(plaintiffs) == expected_row_count

    cases = _fetch_rows(
        db_conn,
        schema="judgments",
        table="cases",
        filters={"source_system": TEST_SOURCE_SYSTEM},
    )
    assert cases, "Cases should be created for imported rows"
    case_ids = [row["case_id"] for row in cases if row.get("case_id")]
    assert set(filter(None, (row.get("case_number") for row in cases))) == expected_case_numbers

    judgments = _fetch_rows(
        db_conn,
        schema="judgments",
        table="judgments",
        filters={"case_id": case_ids},
    )
    assert judgments, "Judgments should exist for imported cases"
    assert set(case_ids).issubset({row.get("case_id") for row in judgments})
    assert (
        set(filter(None, (row.get("judgment_number") for row in judgments)))
        == expected_judgment_numbers
    )

    runs = _fetch_rows(
        db_conn,
        schema=None,
        table="import_runs",
        filters={"source_system": TEST_SOURCE_SYSTEM},
    )
    assert runs
    latest = _sorted_runs(runs)[-1]
    assert latest.get("status") == "completed"
    assert latest.get("total_rows") == expected_row_count
    assert latest.get("row_count") == expected_row_count
    assert latest.get("insert_count", 0) == expected_row_count
    assert latest.get("update_count", 0) == 0
    assert latest.get("error_count", 0) == 0
    metadata = latest.get("metadata") or {}
    assert metadata.get("updated_rows") == 0
    assert metadata.get("skipped_rows") == 0


@pytest.mark.integration
def test_import_simplicity_batch_is_idempotent(
    db_conn: psycopg.Connection,
    simplicity_sample_path: Path,
    simplicity_sample_rows: list[dict[str, str]],
) -> None:
    initial_runs = _fetch_rows(
        db_conn,
        schema=None,
        table="import_runs",
        filters={"source_system": TEST_SOURCE_SYSTEM},
    )
    expected_row_count = len(simplicity_sample_rows)

    import_simplicity_batch(str(simplicity_sample_path), source_system=TEST_SOURCE_SYSTEM)
    first_counts = _collect_counts(db_conn, TEST_SOURCE_SYSTEM)
    runs_after_first = _fetch_rows(
        db_conn,
        schema=None,
        table="import_runs",
        filters={"source_system": TEST_SOURCE_SYSTEM},
    )

    import_simplicity_batch(str(simplicity_sample_path), source_system=TEST_SOURCE_SYSTEM)
    second_counts = _collect_counts(db_conn, TEST_SOURCE_SYSTEM)
    runs_after_second = _fetch_rows(
        db_conn,
        schema=None,
        table="import_runs",
        filters={"source_system": TEST_SOURCE_SYSTEM},
    )

    assert first_counts["plaintiffs"] == expected_row_count
    assert second_counts == first_counts
    assert len(runs_after_first) == len(initial_runs) + 1
    assert len(runs_after_second) == len(runs_after_first) + 1
    assert _sorted_runs(runs_after_first)[-1].get("status") == "completed"
    assert _sorted_runs(runs_after_second)[-1].get("status") == "completed"
