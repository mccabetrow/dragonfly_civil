from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import httpx

from src.supabase_client import create_supabase_client

from .settings import get_worker_settings

API_PREFIX = "/rest/v1/rpc"


class QueueRpcNotFound(RuntimeError):
    """Raised when Supabase RPC endpoints are missing."""


logger = logging.getLogger(__name__)


class QueueClient:
    def __init__(self) -> None:
        create_supabase_client()  # validates configuration
        settings = get_worker_settings()
        url = settings.supabase_url.rstrip("/")
        key = settings.supabase_service_role_key
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._rpc_base_url = url + API_PREFIX
        self._client = httpx.Client(base_url=self._rpc_base_url, headers=headers, timeout=10.0)

    def __enter__(self) -> "QueueClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - context helper
        self.close()

    def close(self) -> None:
        self._client.close()

    @property
    def rpc_base_url(self) -> str:
        return self._rpc_base_url

    def enqueue(
        self, kind: str, payload: Dict[str, Any], idempotency_key: Optional[str] = None
    ) -> int:
        envelope = {
            "idempotency_key": idempotency_key,
            "kind": kind,
            "payload": payload,
        }
        logger.debug("Queue enqueue request: %s", envelope)
        response = self._client.post("/queue_job", json={"payload": envelope})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.error("queue_job RPC not found at /rest/v1/rpc/queue_job")
                raise QueueRpcNotFound("queue_job RPC not found") from exc
            raise
        data = response.json()
        if isinstance(data, dict):
            msg_id = data.get("queue_job") or next(iter(data.values()), None)
        else:
            msg_id = data
        if msg_id is None:
            raise ValueError("Queue job RPC returned no message id")
        logger.debug("Enqueued %s job => id=%s", kind, msg_id)
        return int(msg_id)

    def dequeue(self, kind: str) -> Optional[Dict[str, Any]]:
        response = self._client.post("/dequeue_job", json={"kind": kind})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.error("dequeue_job RPC not found; backing off")
                time.sleep(2.0)
                return None
            raise
        payload = response.json()
        if isinstance(payload, dict) and "dequeue_job" in payload:
            payload = payload["dequeue_job"]
        if not payload:
            return None
        if isinstance(payload, dict):
            result: Dict[str, Any] = dict(payload)
            body = result.get("body")
            payload_field = result.get("payload")
            if body is not None and payload_field is None:
                result["payload"] = body
            elif payload_field is not None and body is None:
                result["body"] = payload_field
            logger.debug("Dequeued %s job: %s", kind, result)
            return result
        logger.debug("Dequeued %s job: %s", kind, payload)
        return payload

    def ack(self, kind: str, msg_id: int) -> bool:
        response = self._client.post("/ack_job", json={"kind": kind, "msg_id": msg_id})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.info("ack_job RPC not found or message %s already acknowledged", msg_id)
                return True
            raise
        if response.content:
            try:
                data = response.json()
            except ValueError:  # plain text/null
                data = None
            if isinstance(data, dict) and "ack_job" in data:
                logger.debug("Acknowledged %s job id=%s => %s", kind, msg_id, data["ack_job"])
            else:
                logger.debug("Acknowledged %s job id=%s", kind, msg_id)
        else:
            logger.debug("Acknowledged %s job id=%s", kind, msg_id)
        return True
