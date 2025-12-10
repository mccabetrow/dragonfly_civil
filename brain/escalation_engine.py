from __future__ import annotations

"""Rule-based Enforcement Escalation Brain."""

from dataclasses import dataclass
from typing import Dict, List, Sequence

_ALLOWED_TARGETS: tuple[str, ...] = (
    "garnishment",
    "levy",
    "skiptrace_refresh",
    "attorney_review",
)


@dataclass(frozen=True)
class EscalationSignals:
    collectability_score: float
    attempts_last_30: int
    days_since_last_activity: int | None
    evidence_items: int
    judgment_age_days: int | None

    def normalized_attempts(self) -> int:
        return max(0, int(self.attempts_last_30))

    def normalized_days_since_activity(self) -> int | None:
        return (
            int(self.days_since_last_activity)
            if self.days_since_last_activity is not None
            else None
        )

    def normalized_evidence(self) -> int:
        return max(0, int(self.evidence_items))

    def normalized_collectability(self) -> float:
        return max(0.0, float(self.collectability_score))

    def normalized_age(self) -> int | None:
        return int(self.judgment_age_days) if self.judgment_age_days is not None else None


@dataclass(frozen=True)
class EscalationDecision:
    escalate_to: str
    confidence: float
    reasons: Sequence[str]


class EscalationEngine:
    """Deterministic scoring engine that maps enforcement signals to a target action."""

    def __init__(
        self,
        *,
        high_collectability: float = 75.0,
        medium_collectability: float = 55.0,
        evidence_confident: int = 3,
        stale_activity_days: int = 45,
        stale_judgment_days: int = 1095,
        aged_out_days: int = 1825,
    ) -> None:
        self.high_collectability = high_collectability
        self.medium_collectability = medium_collectability
        self.evidence_confident = evidence_confident
        self.stale_activity_days = stale_activity_days
        self.stale_judgment_days = stale_judgment_days
        self.aged_out_days = aged_out_days
        self._target_priority: Dict[str, int] = {
            "garnishment": 1,
            "levy": 2,
            "attorney_review": 3,
            "skiptrace_refresh": 4,
        }

    def evaluate(self, signals: EscalationSignals) -> EscalationDecision:
        scores: Dict[str, float] = {target: 0.0 for target in _ALLOWED_TARGETS}
        reasons: Dict[str, List[str]] = {target: [] for target in _ALLOWED_TARGETS}

        collectability = signals.normalized_collectability()
        attempts = signals.normalized_attempts()
        days_since = signals.normalized_days_since_activity()
        evidence = signals.normalized_evidence()
        age_days = signals.normalized_age()

        if collectability >= self.high_collectability:
            scores["garnishment"] += 3.0
            scores["levy"] += 1.0
            reasons["garnishment"].append("High collectability score favors garnishment")
        elif collectability >= self.medium_collectability:
            scores["levy"] += 2.0
            scores["garnishment"] += 0.5
            reasons["levy"].append("Mid-tier collectability supports levy prep")
        else:
            scores["skiptrace_refresh"] += 1.5
            reasons["skiptrace_refresh"].append("Low collectability suggests refreshing intel")

        if evidence >= self.evidence_confident:
            scores["garnishment"] += 1.5
            reasons["garnishment"].append("Sufficient evidence packages ready for court")
        elif evidence == 0:
            scores["skiptrace_refresh"] += 1.0
            reasons["skiptrace_refresh"].append("No evidence stored yet")
        else:
            scores["levy"] += 0.5
            reasons["levy"].append("Partial evidence available for levy paperwork")

        if days_since is not None:
            if days_since >= self.stale_activity_days:
                scores["attorney_review"] += 1.5
                reasons["attorney_review"].append("Activity stale >45 days")
                if attempts >= 5:
                    scores["attorney_review"] += 1.0
                    reasons["attorney_review"].append("Repeated attempts need attorney input")
            elif days_since <= 14 and attempts >= 4:
                scores["garnishment"] += 0.5
                scores["levy"] += 0.5
                reasons["garnishment"].append("Recent activity with multiple attempts")
        else:
            scores["skiptrace_refresh"] += 0.5
            reasons["skiptrace_refresh"].append("No activity history available")

        if attempts >= 7:
            scores["attorney_review"] += 1.0
            reasons["attorney_review"].append("High attempt count triggers legal review")
        elif attempts <= 1 and (days_since or 0) > 0:
            scores["skiptrace_refresh"] += 0.5
            reasons["skiptrace_refresh"].append("Minimal attempts recorded")

        if age_days is not None:
            if age_days >= self.aged_out_days:
                scores["skiptrace_refresh"] += 1.5
                reasons["skiptrace_refresh"].append("Judgment older than five years")
                scores["attorney_review"] += 0.5
            elif age_days >= self.stale_judgment_days:
                scores["levy"] += 1.5
                reasons["levy"].append("Judgment older than three years")
            elif age_days <= 365 and collectability >= self.medium_collectability:
                scores["garnishment"] += 1.0
                reasons["garnishment"].append("Fresh judgment with strong collectability")
        else:
            scores["attorney_review"] += 0.5
            reasons["attorney_review"].append("Missing judgment age triggers review")

        winner = max(
            scores.items(),
            key=lambda item: (item[1], -self._target_priority[item[0]]),
        )[0]

        total_score = sum(max(value, 0.0) for value in scores.values())
        confidence = round((scores[winner] / total_score) if total_score else 0.25, 2)
        winner_reasons = reasons[winner] or ["Baseline routing"]

        return EscalationDecision(
            escalate_to=winner,
            confidence=confidence,
            reasons=tuple(winner_reasons),
        )

    def evaluate_many(self, payloads: Sequence[EscalationSignals]) -> List[EscalationDecision]:
        return [self.evaluate(signals) for signals in payloads]
