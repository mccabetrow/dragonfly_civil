from __future__ import annotations

import csv
import uuid
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from etl.src.simplicity_ingest import (
    _coerce_row,
    ingest_file,
    map_row_to_insert_case_payload,
)
from scripts.sync_simplicity_cases import preview_ingest


def _resolve_db_url() -> str:
    explicit = Path(".env.test")
    if explicit.is_file():
        for line in explicit.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SUPABASE_DB_URL="):
                return line.split("=", 1)[1]
    # Fallback to environment variables consistent with other tests.
    from tests.test_collectability_snapshot import _resolve_db_url as _collectability_resolver

    return _collectability_resolver()


def _write_csv(tmp_path: Path, case_numbers: list[str]) -> Path:
    csv_path = tmp_path / "simplicity_cases.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "case_number",
                "docket_number",
                "title",
                "court",
                "filing_date",
                "judgment_date",
                "amount_awarded",
            ]
        )
        for idx, case_number in enumerate(case_numbers, start=1):
            writer.writerow(
                [
                    case_number,
                    f"DCK-{idx:05d}",
                    f"Case {idx}",
                    "Kings County Civil Court",
                    "2024-01-01",
                    "2024-03-01",
                    "2500.75",
                ]
            )
    return csv_path


def test_map_row_to_insert_case_payload_handles_realistic_headers() -> None:
    raw_row: dict[str, str | None] = {
        "Case Number": "CIV-2025-001",
        "Docket No": "DCK-12345",
        "Case Title": "City of NY v. Smith",
        "Court Name": "Kings County Civil Court",
        "Filing Date": "01/15/2024",
        "Judgment Date": "03/02/2024",
        "Amount": "$4,250.00",
    }

    normalised = _coerce_row(raw_row)
    payload = map_row_to_insert_case_payload(normalised, source="simplicity")

    assert payload == {
        "case_number": "CIV-2025-001",
        "source": "simplicity",
        "docket_number": "DCK-12345",
        "title": "City of NY v. Smith",
        "court": "Kings County Civil Court",
        "filing_date": "2024-01-15",
        "judgment_date": "2024-03-02",
        "amount_awarded": "4250.00",
    }


def test_preview_ingest_returns_counts_and_samples(tmp_path: Path) -> None:
    case_numbers = [f"SIM-DRY-{uuid.uuid4().hex[:6].upper()}" for _ in range(4)]
    csv_path = _write_csv(tmp_path, case_numbers)

    preview = preview_ingest(csv_path, source="simplicity", sample_size=2)

    assert preview.processed == len(case_numbers)
    assert preview.ingestable == len(case_numbers)
    assert preview.errors == []
    assert len(preview.payload_samples) == 2
    assert preview.payload_samples[0]["case_number"] == case_numbers[0]


def test_simplicity_ingest_inserts_cases(tmp_path: Path) -> None:
    db_url = _resolve_db_url()
    case_numbers = [f"SIM-TEST-{uuid.uuid4().hex[:8].upper()}" for _ in range(3)]

    csv_path = _write_csv(tmp_path, case_numbers)

    with psycopg.connect(db_url, autocommit=False) as conn:
        result = ingest_file(csv_path, conn=conn)

        assert result.processed == len(case_numbers)
        assert result.inserted == len(case_numbers)
        assert result.failed == 0

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select case_id, case_number, source, amount_awarded, judgment_date "
                "from judgments.cases where case_number = any(%s)",
                (case_numbers,),
            )
            rows = cur.fetchall()

        assert len(rows) == len(case_numbers)
        case_ids = [row["case_id"] for row in rows]
        assert all(row["source"] == "simplicity" for row in rows)
        assert all(row["amount_awarded"] is not None for row in rows)
        assert all(row["judgment_date"] is not None for row in rows)

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select case_id, judgment_amount, age_days, collectability_tier "
                "from judgments.v_collectability_snapshot where case_id = any(%s)",
                (case_ids,),
            )
            snapshot_rows = cur.fetchall()

        assert len(snapshot_rows) == len(case_numbers)
        for snapshot in snapshot_rows:
            assert snapshot["judgment_amount"] is not None
            assert snapshot["age_days"] is not None
            assert snapshot["collectability_tier"] in {"A", "B", "C"}

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select case_id from public.v_collectability_snapshot where case_id = any(%s)",
                (case_ids,),
            )
            public_rows = cur.fetchall()

        assert len(public_rows) == len(case_numbers)

        conn.rollback()
