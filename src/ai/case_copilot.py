from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence, cast
from uuid import UUID

import psycopg
from openai import OpenAI
from psycopg.rows import RowFactory, dict_row
from psycopg.types.json import Jsonb

from src.supabase_client import get_supabase_db_url, get_supabase_env


logger = logging.getLogger(__name__)

DEFAULT_CASE_COPILOT_MODEL = "gpt-4.1-mini"
SYSTEM_PROMPT = (
    "You are Dragonfly Civil's Case Copilot v2. You review structured enforcement case "
    "context (judgments, plaintiffs, enforcement timeline, tasks, contacts) and produce an "
    "actionable plan for operators. Always respond with valid JSON that matches the schema "
    "described in the user instructions. Avoid hallucinating information not provided in the "
    "context. Provide pragmatic enforcement tactics, concise document outlines, and an "
    "explicit risk score between 0 and 100."
)
RESPONSE_SCHEMA = (
    "Respond with JSON containing the keys: summary (string), "
    "enforcement_suggestions (array of objects with title, rationale, next_step), "
    "draft_documents (array of objects with title, objective, key_points[]), "
    "risk (object with value [0-100], label, drivers[]), "
    "timeline_analysis (array of objects with observation, impact, urgency), and "
    "contact_strategy (array of objects with channel, action, cadence, notes)."
)


@dataclass
class EnforcementSuggestion:
    title: str
    rationale: str | None
    next_step: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "rationale": self.rationale,
            "next_step": self.next_step,
        }


@dataclass
class DraftDocumentPlan:
    title: str
    objective: str | None
    key_points: list[str]

    def to_payload(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "objective": self.objective,
            "key_points": list(self.key_points),
        }


@dataclass
class TimelineInsight:
    observation: str
    impact: str | None
    urgency: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "observation": self.observation,
            "impact": self.impact,
            "urgency": self.urgency,
        }


@dataclass
class ContactStrategy:
    channel: str
    action: str
    cadence: str | None
    notes: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "action": self.action,
            "cadence": self.cadence,
            "notes": self.notes,
        }


@dataclass
class RiskProfile:
    value: int
    label: str
    drivers: list[str]

    def to_payload(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "label": self.label,
            "drivers": list(self.drivers),
        }


@dataclass
class CaseCopilotResult:
    summary: str
    enforcement_suggestions: list[EnforcementSuggestion]
    draft_documents: list[DraftDocumentPlan]
    risk: RiskProfile
    timeline_analysis: list[TimelineInsight]
    contact_strategy: list[ContactStrategy]
    model: str
    raw_response: str

    @property
    def recommended_actions(self) -> list[str]:
        return [
            suggestion.title
            for suggestion in self.enforcement_suggestions
            if suggestion.title
        ]

    def to_log_metadata(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "enforcement_suggestions": [
                s.to_payload() for s in self.enforcement_suggestions
            ],
            "draft_documents": [doc.to_payload() for doc in self.draft_documents],
            "risk": self.risk.to_payload(),
            "timeline_analysis": [ti.to_payload() for ti in self.timeline_analysis],
            "contact_strategy": [cs.to_payload() for cs in self.contact_strategy],
            "recommended_actions": self.recommended_actions,
            "model": self.model,
            "raw_response": self.raw_response,
        }


@dataclass
class CopilotCaseContext:
    case_id: str
    payload: Mapping[str, Any]


class CaseContextRepository(Protocol):
    def fetch_context(self, case_id: str) -> CopilotCaseContext: ...

    def log_invocation(
        self,
        *,
        case_id: str,
        model: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None: ...


class AIClient(Protocol):
    def complete(self, *, system_prompt: str, user_prompt: str, model: str) -> str: ...


class OpenAIChatClient:
    def __init__(self, *, api_key: str | None = None, timeout: float = 30.0) -> None:
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is required to run Case Copilot.")
        self._client = OpenAI(api_key=key, timeout=timeout)

    def complete(self, *, system_prompt: str, user_prompt: str, model: str) -> str:
        response = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.25,
            max_tokens=900,
        )
        content = response.choices[0].message.content or ""
        return content.strip()


