"""Dedicated worker loop for enforcement escalation brain jobs."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any, Dict, Optional

from brain.escalation_engine import (
    EscalationDecision,
    EscalationEngine,
    EscalationSignals,
)
from workers.handlers import extract_case_id
from workers.runner import worker_loop

from src.supabase_client import create_supabase_client

logger = logging.getLogger(__name__)
_ENGINE: Optional[EscalationEngine] = None
_SUPABASE = None


def _get_engine() -> EscalationEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = EscalationEngine()
    return _ENGINE


def _get_supabase():
    global _SUPABASE
    if _SUPABASE is None:
        _SUPABASE = create_supabase_client()
    return _SUPABASE


def _normalize_row(row: Dict[str, Any]) -> EscalationSignals:
    def _to_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _to_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    return EscalationSignals(
        collectability_score=_to_float(row.get("collectability_score")),
        attempts_last_30=int(row.get("attempts_last_30") or 0),
        days_since_last_activity=_to_int(row.get("days_since_last_activity")),
        evidence_items=int(row.get("evidence_items") or 0),
        judgment_age_days=_to_int(row.get("judgment_age_days")),
    )


def _fetch_signals(case_id: str) -> EscalationSignals:
    client = _get_supabase()
    response = client.rpc("evaluate_enforcement_path", {"case_id": case_id}).execute()
    data = getattr(response, "data", None)
    if isinstance(data, list):
        row = data[0] if data else None
    elif isinstance(data, dict):
        row = data
    else:
        row = None
    if not isinstance(row, dict):
        raise RuntimeError(
            f"evaluate_enforcement_path returned no data for case {case_id}"
        )
    return _normalize_row(row)


def _record_decision(
    case_id: str, decision: EscalationDecision, signals: EscalationSignals
) -> None:
    client = _get_supabase()
    metadata = {
        "escalate_to": decision.escalate_to,
        "confidence": decision.confidence,
        "reasons": list(decision.reasons),
        "signals": asdict(signals),
    }
    entry = {
        "case_id": case_id,
        "event_type": "escalation_brain",
        "notes": f"Recommend {decision.escalate_to}",
        "metadata": metadata,
    }
    client.table("enforcement_events").insert(entry).execute()


def _extract_payload(job: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(job, dict):
        return {}
    payload = job.get("payload")
    if isinstance(payload, dict):
        nested = payload.get("payload")
        if isinstance(nested, dict):
            return nested
        return payload
    return {}


async def handle_escalation(job: Dict[str, Any]) -> bool:
    payload = _extract_payload(job)
    case_id = extract_case_id(job) or payload.get("case_id")
    if not case_id:
        raise ValueError("escalation job missing case_id")

    case_id_str = str(case_id).strip()
    signals = _fetch_signals(case_id_str)
    engine = _get_engine()
    decision = engine.evaluate(signals)
    _record_decision(case_id_str, decision, signals)

    logger.info(
        "escalation_brain_decision case_id=%s target=%s confidence=%.2f attempts=%s evidence=%s",
        case_id_str,
        decision.escalate_to,
        decision.confidence,
        signals.attempts_last_30,
        signals.evidence_items,
    )
    return True


if __name__ == "__main__":
    asyncio.run(worker_loop("escalation", handle_escalation))
