import logging
from types import SimpleNamespace

import httpx
import pytest

from workers import queue_client as queue_client_module
from workers.queue_client import QueueClient, QueueRpcNotFound

SUPABASE_URL = "https://example.supabase.co"
RPC_BASE = f"{SUPABASE_URL.rstrip('/')}/rest/v1/rpc"


@pytest.fixture(autouse=True)
def stub_dependencies(monkeypatch):
    monkeypatch.setattr(queue_client_module, "create_supabase_client", lambda: SimpleNamespace())

    class DummySettings:
        supabase_url = SUPABASE_URL
        supabase_service_role_key = "service-role-key"

    monkeypatch.setattr(queue_client_module, "get_worker_settings", lambda: DummySettings())


def make_http_error(status_code: int, path: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", f"{RPC_BASE}{path}")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(f"{status_code} error", request=request, response=response)


def build_response(*, status_code: int = 200, json_data=None, content: bytes = b"", error: Exception | None = None):
    class DummyResponse:
        def __init__(self) -> None:
            self.status_code = status_code
            self.content = content

        def raise_for_status(self) -> None:
            if error:
                raise error

        def json(self):
            return json_data

    return DummyResponse()


def install_fake_client(monkeypatch, handler):
    class FakeClient:
        def __init__(self, base_url, headers, timeout):
            self.base_url = base_url
            self.headers = headers
            self.timeout = timeout

        def post(self, path, json=None):
            return handler(path, json)

        def close(self):
            return None

    monkeypatch.setattr(queue_client_module.httpx, "Client", FakeClient)
    return QueueClient()


def test_enqueue_success(monkeypatch):
    captured = {}

    def handler(path, json):
        captured["path"] = path
        captured["json"] = json
        return build_response(json_data={"queue_job": 99})

    client = install_fake_client(monkeypatch, handler)
    msg_id = client.enqueue("enrich", {"case_number": "42"}, "csv:42")

    assert msg_id == 99
    assert captured["path"] == "/queue_job"
    assert captured["json"] == {
        "payload": {
            "kind": "enrich",
            "payload": {"case_number": "42"},
            "idempotency_key": "csv:42",
        }
    }


def test_enqueue_body_keys_match_arguments(monkeypatch):
    captured = {}

    def handler(path, json):
        captured["json"] = json
        return build_response(json_data={"queue_job": 11})

    client = install_fake_client(monkeypatch, handler)
    kind = "outreach"
    payload = {"case_number": "abc"}
    idempotency_key = "csv:abc"

    client.enqueue(kind, payload, idempotency_key)

    assert captured["json"] == {
        "payload": {
            "idempotency_key": idempotency_key,
            "kind": kind,
            "payload": payload,
        }
    }


def test_enqueue_raises_when_rpc_missing(monkeypatch):
    def handler(path, json):
        error = make_http_error(404, path)
        return build_response(status_code=404, error=error)

    client = install_fake_client(monkeypatch, handler)

    with pytest.raises(QueueRpcNotFound):
        client.enqueue("enrich", {"case_number": "404"}, "csv:404")


def test_dequeue_returns_none_when_empty(monkeypatch):
    captured = {}

    def handler(path, json):
        captured["path"] = path
        captured["json"] = json
        return build_response(json_data=None)

    client = install_fake_client(monkeypatch, handler)
    result = client.dequeue("enrich")

    assert result is None
    assert captured["path"] == "/dequeue_job"
    assert captured["json"] == {"kind": "enrich"}


def test_dequeue_returns_payload(monkeypatch):
    job_payload = {"msg_id": 7, "payload": {"case_number": "ABC"}}

    def handler(path, json):
        return build_response(json_data={"dequeue_job": job_payload})

    client = install_fake_client(monkeypatch, handler)
    result = client.dequeue("enrich")

    assert result is not None
    assert result["payload"] == job_payload["payload"]
    assert result["body"] == job_payload["payload"]
    assert result["msg_id"] == job_payload["msg_id"]


def test_dequeue_aliases_body_and_payload(monkeypatch):
    job_payload = {
        "msg_id": 12,
        "read_ct": 1,
        "vt": "2025-11-14T12:00:00Z",
        "body": {"case_number": "ALIAS-01"},
    }

    def handler(path, json):
        return build_response(json_data={"dequeue_job": job_payload})

    client = install_fake_client(monkeypatch, handler)
    result = client.dequeue("enrich")

    assert result is not None
    assert result["body"] == job_payload["body"]
    assert result["payload"] == job_payload["body"]
    assert result["msg_id"] == job_payload["msg_id"]
    assert result["read_ct"] == job_payload["read_ct"]
    assert result["vt"] == job_payload["vt"]


def test_ack_ignores_404(monkeypatch, caplog):
    def handler(path, json):
        error = make_http_error(404, path)
        return build_response(status_code=404, error=error)

    client = install_fake_client(monkeypatch, handler)

    with caplog.at_level(logging.INFO):
        result = client.ack("enrich", 55)

    assert result is True
    assert any("ack_job RPC not found" in message for message in caplog.messages)
