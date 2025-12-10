"""Telemetry helpers for ETL run tracking."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from src.supabase_client import create_supabase_client

_LOG = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_json(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _coerce_json(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_coerce_json(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _prepare_details(details: dict[str, Any] | None) -> dict[str, Any] | None:
    if details is None:
        return None
    return _coerce_json(details)


def _upsert_run(payload: dict[str, Any]) -> None:
    try:
        client = create_supabase_client()
        client.table("runs").upsert(payload, on_conflict="id").execute()
    except Exception as exc:  # pragma: no cover - telemetry must be best-effort
        _LOG.warning("Failed to persist run telemetry: %s", exc)
        if "406" in str(exc) or "PGRST106" in str(exc):
            _LOG.debug(
                "Supabase responded 406 when calling /rest/v1/runs; payload=%s",
                payload,
                exc_info=True,
            )
        else:
            _LOG.debug("Run telemetry payload skipped: %s", payload, exc_info=True)


def _insert_event(payload: dict[str, Any]) -> None:
    try:
        client = create_supabase_client()
        client.table("events").insert(payload).execute()
    except Exception as exc:  # pragma: no cover - telemetry must be best-effort
        _LOG.warning("Failed to persist run event telemetry: %s", exc)
        if "406" in str(exc) or "PGRST106" in str(exc):
            _LOG.debug(
                "Supabase responded 406 when calling /rest/v1/events; payload=%s",
                payload,
                exc_info=True,
            )
        else:
            _LOG.debug("Run event payload skipped: %s", payload, exc_info=True)


def log_run_start(kind: str, details: dict[str, Any] | None = None) -> str:
    """Record the start of a run and return the run identifier."""

    run_id = str(uuid4())
    prepared_details = _prepare_details(details)
    now = _utc_now()

    run_payload: dict[str, Any] = {
        "id": run_id,
        "kind": kind,
        "status": "running",
        "started_at": now,
    }
    if prepared_details is not None:
        run_payload["details"] = prepared_details
    _upsert_run(run_payload)

    event_payload: dict[str, Any] = {
        "id": str(uuid4()),
        "run_id": run_id,
        "kind": kind,
        "event": "start",
        "status": "running",
        "details": prepared_details or {},
        "created_at": now,
    }
    _insert_event(event_payload)

    return run_id


def log_run_ok(run_id: str, details: dict[str, Any] | None = None, *, status: str = "ok") -> None:
    """Mark a run as completed successfully with the provided status."""

    prepared_details = _prepare_details(details)
    now = _utc_now()

    run_payload: dict[str, Any] = {
        "id": run_id,
        "status": status,
        "finished_at": now,
    }
    if prepared_details is not None:
        run_payload["details"] = prepared_details
    _upsert_run(run_payload)

    event_payload: dict[str, Any] = {
        "id": str(uuid4()),
        "run_id": run_id,
        "event": "finish",
        "status": status,
        "details": prepared_details or {},
        "created_at": now,
    }
    _insert_event(event_payload)


def log_run_error(run_id: str, err: dict[str, Any], details: dict[str, Any] | None = None) -> None:
    """Mark a run as failed with error context."""

    prepared_error = _prepare_details(err) or {}
    prepared_details = _prepare_details(details)
    now = _utc_now()

    run_payload: dict[str, Any] = {
        "id": run_id,
        "status": "error",
        "finished_at": now,
        "error": prepared_error,
    }
    if prepared_details is not None:
        run_payload["details"] = prepared_details
    _upsert_run(run_payload)

    event_payload: dict[str, Any] = {
        "id": str(uuid4()),
        "run_id": run_id,
        "event": "error",
        "status": "error",
        "details": prepared_details or {},
        "error": prepared_error,
        "created_at": now,
    }
    _insert_event(event_payload)
