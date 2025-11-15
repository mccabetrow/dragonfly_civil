import logging
from types import SimpleNamespace

from etl.src import worker_enrich


class FakeQueue:
    def __init__(self, job):
        self.job = job
        self.ack_calls = []
        self.dequeue_calls = 0

    def dequeue(self, kind):
        self.dequeue_calls += 1
        assert kind == worker_enrich.QUEUE_KIND
        return self.job

    def ack(self, kind, msg_id):
        self.ack_calls.append((kind, msg_id))
        return True


def test_process_once_success_ack(monkeypatch):
    job = {
        "msg_id": 42,
        "payload": {"payload": {"case_id": "case-1", "case_number": "CASE-1"}},
    }
    queue = FakeQueue(job)

    def fake_run(case_id, payload):
        assert case_id == "case-1"
        assert payload["case_id"] == "case-1"
        return {"status": "success"}

    monkeypatch.setattr(worker_enrich, "run_enrichment_bundle", fake_run)

    result = worker_enrich.process_once(queue)  # type: ignore[arg-type]

    assert result is worker_enrich.JobResult.SUCCESS
    assert queue.ack_calls == [(worker_enrich.QUEUE_KIND, 42)]


def test_process_once_missing_case_id(monkeypatch, caplog):
    job = {
        "msg_id": 8,
        "payload": {"payload": {"case_number": "CASE-2"}},
    }
    queue = FakeQueue(job)

    def fail_run(*_args, **_kwargs):  # pragma: no cover - defensive
        raise AssertionError("run_enrichment_bundle should not be called")

    monkeypatch.setattr(worker_enrich, "run_enrichment_bundle", fail_run)

    with caplog.at_level(logging.ERROR):
        result = worker_enrich.process_once(queue)  # type: ignore[arg-type]

    assert result is worker_enrich.JobResult.ERROR
    assert not queue.ack_calls
    assert "missing case_id" in " ".join(caplog.messages).lower()


def test_process_once_error_result(monkeypatch, caplog):
    job = {
        "msg_id": 99,
        "payload": {"payload": {"case_id": "case-3", "force_error": True}},
    }
    queue = FakeQueue(job)

    def fake_run(case_id, payload):
        assert case_id == "case-3"
        assert payload["force_error"] is True
        return {"status": "error", "error": "forced"}

    monkeypatch.setattr(worker_enrich, "run_enrichment_bundle", fake_run)

    with caplog.at_level(logging.ERROR):
        result = worker_enrich.process_once(queue)  # type: ignore[arg-type]

    assert result is worker_enrich.JobResult.ERROR
    assert not queue.ack_calls
    assert "forced" in " ".join(caplog.messages)


def test_run_enrichment_bundle_records_success(monkeypatch):
    inserts = []

    snapshot_row = {
        "case_id": "case-4",
        "case_number": "CN-4",
        "judgment_amount": "3200",
        "age_days": 90,
        "collectability_tier": "B",
        "judgment_date": "2024-01-15",
    }

    class FakeTable:
        def insert(self, payload):
            inserts.append(payload)
            return self

        def execute(self):
            return self

    class FakeSnapshotTable:
        def __init__(self):
            self.eq_calls = []

        def select(self, _fields):
            return self

        def eq(self, column, value):
            self.eq_calls.append((column, value))
            return self

        def limit(self, _value):
            return self

        def execute(self):
            return SimpleNamespace(data=[snapshot_row])

    class FakeClient:
        def __init__(self):
            self._insert_table = FakeTable()
            self._snapshot_table = FakeSnapshotTable()

        def table(self, name):
            if name == "enrichment_runs":
                return self._insert_table
            if name == "v_collectability_snapshot":
                return self._snapshot_table
            raise AssertionError(f"unexpected table {name}")

    monkeypatch.setattr(worker_enrich, "create_supabase_client", lambda: FakeClient())

    payload = {"case_id": "case-4", "case_number": "CN-4"}
    result = worker_enrich.run_enrichment_bundle("case-4", payload)

    assert result["status"] == "success"
    assert result["tier_hint"] == "B"
    assert result["collectability_score"] > 0
    assert inserts
    record = inserts[0]
    assert record["case_id"] == "case-4"
    assert record["status"] == "success"
    assert record["summary"].startswith("Collectability tier B")
    assert record["raw"]["bundle"] == "stub:v1"
    assert record["raw"]["tier_hint"] == "B"
    assert record["raw"]["metrics"]["judgment_amount"] == "3200.00"
    assert record["raw"]["metrics"]["age_days"] == 90
    assert record["raw"]["source_payload"] == payload


def test_run_enrichment_bundle_records_error(monkeypatch):
    inserts = []

    class FakeTable:
        def insert(self, payload):
            inserts.append(payload)
            return self

        def execute(self):
            return self

    class FakeClient:
        def table(self, name):
            assert name == "enrichment_runs"
            return FakeTable()

    monkeypatch.setattr(worker_enrich, "create_supabase_client", lambda: FakeClient())

    payload = {"case_id": "case-5", "force_error": True}
    result = worker_enrich.run_enrichment_bundle("case-5", payload)

    assert result["status"] == "error"
    assert inserts
    record = inserts[0]
    assert record["status"] == "error"
    assert "force_error" in record["summary"]
    assert "force_error" in record["raw"]["error"]
    assert record["raw"]["payload"] == payload
