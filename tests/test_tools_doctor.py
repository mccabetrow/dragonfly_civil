from __future__ import annotations

from click.testing import CliRunner

from tools import doctor


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, name: str, client: "FakeClient") -> None:
        self.name = name
        self.client = client
        self._operation: str | None = None
        self._payload: dict[str, object] | None = None
        self._eq_value: object | None = None

    def select(self, _columns: str) -> "FakeTable":
        self._operation = "select"
        return self

    def limit(self, _limit: int) -> "FakeTable":
        return self

    def execute(self) -> FakeResponse:
        if self.name == "judgments" and self._operation == "select":
            return FakeResponse([{"case_id": FakeClient.CASE_UUID}])
        if self.name == "v_cases_with_org" and self._operation == "select":
            return FakeResponse([{"case_id": FakeClient.CASE_UUID}])
        if self.name == "v_collectability_snapshot" and self._operation == "select":
            return FakeResponse([{"case_id": FakeClient.CASE_UUID}])
        if self.name == "enrichment_runs" and self._operation == "select":
            return FakeResponse([])
        if self.name == "enrichment_runs" and self._operation == "insert" and self._payload is not None:
            inserted = dict(self._payload)
            inserted.setdefault("id", 99)
            self.client.inserted_rows.append(inserted)
            return FakeResponse([inserted])
        if self.name == "enrichment_runs" and self._operation == "delete":
            self.client.deleted_ids.append(self._eq_value)
            return FakeResponse([])
        return FakeResponse([])

    def insert(self, payload: dict[str, object]) -> "FakeTable":
        self._operation = "insert"
        self._payload = payload
        return self

    def delete(self) -> "FakeTable":
        self._operation = "delete"
        return self

    def eq(self, _column: str, value: object) -> "FakeTable":
        self._eq_value = value
        return self


class FakeRpc:
    def __init__(self, client: "FakeClient") -> None:
        self.client = client

    def execute(self) -> FakeResponse:
        self.client.rpc_calls += 1
        return FakeResponse({"queue_job": 1})


class FakeClient:
    def __init__(self) -> None:
        self.inserted_rows: list[dict[str, object]] = []
        self.deleted_ids: list[object] = []
        self.rpc_calls = 0
        self.case_view_lookups = 0
        self.snapshot_lookups = 0

    CASE_UUID = "00000000-0000-0000-0000-000000000016"

    def table(self, name: str) -> FakeTable:
        if name == "v_cases_with_org":
            self.case_view_lookups += 1
        if name == "v_collectability_snapshot":
            self.snapshot_lookups += 1
        return FakeTable(name, self)

    def rpc(self, _name: str, _payload: dict[str, object]) -> FakeRpc:
        return FakeRpc(self)


def test_doctor_reports_enrichment_runs_write_success(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(doctor, "create_supabase_client", lambda: fake_client)
    monkeypatch.setattr(doctor, "_generate_enrichment_run_id", lambda: 4242)
    monkeypatch.setattr(doctor, "_count_foil_responses", lambda: 0)

    runner = CliRunner()
    result = runner.invoke(doctor.main)

    assert result.exit_code == 0
    assert "enrichment_runs write OK" in result.output
    assert fake_client.inserted_rows
    assert fake_client.deleted_ids == [4242]
    assert fake_client.inserted_rows[0]["id"] == 4242
    assert fake_client.rpc_calls == 1
    assert fake_client.inserted_rows[0]["case_id"] == FakeClient.CASE_UUID
    assert fake_client.case_view_lookups == 1
    assert fake_client.snapshot_lookups == 1
    assert "collectability snapshot check OK" in result.output
    assert "foil_responses check OK, rows=0" in result.output
