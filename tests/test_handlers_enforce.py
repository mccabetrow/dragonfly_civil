"""
tests/test_handlers_enforce.py

Modernized tests for the enforce workflow handler.

Updated to match current production behavior:
- Status is always "enforcement_open" (not "enforcement_pending")
- Log message format: "Enforcement flow %s spawned for case %s (%s tasks)"
- No demo short-circuit behavior exists in production
"""

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
    """Test that handle_enforce calls the RPC and updates status to enforcement_open."""
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
    # Verify RPC was called with correct params
    assert (
        "rpc",
        "spawn_enforcement_flow",
        {"case_number": "SIM-0003", "template_code": "CUSTOM_FLOW"},
    ) in fake_supabase
    # Verify status is set to enforcement_open (not enforcement_pending)
    assert ("update", "judgments", {"status": "enforcement_open"}) in fake_supabase
    # Verify log message matches production format
    assert any(
        "Enforcement flow" in record.getMessage()
        and "spawned for case" in record.getMessage()
        and "SIM-0003" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_handle_enforce_empty_rpc_response(monkeypatch, caplog):
    """
    Test behavior when RPC returns empty response.

    Production still sets enforcement_open and logs success with 0 tasks.
    """
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

    with caplog.at_level("INFO"):
        result = await handlers.handle_enforce(job)

    assert result is True
    # RPC should still be called
    assert any(call[0] == "rpc" for call in calls)
    # Status is ALWAYS enforcement_open in production (even with empty response)
    assert ("update", "judgments", {"status": "enforcement_open"}) in calls
    # Logs should show 0 tasks
    assert any(
        "Enforcement flow" in record.getMessage() and "(0 tasks)" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_handle_enforce_uses_default_template(fake_supabase, monkeypatch, caplog):
    """Test that handle_enforce uses INFO_SUBPOENA_FLOW as default template."""
    monkeypatch.setattr(handlers, "is_demo_env", lambda: False)
    job = {
        "msg_id": 555,
        "idempotency_key": "enforce:SIM-0005",
        "payload": {"payload": {"case_number": "SIM-0005"}},  # No template_code
    }

    with caplog.at_level("INFO"):
        result = await handlers.handle_enforce(job)

    assert result is True
    # Should use default template
    assert (
        "rpc",
        "spawn_enforcement_flow",
        {"case_number": "SIM-0005", "template_code": "INFO_SUBPOENA_FLOW"},
    ) in fake_supabase
    # Status should be enforcement_open
    assert ("update", "judgments", {"status": "enforcement_open"}) in fake_supabase


@pytest.mark.asyncio
async def test_handle_enforce_missing_case_number(fake_supabase, monkeypatch):
    """Test that handle_enforce raises ValueError when case_number is missing."""
    monkeypatch.setattr(handlers, "is_demo_env", lambda: False)
    job = {
        "msg_id": 666,
        "idempotency_key": "enforce:missing",
        "payload": {"payload": {}},  # No case_number
    }

    with pytest.raises(ValueError, match="Missing case_number"):
        await handlers.handle_enforce(job)
