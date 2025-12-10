from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class StubEnrichmentResult:
    """Structured result for the stub enrichment bundle."""

    summary: str
    raw: dict[str, Any]


_CONFIDENCE_BY_TIER: dict[str, float] = {
    "A": 0.85,
    "B": 0.72,
    "C": 0.58,
}

_NEXT_STEPS_BY_TIER: dict[str, list[str]] = {
    "A": [
        "Confirm contact information",
        "Schedule outbound collector call",
        "Queue banking asset sweep",
    ],
    "B": [
        "Verify party identity",
        "Send follow-up notice",
        "Ready packet for outreach queue",
    ],
    "C": [
        "Flag for manual review",
        "Collect missing documents",
        "Re-score after outreach",
    ],
}


def build_stub_enrichment(
    case_id: str,
    snapshot: Mapping[str, Any] | None,
    *,
    job_payload: Mapping[str, Any] | None = None,
) -> StubEnrichmentResult:
    """Return a predictable stub enrichment payload for the given case."""

    snapshot_dict = dict(snapshot or {})
    job_payload_dict = dict(job_payload or {})

    case_number = (
        _as_str(snapshot_dict.get("case_number") or job_payload_dict.get("case_number")) or case_id
    )

    amount = _coerce_decimal(
        snapshot_dict.get("judgment_amount")
        or job_payload_dict.get("judgment_amount")
        or job_payload_dict.get("amount_awarded")
    )
    age_days = _coerce_age_days(snapshot_dict, job_payload_dict)

    score = _score_from(amount, age_days)
    tier_hint = _tier_from_score(score, snapshot_dict.get("collectability_tier"))
    confidence = _CONFIDENCE_BY_TIER.get(tier_hint, 0.6)

    amount_bucket = _amount_bucket(amount)
    age_bucket = _age_bucket(age_days)

    signals = {
        "amount_bucket": amount_bucket,
        "age_bucket": age_bucket,
        "recent_judgment": age_days is not None and age_days <= 180,
        "needs_manual_review": tier_hint == "C",
    }

    insights: list[dict[str, Any]] = [
        {
            "code": "collectability_score",
            "label": "Collectability score",
            "value": score,
        },
        {
            "code": "judgment_amount",
            "label": "Judgment amount",
            "value": _format_amount(amount) or "n/a",
        },
        {
            "code": "age_days",
            "label": "Debt age (days)",
            "value": age_days,
        },
    ]

    raw_payload = {
        "bundle": "stub:v1",
        "generated_at": _now_iso(),
        "case_id": case_id,
        "case_number": case_number,
        "collectability_score": score,
        "tier_hint": tier_hint,
        "confidence": confidence,
        "signals": signals,
        "metrics": {
            "judgment_amount": _format_amount(amount),
            "age_days": age_days,
        },
        "insights": insights,
        "next_steps": list(_NEXT_STEPS_BY_TIER.get(tier_hint, _NEXT_STEPS_BY_TIER["C"])),
        "source_payload": job_payload_dict,
    }

    summary = f"Collectability tier {tier_hint} · score {score}/100 (stub)"

    return StubEnrichmentResult(summary=summary, raw=raw_payload)


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        cleaned = cleaned.replace("$", "").replace(",", "")
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None
    return None


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date()
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1]
        try:
            return datetime.fromisoformat(cleaned).date()
        except ValueError:
            return None
    return None


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, bool):  # bool is subclass of int; ignore
        return 1 if value else 0
    if isinstance(value, float):
        return int(value)
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            try:
                return int(float(stripped))
            except ValueError:
                return None
    return None


def _coerce_age_days(snapshot: Mapping[str, Any], job_payload: Mapping[str, Any]) -> Optional[int]:
    direct = _coerce_int(snapshot.get("age_days")) or _coerce_int(job_payload.get("age_days"))
    if direct is not None and direct >= 0:
        return direct

    judgment_date = snapshot.get("judgment_date") or job_payload.get("judgment_date")
    parsed = _parse_date(judgment_date)
    if parsed is None:
        return None
    today = datetime.now(timezone.utc).date()
    delta = (today - parsed).days
    return max(delta, 0)


def _score_from(amount: Optional[Decimal], age_days: Optional[int]) -> int:
    score = 45
    if amount is not None:
        if amount >= Decimal("6000"):
            score += 30
        elif amount >= Decimal("4000"):
            score += 24
        elif amount >= Decimal("2500"):
            score += 18
        elif amount >= Decimal("1000"):
            score += 12
        elif amount > 0:
            score += 6
    else:
        score += 3

    if age_days is not None:
        if age_days <= 120:
            score += 15
        elif age_days <= 365:
            score += 8
        elif age_days <= 1095:
            score += 2
        else:
            score -= 8
    else:
        score += 2

    return max(5, min(95, score))


def _tier_from_score(score: int, explicit: Any) -> str:
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip().upper()
    if score >= 75:
        return "A"
    if score >= 55:
        return "B"
    return "C"


def _amount_bucket(amount: Optional[Decimal]) -> str:
    if amount is None:
        return "unknown"
    if amount >= Decimal("5000"):
        return "high"
    if amount >= Decimal("1500"):
        return "mid"
    if amount > 0:
        return "low"
    return "unknown"


def _age_bucket(age_days: Optional[int]) -> str:
    if age_days is None:
        return "unknown"
    if age_days <= 120:
        return "fresh"
    if age_days <= 365:
        return "recent"
    if age_days <= 1095:
        return "seasoned"
    return "stale"


def _format_amount(amount: Optional[Decimal]) -> Optional[str]:
    if amount is None:
        return None
    quantized = amount.quantize(Decimal("0.01"))
    return f"{quantized:.2f}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
