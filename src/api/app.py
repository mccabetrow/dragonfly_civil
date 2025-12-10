from __future__ import annotations

import logging
import secrets
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, EmailStr, Field, model_validator

from src.settings import get_settings
from src.supabase_client import create_supabase_client, get_supabase_env
from tools.demo_insert_case import upsert_case

LOGGER = logging.getLogger(__name__)
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
ENV_HEADER = "X-Dragonfly-Env"

app = FastAPI(
    title="Dragonfly Orchestration API",
    version="0.1.0",
    description="Thin API layer for n8n orchestration workflows.",
)


def _normalize_env(value: Optional[str]) -> str:
    if not value:
        return get_supabase_env()
    lowered = value.strip().lower()
    if lowered in {"prod", "production"}:
        return "prod"
    if lowered in {"dev", "demo", "development"}:
        return "dev"
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST, detail="Unsupported Supabase environment override"
    )


@lru_cache(maxsize=2)
def _get_supabase_client_cached(env: str) -> Any:
    return create_supabase_client(env)


async def require_api_key(api_key: Optional[str] = Depends(API_KEY_HEADER)) -> None:
    settings = get_settings()
    expected = (settings.N8N_API_KEY or "").strip()
    if not expected:
        LOGGER.error("N8N_API_KEY is not configured; refusing authenticated request")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="API key not configured")
    if not api_key or not secrets.compare_digest(api_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


class CaseParty(BaseModel):
    name: str = Field(..., min_length=1)
    is_business: Optional[bool] = None
    emails: List[EmailStr] = Field(default_factory=list)
    phones: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_supabase(self, role: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "role": role,
            "name_full": self.name.strip(),
        }
        if self.is_business is not None:
            payload["is_business"] = self.is_business
        if self.emails:
            payload["emails"] = self.emails
        if self.phones:
            payload["phones"] = [phone.strip() for phone in self.phones if phone and phone.strip()]
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


class CaseUpsertRequest(BaseModel):
    case_number: str = Field(..., min_length=1)
    source: str = Field(default="n8n_orchestrator")
    title: Optional[str] = None
    court: Optional[str] = None
    judgment_amount_cents: Optional[int] = Field(default=None, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    plaintiff: CaseParty
    defendants: List[CaseParty]

    @model_validator(mode="after")
    def validate_defendants(self) -> "CaseUpsertRequest":
        if not self.defendants:
            raise ValueError("At least one defendant is required")
        return self

    def to_supabase_payload(self) -> Dict[str, Any]:
        amount_cents = self.judgment_amount_cents
        amount_dollars = round(amount_cents / 100.0, 2) if isinstance(amount_cents, int) else None
        case_section: Dict[str, Any] = {
            "case_number": self.case_number.strip().upper(),
            "source": self.source,
            "title": self.title,
            "court": self.court,
            "judgment_amount_cents": amount_cents,
            "amount_awarded": amount_dollars,
        }
        if self.metadata:
            case_section["metadata"] = self.metadata
        compact_case = {key: value for key, value in case_section.items() if value is not None}
        entities = [self.plaintiff.to_supabase("plaintiff")] + [
            party.to_supabase("defendant") for party in self.defendants
        ]
        return {"case": compact_case, "entities": entities}


class CaseUpsertResponse(BaseModel):
    case_id: str
    case_number: str
    entity_ids: List[str] = Field(default_factory=list)
    supabase_env: str


class OutreachEventRequest(BaseModel):
    case_number: str = Field(..., min_length=1)
    channel: str = Field(default="email")
    template: str = Field(default="generic_notification")
    status: str = Field(default="sent")
    recipient: Optional[str] = None
    sent_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OutreachEventResponse(BaseModel):
    id: int
    status: str


class InboundWebhookRequest(BaseModel):
    case_number: str = Field(..., min_length=1)
    channel: str = Field(default="sms")
    message: str = Field(..., min_length=1)
    sender: Optional[str] = None
    received_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    next_case_status: Optional[str] = None


class InboundWebhookResponse(BaseModel):
    id: int
    case_status_updated: bool


class TaskCompleteRequest(BaseModel):
    task_id: str = Field(..., min_length=1)
    status: str = Field(default="completed")
    case_number: Optional[str] = None
    notes: Optional[str] = None


class TaskCompleteResponse(BaseModel):
    task_id: str
    status: str


def _first_dict(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                return item
    return {}


def _compact_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            compact[key] = value
        elif value is None:
            continue
        else:
            compact[key] = value
    return compact


@app.post("/api/cases", response_model=CaseUpsertResponse, status_code=status.HTTP_200_OK)
async def upsert_case_via_api(
    body: CaseUpsertRequest,
    _: None = Depends(require_api_key),
    env_override: Optional[str] = Header(default=None, alias=ENV_HEADER),
) -> CaseUpsertResponse:
    target_env = _normalize_env(env_override)
    try:
        supabase_client = _get_supabase_client_cached(target_env)
    except Exception as exc:  # pragma: no cover
        LOGGER.exception("Failed to init Supabase client")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Supabase client unavailable"
        ) from exc

    try:
        payload = body.to_supabase_payload()
        result = upsert_case(
            supabase_client,
            payload,
            supabase_env=target_env,
            case_number_hint=body.case_number,
            amount_cents=body.judgment_amount_cents,
        )
    except Exception as exc:
        LOGGER.exception("Supabase upsert failed for case %s", body.case_number)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Failed to persist case") from exc

    return CaseUpsertResponse(
        case_id=str(result.get("case_id")),
        case_number=str(result.get("case_number")),
        entity_ids=[str(entity) for entity in result.get("entity_ids", []) if entity],
        supabase_env=target_env,
    )


@app.post(
    "/api/outreach-events",
    response_model=OutreachEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_outreach_event(
    body: OutreachEventRequest,
    _: None = Depends(require_api_key),
    env_override: Optional[str] = Header(default=None, alias=ENV_HEADER),
) -> OutreachEventResponse:
    target_env = _normalize_env(env_override)
    supabase_client = _get_supabase_client_cached(target_env)

    metadata = {
        "recipient": body.recipient,
        "sent_at": body.sent_at.isoformat() if body.sent_at else None,
        **body.metadata,
    }
    clean_metadata = {k: v for k, v in _compact_metadata(metadata).items() if v is not None}

    row: Dict[str, Any] = {
        "case_number": body.case_number.strip().upper(),
        "channel": body.channel,
        "template": body.template,
        "status": body.status,
    }
    if clean_metadata:
        row["metadata"] = clean_metadata

    try:
        response = supabase_client.table("outreach_log").insert(row).execute()
    except Exception as exc:
        LOGGER.exception("Failed to log outreach event for case %s", body.case_number)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Failed to persist outreach event"
        ) from exc

    record = _first_dict(getattr(response, "data", None))
    if not record.get("id"):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Supabase returned no outreach id")

    return OutreachEventResponse(id=int(record["id"]), status=row["status"])


@app.post(
    "/api/webhooks/inbound",
    response_model=InboundWebhookResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_inbound_webhook(
    body: InboundWebhookRequest,
    _: None = Depends(require_api_key),
    env_override: Optional[str] = Header(default=None, alias=ENV_HEADER),
) -> InboundWebhookResponse:
    target_env = _normalize_env(env_override)
    supabase_client = _get_supabase_client_cached(target_env)

    metadata = {
        "sender": body.sender,
        "message": body.message,
        "received_at": body.received_at.isoformat() if body.received_at else None,
        **body.metadata,
    }
    clean_metadata = {k: v for k, v in _compact_metadata(metadata).items() if v is not None}

    row: Dict[str, Any] = {
        "case_number": body.case_number.strip().upper(),
        "channel": f"{body.channel}_inbound",
        "template": "inbound_signal",
        "status": "received",
    }
    if clean_metadata:
        row["metadata"] = clean_metadata

    try:
        response = supabase_client.table("outreach_log").insert(row).execute()
    except Exception as exc:
        LOGGER.exception("Failed to record inbound webhook for case %s", body.case_number)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Failed to persist inbound webhook"
        ) from exc

    record = _first_dict(getattr(response, "data", None))
    if not record.get("id"):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Supabase returned no inbound id")

    status_updated = False
    if body.next_case_status:
        try:
            supabase_client.schema("judgments").table("cases").update(
                {"case_status": body.next_case_status}
            ).eq("case_number", body.case_number.strip().upper()).execute()
            status_updated = True
        except Exception:
            LOGGER.exception("Failed to update case status for %s", body.case_number)
            status_updated = False

    return InboundWebhookResponse(id=int(record["id"]), case_status_updated=status_updated)


@app.post(
    "/api/tasks/complete",
    response_model=TaskCompleteResponse,
    status_code=status.HTTP_200_OK,
)
async def complete_task(
    body: TaskCompleteRequest,
    _: None = Depends(require_api_key),
    env_override: Optional[str] = Header(default=None, alias=ENV_HEADER),
) -> TaskCompleteResponse:
    target_env = _normalize_env(env_override)
    supabase_client = _get_supabase_client_cached(target_env)

    try:
        update_response = (
            supabase_client.schema("enforcement")
            .table("tasks")
            .update({"status": body.status})
            .eq("task_id", body.task_id)
            .execute()
        )
    except Exception as exc:
        LOGGER.exception("Failed to update task %s", body.task_id)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Failed to update task") from exc

    record = _first_dict(getattr(update_response, "data", None))
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")

    if body.notes:
        notes_metadata = {
            "case_number": body.case_number,
            "task_id": body.task_id,
            "notes": body.notes,
        }
        clean_notes = {k: v for k, v in notes_metadata.items() if v is not None}
        try:
            supabase_client.table("outreach_log").insert(
                {
                    "case_number": (body.case_number or record.get("case_number") or "")
                    .strip()
                    .upper(),
                    "channel": "task",
                    "template": "completion_note",
                    "status": "note",
                    "metadata": clean_notes or None,
                }
            ).execute()
        except Exception:
            LOGGER.exception("Failed to log task completion note for %s", body.task_id)

    return TaskCompleteResponse(
        task_id=str(record.get("task_id", body.task_id)),
        status=str(record.get("status", body.status)),
    )


@app.get("/healthz", status_code=status.HTTP_200_OK)
async def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


# Include routers
from src.api.enforcement import router as enforcement_router
from src.api.ops_digest import router as ops_digest_router

app.include_router(enforcement_router)
app.include_router(ops_digest_router)
