from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.import_cases_from_csv import ImportConfig, import_cases


class FakeResponse:
    def __init__(self, data: Any):
        self.data = data

    def execute(self):
        return self


class FakeSupabaseClient:
    def __init__(self):
        self.insert_calls: list[dict[str, Any]] = []
        self.queue_calls: list[dict[str, Any]] = []
        self._seen_cases: set[str] = set()

    def rpc(self, name: str, params: dict[str, Any]):
        if name == "insert_or_get_case":
            payload = params.get("payload", {})
            case_number = payload.get("case_number", "")
            created = case_number not in self._seen_cases
            self._seen_cases.add(case_number)
            status = "inserted" if created else "existing"
            self.insert_calls.append(params)
            return FakeResponse({"case_id": f"id-{case_number}", "status": status})
        if name == "queue_job":
            self.queue_calls.append(params)
            return FakeResponse({"queue_job": len(self.queue_calls)})
        raise AssertionError(f"Unexpected RPC call: {name}")


def write_csv(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "cases.csv"
    path.write_text(content, encoding="utf-8")
    return path


def test_import_cases_enqueues_jobs_and_classifies_status(tmp_path: Path):
    csv_content = (
        "case_number,court,plaintiff_name,defendant_name,judgment_amount,judgment_date,source\n"
        "CASE-001,Kings County Civil Court,Acme Funding LLC,Jordan Rivera,18750.00,2024-09-15,import_batch\n"
        "CASE-002,Queens County Civil Court,Summit Lending LLC,,4500.50,2024-08-01,\n"
        "CASE-001,Kings County Civil Court,Acme Funding LLC,Jordan Rivera,18750.00,2024-09-15,ignored_source\n"
    )
    csv_path = write_csv(tmp_path, csv_content)

    config = ImportConfig(
        csv_path=csv_path,
        dry_run=False,
        source_tag="INTAKE_DEFAULT",
        enqueue_enrich=True,
    )

    fake_client = FakeSupabaseClient()
    summary = import_cases(config, env="demo", client=fake_client)

    assert summary.total_rows == 3
    assert summary.inserted == 2
    assert summary.reused == 1
    assert summary.errors == 0
    assert summary.queued == 3

    assert len(fake_client.insert_calls) == 3
    first_payload = fake_client.insert_calls[0]["payload"]
    assert first_payload["case_number"] == "CASE-001"
    assert first_payload["source"] == "INTAKE_DEFAULT"
    assert first_payload["title"] == "Acme Funding LLC v. Jordan Rivera"
    assert first_payload["amount_awarded"] == pytest.approx(18750.0)
    assert first_payload["metadata"]["plaintiff_name"] == "Acme Funding LLC"

    assert len(fake_client.queue_calls) == 3
    idempotency_values = [
        call["payload"]["idempotency_key"] for call in fake_client.queue_calls
    ]
    assert idempotency_values == [
        "INTAKE_DEFAULT:CASE-001",
        "INTAKE_DEFAULT:CASE-002",
        "INTAKE_DEFAULT:CASE-001",
    ]


def test_import_cases_dry_run_does_not_call_supabase(tmp_path: Path):
    csv_content = (
        "case_number,court,plaintiff_name,defendant_name,judgment_amount,judgment_date,source\n"
        "CASE-100,Queens County Civil Court,Empire Credit Partners,Alicia Patel,2450.00,2024-05-20,DEMO_BATCH\n"
    )
    csv_path = write_csv(tmp_path, csv_content)

    config = ImportConfig(
        csv_path=csv_path,
        dry_run=True,
        source_tag=None,
        enqueue_enrich=True,
    )

    fake_client = FakeSupabaseClient()
    summary = import_cases(config, env="demo", client=fake_client)

    assert summary.total_rows == 1
    assert summary.inserted == 0
    assert summary.reused == 0
    assert summary.errors == 0
    assert summary.queued == 0

    assert fake_client.insert_calls == []
    assert fake_client.queue_calls == []


def test_import_cases_skips_invalid_rows(tmp_path: Path):
    csv_content = (
        "case_number,court,plaintiff_name,defendant_name,judgment_amount,judgment_date,source\n"
        ",Kings County Civil Court,Acme Funding LLC,Jordan Rivera,18750.00,2024-09-15,INTAKE_BATCH\n"
        "CASE-010,Bronx Civil Court,Falcon Capital LLC,Taylor Price,not-a-number,2024-10-01,INTAKE_BATCH\n"
        "CASE-011,Bronx Civil Court,Falcon Capital LLC,Taylor Price,18750.00,2024-10-01,\n"
    )
    csv_path = write_csv(tmp_path, csv_content)

    config = ImportConfig(
        csv_path=csv_path,
        dry_run=False,
        source_tag="INTAKE_BATCH",
        enqueue_enrich=True,
    )

    fake_client = FakeSupabaseClient()
    summary = import_cases(config, env="demo", client=fake_client)

    assert summary.total_rows == 3
    assert summary.inserted == 1
    assert summary.reused == 0
    assert summary.errors == 2
    assert summary.queued == 1

    assert len(fake_client.insert_calls) == 1
    payload = fake_client.insert_calls[0]["payload"]
    assert payload["case_number"] == "CASE-011"
    assert payload["source"] == "INTAKE_BATCH"

    assert len(fake_client.queue_calls) == 1