class DatabaseCaseContextRepository:
    def __init__(self, db_url: str) -> None:
        self._db_url = db_url

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(
            self._db_url,
            connect_timeout=10,
            row_factory=cast(RowFactory[Any], dict_row),
        )

    def fetch_context(self, case_id: str) -> CopilotCaseContext:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT case_id::text AS case_id, context FROM public.copilot_case_context(%s)",
                (case_id,),
            )
            row = cur.fetchone()
        if not row:
            raise ValueError(f"Case context not found for {case_id}")
        context_payload = row["context"]
        if not isinstance(context_payload, Mapping):
            raise RuntimeError("copilot_case_context returned unexpected payload")
        return CopilotCaseContext(case_id=row["case_id"], payload=context_payload)

    def log_invocation(
        self,
        *,
        case_id: str,
        model: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        with psycopg.connect(
            self._db_url, autocommit=True
        ) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.case_copilot_logs (case_id, model, metadata)
                VALUES (%s, %s, %s)
                """,
                (case_id, model, Jsonb(dict(metadata or {}))),
            )


class CaseCopilotService:
    def __init__(
        self,
        *,
        env: str | None = None,
        model: str | None = None,
        repository: CaseContextRepository | None = None,
        ai_client: AIClient | None = None,
    ) -> None:
        self._env = env or get_supabase_env()
        self._model = model or DEFAULT_CASE_COPILOT_MODEL
        if repository is None:
            db_url = get_supabase_db_url(self._env)
            repository = DatabaseCaseContextRepository(db_url)
        self._repository = repository
        self._ai_client = ai_client or OpenAIChatClient()

    def summarize(
        self,
        case_id: UUID | str,
        *,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> CaseCopilotResult:
        case_id_str = str(case_id)
        context = self._repository.fetch_context(case_id_str)
        context_json = json.dumps(
            context.payload, indent=2, ensure_ascii=True, sort_keys=True
        )
        user_prompt = _build_user_prompt(context_json)

        metadata: dict[str, Any] = {
            "env": self._env,
            "case_id": case_id_str,
            "case_copilot_version": "v2",
        }
        if extra_metadata:
            for key, value in extra_metadata.items():
                if value is None:
                    continue
                metadata[key] = value

        start = datetime.now(timezone.utc)
        status_meta = dict(metadata)
        try:
            response_text = self._ai_client.complete(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=self._model,
            )
            duration_ms = _duration_ms(start)
            result = _parse_response(response_text, self._model)
            status_meta.update(result.to_log_metadata())
            status_meta["duration_ms"] = duration_ms
            status_meta["status"] = "ok"
            self._repository.log_invocation(
                case_id=case_id_str,
                model=self._model,
                metadata=status_meta,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            status_meta["status"] = "error"
            status_meta["duration_ms"] = _duration_ms(start)
            status_meta["error"] = str(exc)
            try:
                self._repository.log_invocation(
                    case_id=case_id_str,
                    model=self._model,
                    metadata=status_meta,
                )
            except Exception:  # pragma: no cover
                logger.exception(
                    "Failed to log Case Copilot error for case %s", case_id_str
                )
            raise


def run_case_copilot(
    case_id: UUID | str,
    *,
    env: str | None = None,
    model: str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
    repository: CaseContextRepository | None = None,
    ai_client: AIClient | None = None,
) -> CaseCopilotResult:
    service = CaseCopilotService(
        env=env,
        model=model,
        repository=repository,
        ai_client=ai_client,
    )
    return service.summarize(case_id, extra_metadata=extra_metadata)


def _build_user_prompt(context_json: str) -> str:
    return (
        "You will be given structured enforcement data. "
        + RESPONSE_SCHEMA
        + " Be specific, tactical, and stay within civil judgment enforcement scope.\nContext:\n"
        + context_json
    )


def _parse_response(response_text: str, model: str) -> CaseCopilotResult:
    cleaned = _strip_code_fence(response_text)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:  # pragma: no cover
        raise RuntimeError("AI response was not valid JSON") from exc

    summary = _require_str(payload.get("summary"), "summary")
    suggestions = _coerce_suggestions(payload.get("enforcement_suggestions"))
    drafts = _coerce_draft_documents(payload.get("draft_documents"))
    risk = _coerce_risk(payload.get("risk"))
    timeline = _coerce_timeline(payload.get("timeline_analysis"))
    contact_strategy = _coerce_contact_strategy(payload.get("contact_strategy"))

    return CaseCopilotResult(
        summary=summary,
        enforcement_suggestions=suggestions,
        draft_documents=drafts,
        risk=risk,
        timeline_analysis=timeline,
        contact_strategy=contact_strategy,
        model=model,
        raw_response=response_text,
    )


def _coerce_suggestions(value: Any) -> list[EnforcementSuggestion]:
    results: list[EnforcementSuggestion] = []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            if isinstance(item, Mapping):
                title = str(item.get("title", "")).strip()
                rationale = _optional_str(item.get("rationale"))
                next_step = _optional_str(item.get("next_step"))
                if title:
                    results.append(
                        EnforcementSuggestion(
                            title=title, rationale=rationale, next_step=next_step
                        )
                    )
            elif isinstance(item, str) and item.strip():
                results.append(
                    EnforcementSuggestion(
                        title=item.strip(), rationale=None, next_step=None
                    )
                )
    elif isinstance(value, str) and value.strip():
        for line in value.splitlines():
            line = line.strip()
            if line:
                results.append(
                    EnforcementSuggestion(title=line, rationale=None, next_step=None)
                )
    if not results:
        raise RuntimeError("AI response missing enforcement_suggestions")
    return results


def _coerce_draft_documents(value: Any) -> list[DraftDocumentPlan]:
    results: list[DraftDocumentPlan] = []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            objective = _optional_str(item.get("objective"))
            key_points = _coerce_string_list(item.get("key_points"))
            results.append(
                DraftDocumentPlan(
                    title=title, objective=objective, key_points=key_points
                )
            )
    if not results:
        results.append(
            DraftDocumentPlan(
                title="Demand letter refresh",
                objective="Outline recent enforcement steps and payment expectations.",
                key_points=[
                    "Summarize judgment",
                    "Detail enforcement steps",
                    "State remittance wiring",
                ],
            )
        )
    return results


def _coerce_risk(value: Any) -> RiskProfile:
    if not isinstance(value, Mapping):
        raise RuntimeError("AI response missing risk object")
    raw_value = value.get("value")
    if raw_value is None:
        raise RuntimeError("AI response missing numeric risk value")
    try:
        int_value = int(float(raw_value))
    except (TypeError, ValueError):
        raise RuntimeError("AI response missing numeric risk value") from None
    int_value = min(max(int_value, 0), 100)
    label = _require_str(value.get("label"), "risk.label")
    drivers = _coerce_string_list(value.get("drivers"))
    if not drivers:
        drivers = ["No drivers supplied"]
    return RiskProfile(value=int_value, label=label, drivers=drivers)


def _coerce_timeline(value: Any) -> list[TimelineInsight]:
    insights: list[TimelineInsight] = []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            observation = _optional_str(item.get("observation"))
            if not observation:
                continue
            impact = _optional_str(item.get("impact"))
            urgency = _optional_str(item.get("urgency"))
            insights.append(
                TimelineInsight(observation=observation, impact=impact, urgency=urgency)
            )
    return insights


def _coerce_contact_strategy(value: Any) -> list[ContactStrategy]:
    plays: list[ContactStrategy] = []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            channel = _optional_str(item.get("channel")) or "unspecified"
            action = _optional_str(item.get("action"))
            if not action:
                continue
            cadence = _optional_str(item.get("cadence"))
            notes = _optional_str(item.get("notes"))
            plays.append(
                ContactStrategy(
                    channel=channel, action=action, cadence=cadence, notes=notes
                )
            )
    return plays


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value).strip() or None


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result = [str(item).strip() for item in value if str(item).strip()]
        return result
    if isinstance(value, str):
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        return lines
    return []


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"AI response missing {field_name}")
    stripped = value.strip()
    if not stripped:
        raise RuntimeError(f"AI response provided empty {field_name}")
    return stripped


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    def _is_fence(line: str) -> bool:
        return line.strip().startswith("```")

    lines = stripped.splitlines()
    if lines and _is_fence(lines[0]):
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and _is_fence(lines[-1]):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _duration_ms(start: datetime) -> int:
    elapsed = datetime.now(timezone.utc) - start
    return int(elapsed.total_seconds() * 1000)
