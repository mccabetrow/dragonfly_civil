from __future__ import annotations

import json
from textwrap import dedent
from typing import Any, Mapping
from uuid import UUID

import pytest

from src.ai import case_copilot


def _sample_context() -> dict[str, Any]:
    return {
        "case": {
            "case_id": "11111111-1111-1111-1111-111111111111",
            "case_number": "CASE-42",
            "opened_at": "2025-01-01T00:00:00Z",
            "current_stage": "asset_search",
            "status": "open",
            "assigned_to": "ops",
            "latest_event_type": "bank_subpoena",
            "latest_event_date": "2025-02-05T00:00:00Z",
        },
        "judgment": {
            "judgment_id": 42,
            "amount": 125000,
            "county": "Kings",
            "state": "NY",
            "priority_level": "high",
        },
        "timeline": [
            {
                "item_kind": "event",
                "title": "bank_subpoena",
                "details": "Awaiting response",
                "occurred_at": "2025-02-05T00:00:00Z",
            }
        ],
        "timeline_stats": {"event_count": 1, "evidence_count": 0},
        "tasks": {"open_count": 1, "overdue_count": 0, "items": []},
        "contacts": {
            "primary_contact": {
                "name": "Major Bank",
                "email": "ops@example.com",
                "phone": "555-1212",
            }
        },
        "risk_inputs": {"case_age_days": 40, "collectability_tier": "A"},
    }


class _FakeRepo(case_copilot.CaseContextRepository):
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.logged: list[dict[str, Any]] = []
        self.requested: list[str] = []

    def fetch_context(self, case_id: str) -> case_copilot.CopilotCaseContext:
        self.requested.append(case_id)
        return case_copilot.CopilotCaseContext(case_id=case_id, payload=self.payload)

    def log_invocation(
        self,
        *,
        case_id: str,
        model: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.logged.append(
            {"case_id": case_id, "model": model, "metadata": dict(metadata or {})}
        )


class _FakeAI(case_copilot.AIClient):
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def complete(self, *, system_prompt: str, user_prompt: str, model: str) -> str:
        self.prompts.append(user_prompt)
        return self.response


def test_case_copilot_service_emits_sections_and_logs() -> None:
    repo = _FakeRepo(_sample_context())
    ai_response = json.dumps(
        {
            "summary": "Case looks strong",
            "enforcement_suggestions": [
                {
                    "title": "Call plaintiff",
                    "rationale": "Need updated contact",
                    "next_step": "Schedule follow-up",
                }
            ],
            "draft_documents": [
                {
                    "title": "Demand letter",
                    "objective": "Escalate collections",
                    "key_points": ["Reference judgment", "Deadline"],
                }
            ],
            "risk": {
                "value": 42,
                "label": "Moderate",
                "drivers": ["Awaiting subpoena"],
            },
            "timeline_analysis": [
                {
                    "observation": "No new events in 30 days",
                    "impact": "stale",
                    "urgency": "high",
                }
            ],
            "contact_strategy": [
                {
                    "channel": "phone",
                    "action": "Call plaintiff partner",
                    "cadence": "weekly",
                    "notes": "summarize hurdles",
                }
            ],
        }
    )
    ai = _FakeAI(ai_response)
    service = case_copilot.CaseCopilotService(
        env="dev", model="gpt-test", repository=repo, ai_client=ai
    )

    result = service.summarize(UUID("11111111-1111-1111-1111-111111111111"))

    assert result.summary == "Case looks strong"
    assert result.recommended_actions == ["Call plaintiff"]
    assert result.risk.value == 42
    assert result.draft_documents[0].title == "Demand letter"
    assert repo.logged and repo.logged[0]["metadata"]["status"] == "ok"
    assert repo.logged[0]["metadata"]["recommended_actions"] == ["Call plaintiff"]
    assert repo.logged[0]["metadata"]["case_copilot_version"] == "v2"


def test_case_copilot_parses_string_blocks_and_defaults_documents() -> None:
    repo = _FakeRepo(_sample_context())
    ai = _FakeAI(
        dedent(
            """
            ```json
            {
                "summary": "Minimal context",
                "enforcement_suggestions": "1. Verify asset search\\n2. Schedule levy",
                "draft_documents": [],
                "risk": {"value": "55", "label": "Medium", "drivers": "Unknown employer"},
                "timeline_analysis": [],
                "contact_strategy": "Call weekly"
            }
            ```
            """
        ).strip()
    )
    service = case_copilot.CaseCopilotService(env="dev", repository=repo, ai_client=ai)

    result = service.summarize("11111111-1111-1111-1111-111111111111")

    assert result.recommended_actions == ["1. Verify asset search", "2. Schedule levy"]
    assert result.draft_documents  # fallback generated
    assert result.risk.value == 55


def test_case_copilot_rejects_json_with_stray_fence() -> None:
    repo = _FakeRepo(_sample_context())
    ai = _FakeAI(
        dedent(
            """
            ```json
            {
                "summary": "Bad fence",
                "enforcement_suggestions": ["Call"],
                "draft_documents": []
            }
            ```
            ```
            """
        ).strip()
    )
    service = case_copilot.CaseCopilotService(env="dev", repository=repo, ai_client=ai)

    with pytest.raises(RuntimeError):
        service.summarize("11111111-1111-1111-1111-111111111111")


def test_case_copilot_logs_extra_metadata() -> None:
    repo = _FakeRepo(_sample_context())
    ai_response = json.dumps(
        {
            "summary": "Case ok",
            "enforcement_suggestions": ["Call"],
            "draft_documents": [],
            "risk": {"value": 10, "label": "Low", "drivers": ["Assets located"]},
            "timeline_analysis": [],
            "contact_strategy": [],
        }
    )
    ai = _FakeAI(ai_response)
    service = case_copilot.CaseCopilotService(env="dev", repository=repo, ai_client=ai)

    service.summarize(
        "11111111-1111-1111-1111-111111111111",
        extra_metadata={"requested_by": "dashboard", "source": "worker"},
    )

    metadata = repo.logged[0]["metadata"]
    assert metadata["requested_by"] == "dashboard"
    assert metadata["source"] == "worker"


def test_case_copilot_logs_errors_on_invalid_json() -> None:
    repo = _FakeRepo(_sample_context())
    ai = _FakeAI("not-json")
    service = case_copilot.CaseCopilotService(env="dev", repository=repo, ai_client=ai)

    with pytest.raises(RuntimeError):
        service.summarize("11111111-1111-1111-1111-111111111111")

    assert repo.logged[0]["metadata"]["status"] == "error"
