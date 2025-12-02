from types import SimpleNamespace

import pytest

from workers import handlers


class FakeRpcResponse:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self


class FakeTable:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    def update(self, payload):
        self.calls.append(("update", self.name, payload))
        return self

    def eq(self, column, value):
        self.calls.append(("eq", self.name, column, value))
        return self

    def execute(self):
        self.calls.append(("execute", self.name))
        return self


class FakeSupabaseClient:
    def __init__(self, calls, rpc_response=None, rpc_error=None):
        self.calls = calls
        self._rpc_response = rpc_response
        self._rpc_error = rpc_error

    def table(self, name):
        return FakeTable(name, self.calls)

    def rpc(self, name, params):
        self.calls.append(("rpc", name, params))
        if self._rpc_error is not None:
            raise self._rpc_error
        payload = (
            self._rpc_response
            if self._rpc_response is not None
            else {"spawn_enforcement_flow": ["task-1"]}
        )
        return FakeRpcResponse(payload)


@pytest.fixture
def fake_supabase(monkeypatch):
    calls = []
    client = FakeSupabaseClient(calls)
    monkeypatch.setattr(handlers, "_SUPABASE_CLIENT", client)
    monkeypatch.setattr(handlers, "_get_supabase_client", lambda: client)
    monkeypatch.setattr(handlers, "create_supabase_client", lambda: client)
    return calls


@pytest.mark.asyncio
async def test_handle_enforce_spawns_flow(fake_supabase, monkeypatch, caplog):
    monkeypatch.setattr(handlers, "is_demo_env", lambda: False)
    job = {
        "msg_id": 789,
        "idempotency_key": "enforce:SIM-0003",
        "payload": {
            "payload": {"case_number": "SIM-0003", "template_code": "CUSTOM_FLOW"}
        },
    }

    with caplog.at_level("INFO"):
        result = await handlers.handle_enforce(job)

    assert result is True
    assert (
        "rpc",
        "spawn_enforcement_flow",
        {"case_number": "SIM-0003", "template_code": "CUSTOM_FLOW"},
    ) in fake_supabase
    assert ("update", "judgments", {"status": "enforcement_open"}) in fake_supabase
    assert any(
        "enforce_flow_spawned" in record.getMessage()
        and "idempotency_key=enforce:SIM-0003" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_handle_enforce_missing_rpc_ack(monkeypatch, caplog):
    calls = []
    client = FakeSupabaseClient(calls, rpc_response={})

    monkeypatch.setattr(handlers, "_SUPABASE_CLIENT", client)
    monkeypatch.setattr(handlers, "_get_supabase_client", lambda: client)
    monkeypatch.setattr(handlers, "create_supabase_client", lambda: client)
    monkeypatch.setattr(handlers, "is_demo_env", lambda: False)

    job = {
        "msg_id": 123,
        "idempotency_key": "enforce:SIM-0004",
        "payload": {"payload": {"case_number": "SIM-0004"}},
    }

    with caplog.at_level("WARNING"):
        result = await handlers.handle_enforce(job)

    assert result is True
    assert any(call[0] == "rpc" for call in calls)
    assert ("update", "judgments", {"status": "enforcement_pending"}) in calls
    assert any(
        "spawn_enforcement_flow_missing" in record.getMessage()
        and "idempotency_key=enforce:SIM-0004" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_handle_enforce_demo_short_circuit(fake_supabase, monkeypatch, caplog):
    monkeypatch.setattr(handlers, "is_demo_env", lambda: True)
    job = {
        "msg_id": 555,
        "idempotency_key": "demo:SIM-0005",
        "payload": {
            "payload": {"case_number": "SIM-0005", "template_code": "DEMO_FLOW"}
        },
    }

    with caplog.at_level("INFO"):
        result = await handlers.handle_enforce(job)

    assert result is True
    assert ("update", "judgments", {"status": "enforcement_pending"}) in fake_supabase
    assert not any(call[0] == "rpc" for call in fake_supabase)
    assert any(
        "enforce_demo_short_circuit" in record.getMessage() for record in caplog.records
    )
    assert any(
        "idempotency_key=demo:SIM-0005" in record.getMessage()
        for record in caplog.records
    )
