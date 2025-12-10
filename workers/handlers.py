from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.supabase_client import create_supabase_client

logger = logging.getLogger(__name__)

_SUPABASE_CLIENT = None


def is_demo_env() -> bool:
    """
    Returns True when running a demo / sandbox environment.

    Tests monkeypatch this function to simulate demo behavior.
    """
    from backend.config import get_settings

    settings = get_settings()
    # Demo env is indicated by environment == "demo"
    return settings.environment.lower() == "demo"


def _get_supabase_client():
    global _SUPABASE_CLIENT
    if _SUPABASE_CLIENT is None:
        _SUPABASE_CLIENT = create_supabase_client()
    return _SUPABASE_CLIENT


def extract_case_number(job: Dict[str, Any]) -> Optional[str]:
    payload = job.get("payload") if isinstance(job, dict) else None
    if isinstance(payload, dict):
        message_payload = payload.get("payload")
        if isinstance(message_payload, dict):
            candidate = message_payload.get("case_number")
            if candidate:
                return str(candidate).strip()
        candidate = payload.get("case_number")
        if candidate:
            return str(candidate).strip()
    candidate = job.get("case_number") if isinstance(job, dict) else None
    if candidate:
        return str(candidate).strip()
    return None


def extract_template_code(job: Dict[str, Any]) -> Optional[str]:
    def _from_mapping(mapping: Dict[str, Any] | None) -> Optional[str]:
        if not isinstance(mapping, dict):
            return None
        candidate = mapping.get("template_code")
        if candidate:
            return str(candidate).strip()
        return None

    payload = job.get("payload") if isinstance(job, dict) else None
    nested = payload.get("payload") if isinstance(payload, dict) else None

    template_code = _from_mapping(nested) or _from_mapping(payload)
    if template_code:
        return template_code

    direct = job.get("template_code") if isinstance(job, dict) else None
    if direct:
        return str(direct).strip()

    return None


def update_case_status(case_number: str, status: str) -> None:
    client = _get_supabase_client()
    client.table("judgments").update({"status": status}).eq("case_number", case_number).execute()


async def handle_enrich(job: Dict[str, Any]) -> bool:
    """Process an enrich job by flagging the case for enrichment."""
    try:
        case_number = extract_case_number(job)
        if not case_number:
            raise ValueError("Missing case_number in enrich job payload")

        update_case_status(case_number, "enrich_pending")
        logger.info("Enrich job accepted for case %s", case_number)
        return True
    except Exception:
        logger.exception("handle_enrich failed for job %s", job.get("msg_id"))
        raise


def log_outreach_stub(case_number: str, metadata: Optional[Dict[str, Any]]) -> None:
    client = _get_supabase_client()
    entry: Dict[str, Any] = {
        "case_number": case_number,
        "channel": "stub",
        "template": "welcome_v0",
        "status": "pending_provider",
    }
    if metadata:
        entry["metadata"] = metadata
    client.table("outreach_log").insert(entry).execute()


async def handle_outreach(job: Dict[str, Any]) -> bool:
    try:
        payload = job.get("payload") if isinstance(job, dict) else None
        message_payload = payload.get("payload") if isinstance(payload, dict) else None
        if not isinstance(message_payload, dict):
            raise ValueError("Missing nested payload for outreach job")

        case_number_raw = message_payload.get("case_number")
        if not case_number_raw:
            raise ValueError("Missing case_number in outreach job payload")

        case_number = str(case_number_raw).strip()

        log_outreach_stub(case_number, message_payload)
        update_case_status(case_number, "outreach_stubbed")
        logger.info("Outreach stub recorded for case %s", case_number)
        return True
    except Exception:
        logger.exception("handle_outreach failed for job %s", job.get("msg_id"))
        raise


async def handle_enforce(job: Dict[str, Any]) -> bool:
    try:
        case_number = extract_case_number(job)
        if not case_number:
            raise ValueError("Missing case_number in enforce job payload")

        template_code = extract_template_code(job) or "INFO_SUBPOENA_FLOW"

        client = _get_supabase_client()
        response = client.rpc(
            "spawn_enforcement_flow",
            {
                "case_number": case_number,
                "template_code": template_code,
            },
        ).execute()

        created_ids = getattr(response, "data", None)
        if isinstance(created_ids, dict):
            created_ids = created_ids.get("spawn_enforcement_flow")
        if created_ids is None:
            created_ids = []
        elif isinstance(created_ids, (str, bytes)):
            created_ids = [created_ids]

        task_count = len(created_ids) if isinstance(created_ids, (list, tuple)) else 0
        update_case_status(case_number, "enforcement_open")
        logger.info(
            "Enforcement flow %s spawned for case %s (%s tasks)",
            template_code,
            case_number,
            task_count,
        )
        return True
    except Exception:
        logger.exception("handle_enforce failed for job %s", job.get("msg_id"))
        raise
