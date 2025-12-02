from __future__ import annotations

import asyncio

import httpx
import pytest

from workers import runner


def _http_error(status: int, body: str) -> httpx.HTTPStatusError:
    request = httpx.Request(
        "POST", "https://example.supabase.co/rest/v1/rpc/dequeue_job"
    )
    response = httpx.Response(status, request=request, text=body)
    return httpx.HTTPStatusError(f"{status} error", request=request, response=response)


@pytest.mark.asyncio
async def test_worker_loop_exits_on_http_error(monkeypatch, caplog):
    error = _http_error(500, "internal failure")
    instances: list[object] = []

    class FakeQueueClient:
        def __init__(self):
            self.closed = False
            instances.append(self)

        def dequeue(self, kind):  # noqa: D401 - test stub
            raise error

        def ack(self, kind, msg_id):  # noqa: D401 - test stub
            return True

        def close(self):
            self.closed = True

    monkeypatch.setattr(runner, "QueueClient", FakeQueueClient)

    async def noop_handler(job):  # noqa: ANN001 - testing signature
        return True

    with caplog.at_level("CRITICAL"):
        await runner.worker_loop("enforce", noop_handler, poll_interval=0.01)

    assert instances and instances[0].closed is True
    assert any(
        "queue_rpc_http_error" in record.getMessage() for record in caplog.records
    )


@pytest.mark.asyncio
async def test_worker_loop_exits_on_ack_http_error(monkeypatch, caplog):
    error = _http_error(400, "bad ack payload")
    instances: list[object] = []

    class FakeQueueClient:
        def __init__(self):
            self.closed = False
            self._dequeue_calls = 0
            instances.append(self)

        def dequeue(self, kind):
            if self._dequeue_calls == 0:
                self._dequeue_calls += 1
                return {"msg_id": 99, "payload": {}}
            return None

        def ack(self, kind, msg_id):
            raise error

        def close(self):
            self.closed = True

        @property
        def rpc_base_url(self):
            return "https://example.supabase.co/rest/v1/rpc"

    monkeypatch.setattr(runner, "QueueClient", FakeQueueClient)

    async def noop_handler(job):  # noqa: ANN001 - testing signature
        return True

    with caplog.at_level("CRITICAL"):
        await runner.worker_loop("case_copilot", noop_handler, poll_interval=0.01)

    assert instances and instances[0].closed is True
    assert any(
        "queue_ack_http_error" in record.getMessage() for record in caplog.records
    )
