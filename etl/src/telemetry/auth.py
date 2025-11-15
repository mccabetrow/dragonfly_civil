"""Telemetry helpers for authentication workflows."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from ..utils.log import get_logger
from ..utils.supabase import get_client

_LOG = get_logger(__name__)

AuthEventKind = Literal[
    "validate",
    "refresh",
    "error",
    "scrape_start",
    "scrape_ok",
    "scrape_error",
]


def record_auth_event(
    kind: AuthEventKind,
    ok: bool,
    latency_ms: int,
    reason: str | None,
    run_id: UUID | str | None,
) -> None:
    """Persist an authentication telemetry record to Supabase.

    Telemetry is best-effort; any error encountered while talking to Supabase
    is logged at warning level and otherwise ignored so that caller workflows
    continue without interruption.
    """

    latency_value = max(int(latency_ms), 0)
    payload: dict[str, object] = {
        "kind": kind,
        "ok": bool(ok),
        "latency_ms": latency_value,
    }
    if reason is not None:
        payload["reason"] = reason
    if run_id is not None:
        payload["run_id"] = str(run_id)

    try:
        client = get_client()
        client.schema("analytics").table("auth_sessions").upsert(payload, returning="minimal").execute()
    except Exception as exc:  # pragma: no cover - telemetry must never fail caller
        _LOG.warning("Auth telemetry submission failed: %s", exc)
        _LOG.debug("Auth telemetry payload skipped: %s", payload)