"""FastAPI service for validating and refreshing WebCivil sessions."""

from __future__ import annotations

import os
import time
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import FastAPI, Query

from ..telemetry.auth import record_auth_event
from ..utils.log import event, get_logger
from .session_manager import (
    CircuitOpenError,
    SessionValidationError,
    ensure_session,
    load_session,
    validate_session,
)

try:  # pragma: no cover - uvicorn only needed when executed as script
    import uvicorn
except Exception:  # pragma: no cover
    uvicorn = None

__all__ = ["app", "main"]

_LOG = get_logger(__name__)

app = FastAPI(title="Dragonfly Auth Session Service", version="1.0.0")


def _parse_run_id(raw: Optional[str]) -> Optional[UUID]:
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        _LOG.warning("Ignoring invalid run_id query parameter: %s", raw)
        return None


def _record_validation_event(ok: bool, latency_ms: int, *, reason: Optional[str], run_id: Optional[UUID]) -> None:
    record_auth_event("validate", ok=ok, latency_ms=latency_ms, reason=reason, run_id=run_id)


@app.get("/auth/validate-refresh")
def validate_refresh_endpoint(
    refresh: int = Query(0, ge=0, le=1, description="Refresh the session if validation fails"),
    run_id: Optional[str] = Query(None, description="Optional run identifier for telemetry"),
) -> dict[str, Any]:
    parsed_run_id = _parse_run_id(run_id) or uuid4()
    refreshed = False

    try:
        cookies = load_session()
    except Exception as exc:  # pragma: no cover - unexpected read errors
        _LOG.error("Failed to load cached session: %s", exc)
        record_auth_event("error", ok=False, latency_ms=0, reason=f"load_failed:{exc}", run_id=parsed_run_id)
        return {"ok": False, "refreshed": False, "reason": f"load_failed:{exc}"}

    if not cookies:
        reason = "missing_session"
        event("auth.validation", status="missing_session", refreshed=False)
        if refresh:
            return _attempt_refresh(parsed_run_id)
        return {"ok": False, "refreshed": False, "reason": reason}

    validation_started = time.perf_counter()
    try:
        is_valid = bool(validate_session(cookies))
    except SessionValidationError as exc:
        latency_ms = max(int((time.perf_counter() - validation_started) * 1_000), 0)
        _record_validation_event(False, latency_ms, reason=str(exc), run_id=parsed_run_id)
        event("auth.validation", status="validation_error", error=str(exc), refreshed=False)
        if refresh:
            return _attempt_refresh(parsed_run_id)
        return {"ok": False, "refreshed": False, "reason": f"validation_error:{exc}"}

    latency_ms = max(int((time.perf_counter() - validation_started) * 1_000), 0)
    if is_valid:
        _record_validation_event(True, latency_ms, reason=None, run_id=parsed_run_id)
        event("auth.validation", status="ok", refreshed=False)
        return {"ok": True, "refreshed": refreshed, "reason": None}

    _record_validation_event(False, latency_ms, reason="invalid_session", run_id=parsed_run_id)
    event("auth.validation", status="invalid_session", refreshed=False)

    if not refresh:
        return {"ok": False, "refreshed": False, "reason": "invalid_session"}

    return _attempt_refresh(parsed_run_id)


def _attempt_refresh(run_id: UUID) -> dict[str, Any]:
    refreshed = False
    try:
        refreshed_cookies = ensure_session(force_refresh=True, run_id=run_id)
        refreshed = True
    except CircuitOpenError as exc:
        event("auth.validation", status="circuit_open", error=str(exc), refreshed=False)
        return {"ok": False, "refreshed": False, "reason": f"circuit_open:{exc}"}
    except Exception as exc:  # pragma: no cover - network/login guard
        event("auth.validation", status="refresh_failed", error=str(exc), refreshed=False)
        return {"ok": False, "refreshed": False, "reason": f"refresh_failed:{exc}"}

    validation_started = time.perf_counter()
    try:
        is_valid = bool(validate_session(refreshed_cookies))
    except SessionValidationError as exc:
        latency_ms = max(int((time.perf_counter() - validation_started) * 1_000), 0)
        _record_validation_event(False, latency_ms, reason=f"post_refresh:{exc}", run_id=run_id)
        event("auth.validation", status="post_refresh_validation_error", error=str(exc), refreshed=True)
        return {"ok": False, "refreshed": refreshed, "reason": f"post_refresh_validation_error:{exc}"}

    latency_ms = max(int((time.perf_counter() - validation_started) * 1_000), 0)
    if not is_valid:
        _record_validation_event(False, latency_ms, reason="post_refresh_invalid", run_id=run_id)
        event("auth.validation", status="post_refresh_invalid", refreshed=True)
        return {"ok": False, "refreshed": refreshed, "reason": "post_refresh_invalid"}

    _record_validation_event(True, latency_ms, reason=None, run_id=run_id)
    event("auth.validation", status="ok", refreshed=True)
    return {"ok": True, "refreshed": refreshed, "reason": None}


def main() -> None:  # pragma: no cover - manual execution helper
    if uvicorn is None:
        raise RuntimeError("uvicorn is required to run this service")
    host = os.environ.get("AUTH_SERVICE_HOST", "127.0.0.1")
    port = int(os.environ.get("AUTH_SERVICE_PORT", "8787"))
    uvicorn.run(
        "etl.src.auth.validation_service:app",
        host=host,
        port=port,
        reload=False,
        factory=False,
    )


if __name__ == "__main__":  # pragma: no cover
    main()