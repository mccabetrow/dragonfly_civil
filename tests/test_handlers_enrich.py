from types import SimpleNamespace

import pytest

from workers import handlers


class FakeTable:
    def __init__(self, name, calls):
        self.name = name
        self._calls = calls

    def update(self, payload):
        self._calls.append(("update", self.name, payload))
        return self

    def insert(self, payload):
        self._calls.append(("insert", self.name, payload))
        return self

    def eq(self, column, value):
        self._calls.append(("eq", self.name, column, value))
        return self

    def execute(self):
        self._calls.append(("execute", self.name))
        return {"data": "ok"}


class FakeSupabaseClient:
    def __init__(self, calls):
        self._calls = calls

    def table(self, name):
        return FakeTable(name, self._calls)

    def rpc(self, name, params):
        self._calls.append(("rpc", name, params))

        class RpcResponse:
            def __init__(self, outer_calls, rpc_name):
                self._calls = outer_calls
                self.data = {"spawn_enforcement_flow": ["task-1"]}
                self._rpc_name = rpc_name

            def execute(self):
                self._calls.append(("rpc_execute", self._rpc_name))
                return self

        return RpcResponse(self._calls, name)


@pytest.fixture
def fake_supabase(monkeypatch):
    calls = []
    client = FakeSupabaseClient(calls)
    monkeypatch.setattr(handlers, "_SUPABASE_CLIENT", client)
    monkeypatch.setattr(handlers, "_get_supabase_client", lambda: client)
    monkeypatch.setattr(handlers, "create_supabase_client", lambda: client)
    return calls


@pytest.mark.asyncio
async def test_handle_enrich_updates_case_status(fake_supabase):
    job = {"msg_id": 123, "payload": {"case_number": "SIM-0001"}}

    result = await handlers.handle_enrich(job)

    assert result is True
    assert ("update", "judgments", {"status": "enrich_pending"}) in fake_supabase
    assert ("eq", "judgments", "case_number", "SIM-0001") in fake_supabase


@pytest.mark.asyncio
async def test_handle_outreach_logs_and_updates(fake_supabase):
    job = {
        "msg_id": 456,
        "payload": {"payload": {"case_number": "SIM-0002", "template_code": "TEMPLATE_A"}},
    }

    result = await handlers.handle_outreach(job)

    assert result is True
    insert_calls = [
        call for call in fake_supabase if call[0] == "insert" and call[1] == "outreach_log"
    ]
    assert insert_calls, "Expected outreach_log insert call"
    inserted_payload = insert_calls[0][2]
    assert inserted_payload["case_number"] == "SIM-0002"
    assert inserted_payload["status"] == "pending_provider"
    assert ("update", "judgments", {"status": "outreach_stubbed"}) in fake_supabase


@pytest.mark.asyncio
async def test_handle_enforce_spawns_flow(fake_supabase):
    job = {
        "msg_id": 789,
        "payload": {"payload": {"case_number": "SIM-0003", "template_code": "CUSTOM_FLOW"}},
    }

    result = await handlers.handle_enforce(job)

    assert result is True
    assert (
        "rpc",
        "spawn_enforcement_flow",
        {
            "case_number": "SIM-0003",
            "template_code": "CUSTOM_FLOW",
        },
    ) in fake_supabase
    assert ("update", "judgments", {"status": "enforcement_open"}) in fake_supabase
