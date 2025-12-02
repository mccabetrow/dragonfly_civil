from __future__ import annotations

from brain.escalation_engine import (
    EscalationDecision,
    EscalationEngine,
    EscalationSignals,
)


def build_signals(**overrides) -> EscalationSignals:
    base = dict(
        collectability_score=60.0,
        attempts_last_30=3,
        days_since_last_activity=20,
        evidence_items=2,
        judgment_age_days=400,
    )
    base.update(overrides)
    return EscalationSignals(**base)


def test_high_collectability_prefers_garnishment() -> None:
    engine = EscalationEngine()
    signals = build_signals(
        collectability_score=82.0,
        evidence_items=4,
        days_since_last_activity=5,
        attempts_last_30=5,
        judgment_age_days=200,
    )
    decision = engine.evaluate(signals)

    assert isinstance(decision, EscalationDecision)
    assert decision.escalate_to == "garnishment"
    assert decision.confidence >= 0.4
    assert any("High collectability" in reason for reason in decision.reasons)


def test_stale_case_prefers_attorney_review() -> None:
    engine = EscalationEngine()
    signals = build_signals(
        attempts_last_30=8,
        days_since_last_activity=90,
        evidence_items=1,
        collectability_score=58.0,
    )
    decision = engine.evaluate(signals)

    assert decision.escalate_to == "attorney_review"
    assert any("stale" in reason.lower() for reason in decision.reasons)


def test_low_collectability_defaults_to_skiptrace() -> None:
    engine = EscalationEngine()
    signals = build_signals(
        collectability_score=25.0,
        attempts_last_30=1,
        days_since_last_activity=10,
        evidence_items=0,
        judgment_age_days=2200,
    )
    decision = engine.evaluate(signals)

    assert decision.escalate_to == "skiptrace_refresh"
    assert decision.confidence >= 0.4


def test_older_but_viable_case_prefers_levy() -> None:
    engine = EscalationEngine()
    signals = build_signals(
        collectability_score=62.0,
        evidence_items=2,
        attempts_last_30=3,
        days_since_last_activity=25,
        judgment_age_days=1200,
    )
    decision = engine.evaluate(signals)

    assert decision.escalate_to == "levy"
    assert decision.confidence > 0.2
