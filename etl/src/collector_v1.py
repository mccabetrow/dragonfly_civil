import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
from dotenv import load_dotenv

from .models import CaseIn

load_dotenv()
BASE = os.environ["SUPABASE_URL"].rstrip("/")
ANON = os.environ["SUPABASE_ANON_KEY"]
SERVICE_ROLE = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

logger = logging.getLogger(__name__)

INSERT_CASE_URL = f"{BASE}/rest/v1/rpc/insert_case"
INSERT_CASE_UPSERT_URL = f"{BASE}/rest/v1/rpc/insert_or_get_case"
INSERT_ENTITY_URL = f"{BASE}/rest/v1/rpc/insert_entity"
INSERT_COMPOSITE_URL = f"{BASE}/rest/v1/rpc/insert_case_with_entities"
INSERT_IDEMPOTENT_COMPOSITE_URL = f"{BASE}/rest/v1/rpc/insert_or_get_case_with_entities"
QUEUE_JOB_URL = f"{BASE}/rest/v1/rpc/queue_job"
CASES_VIEW_URL = f"{BASE}/rest/v1/v_cases_with_org"
ENTITIES_VIEW_URL = f"{BASE}/rest/v1/v_entities_simple"

RECENCY_WINDOW_SECONDS = 5


def _headers() -> Dict[str, str]:
    return {
        "apikey": ANON,
        "Authorization": f"Bearer {ANON}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": "return=representation",
    }


def _service_headers() -> Dict[str, str]:
    return {
        "apikey": SERVICE_ROLE,
        "Authorization": f"Bearer {SERVICE_ROLE}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _extract_value(data: Any, key: str) -> str:
    if isinstance(data, dict):
        value = data.get(key) or next(iter(data.values()), None)
        if value is None:
            raise ValueError(f"RPC response missing {key} value")
        return str(value)
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            value = first.get(key) or next(iter(first.values()), None)
            if value is None:
                raise ValueError(f"RPC response missing {key} value in list payload")
            return str(value)
        return str(first)
    if isinstance(data, str):
        return data
    raise ValueError(f"Unexpected response payload: {data!r}")


async def _post_json(
    url: str,
    json_payload: Dict[str, Any],
    *,
    headers: Dict[str, str] | None = None,
) -> Any:
    request_headers = headers or _headers()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, headers=request_headers, json=json_payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - smoke helper
            raise RuntimeError(
                f"Supabase RPC {url.rsplit('/', 1)[-1]} failed: {exc.response.text}"
            ) from exc
        return response.json()


async def _queue_job(kind: str, payload: Dict[str, Any], idempotency_key: str) -> int:
    envelope = {
        "kind": kind,
        "payload": payload,
        "idempotency_key": idempotency_key,
    }
    data = await _post_json(QUEUE_JOB_URL, {"payload": envelope}, headers=_service_headers())
    if isinstance(data, dict):
        msg_id = data.get("queue_job") or next(iter(data.values()), None)
    else:
        msg_id = data
    if msg_id is None:
        raise RuntimeError("Queue job RPC returned no message id")
    return int(msg_id)


async def _enqueue_enrich_job(
    case_payload: Dict[str, Any],
    case_id: str | None,
) -> None:
    case_number = case_payload.get("case_number")
    if not case_number:
        return
    source = (case_payload.get("source") or "collector").lower()
    idempotency_key = f"{source}:{case_number}"
    try:
        job_payload: Dict[str, Any] = {"case_number": case_number}
        if case_id:
            job_payload["case_id"] = case_id
        msg_id = await _queue_job("enrich", job_payload, idempotency_key)
        logger.info("Queued enrich job %s for case %s", msg_id, case_number)
    except Exception as exc:
        logger.warning("Failed to enqueue enrich job for %s: %s", case_number, exc)


async def _fetch_case_record(case_number: str, source: str) -> Dict[str, Any] | None:
    params = {
        "case_number": f"eq.{case_number}",
        "source": f"eq.{source}",
        "order": "created_at.desc",
        "limit": "1",
        "select": "case_id,created_at",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(CASES_VIEW_URL, headers=_headers(), params=params)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - smoke helper
            raise RuntimeError(f"Supabase view lookup failed: {exc.response.text}") from exc
        data = response.json()

    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return first
    return None


async def _fetch_entity_record(case_id: str, role: str, name_full: str) -> Dict[str, Any] | None:
    params = {
        "case_id": f"eq.{case_id}",
        "role": f"eq.{role}",
        "name_full": f"eq.{name_full}",
        "order": "created_at.desc",
        "limit": "1",
        "select": "entity_id,created_at",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(ENTITIES_VIEW_URL, headers=_headers(), params=params)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - smoke helper
            raise RuntimeError(f"Supabase entity view lookup failed: {exc.response.text}") from exc
        data = response.json()

    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return first
    return None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:  # pragma: no cover - defensive
        return None


async def _determine_case_status(case_payload: Dict[str, Any]) -> str:
    case_number = case_payload.get("case_number")
    source = case_payload.get("source", "unknown")
    if not case_number or not source:
        return "inserted"

    record = await _fetch_case_record(case_number, source)
    if not record:
        return "inserted"

    created_at = _parse_timestamp(record.get("created_at"))
    if created_at and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    if created_at:
        reference_time = datetime.now(timezone.utc)
        delta = abs((reference_time - created_at).total_seconds())
        if delta <= RECENCY_WINDOW_SECONDS:
            return "inserted"
    return "existing"


async def _determine_entity_status(case_id: str, entity_payload: Dict[str, Any]) -> str:
    role = entity_payload.get("role")
    name_full = entity_payload.get("name_full")
    if not role or not name_full:
        return "inserted"

    record = await _fetch_entity_record(case_id, role, name_full)
    if not record:
        return "inserted"

    created_at = _parse_timestamp(record.get("created_at"))
    if created_at and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    if created_at:
        reference_time = datetime.now(timezone.utc)
        delta = abs((reference_time - created_at).total_seconds())
        if delta <= RECENCY_WINDOW_SECONDS:
            return "inserted"
    return "existing"


async def insert_case(case: CaseIn, force_insert: bool = False) -> tuple[str, str]:
    payload_json = case.model_dump(mode="json")
    payload = {"payload": payload_json}
    rpc_url = INSERT_CASE_URL if force_insert else INSERT_CASE_UPSERT_URL
    key_name = "insert_case" if force_insert else "insert_or_get_case"

    data = await _post_json(rpc_url, payload)
    case_id = _extract_value(data, key_name)

    status = "inserted"
    if not force_insert:
        status = await _determine_case_status(payload_json)

    await _enqueue_enrich_job(payload_json, case_id)

    return case_id, status


async def insert_entity(payload: Dict[str, Any]) -> str:
    data = await _post_json(INSERT_ENTITY_URL, {"payload": payload})
    return _extract_value(data, "insert_entity")


async def insert_case_with_entities(
    payload: Dict[str, Any], *, idempotent: bool = False
) -> Dict[str, Any]:
    rpc_url = INSERT_IDEMPOTENT_COMPOSITE_URL if idempotent else INSERT_COMPOSITE_URL
    data = await _post_json(rpc_url, {"payload": payload})
    case_payload = payload.get("case") if isinstance(payload, dict) else None
    case_id: str | None = None

    if isinstance(data, dict):
        try:
            case_id = _extract_value(data, "case_id")
        except ValueError:
            case_id = None
        if isinstance(case_payload, dict):
            await _enqueue_enrich_job(case_payload, case_id)
        return data
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            try:
                case_id = _extract_value(first, "case_id")
            except ValueError:
                case_id = None
            if isinstance(case_payload, dict):
                await _enqueue_enrich_job(case_payload, case_id)
            return first
    raise ValueError(f"Unexpected composite response payload: {data!r}")


def make_smoke_case(case_number_override: str | None = None) -> CaseIn:
    if case_number_override:
        candidate = case_number_override.strip().upper()
        case_number = candidate if candidate.startswith("SMOKE-") else f"SMOKE-{candidate}"
    else:
        case_number = f"SMOKE-{uuid.uuid4().hex[:6].upper()}"

    return CaseIn(
        case_number=case_number,
        source="smoke",
        title="Doe v. Roe",
        court="NYC Civil Court",
        amount_awarded=1234.56,
    )


def make_demo_entities(case_id: str) -> List[Dict[str, Any]]:
    return [
        {
            "case_id": case_id,
            "role": "plaintiff",
            "name_full": "Jane Doe",
            "emails": ["jane@example.com"],
            "phones": ["+15555550123"],
        },
        {
            "case_id": case_id,
            "role": "defendant",
            "name_full": "John Roe",
            "phones": ["+15555550999"],
        },
    ]


async def do_composite(case_number_override: str | None, use_idempotent_composite: bool) -> None:
    case = make_smoke_case(case_number_override)
    case_payload = case.model_dump(mode="json")
    entities_payload = [
        {
            "role": "plaintiff",
            "name_full": "Jane Doe",
            "emails": ["jane@example.com"],
        },
        {
            "role": "defendant",
            "name_full": "John Roe",
            "phones": ["+15555550999"],
        },
    ]
    payload = {"case": case_payload, "entities": entities_payload}
    result = await insert_case_with_entities(payload, idempotent=use_idempotent_composite)

    case_id = _extract_value(result, "case_id")
    case_status = await _determine_case_status(case_payload)
    print(f"{case_status} case_id:", case_id)

    entity_ids = result.get("entity_ids") or []
    for entity_payload, entity_id in zip(entities_payload, entity_ids):
        status = await _determine_entity_status(case_id, entity_payload)
        print(f"{status} entity_id:", entity_id)

    if len(entity_ids) < len(entities_payload):  # pragma: no cover - defensive
        print("Warning: entity IDs missing from composite response", result)

    print("Bundle result:", result)


async def do_entity_only(case_id: str) -> None:
    payload = {
        "case_id": case_id,
        "role": "defendant",
        "name_full": "Entity Smoke",
        "emails": ["entity@example.com"],
    }
    entity_id = await insert_entity(payload)
    status = await _determine_entity_status(case_id, payload)
    print(f"{status} entity_id:", entity_id)


async def do_case_only(case_number_override: str | None) -> None:
    case = make_smoke_case(case_number_override)
    case_id, status = await insert_case(case)
    print(f"{status} case_id:", case_id)
    # enqueue as part of insert_case, no extra call needed


async def main(
    composite: bool,
    entity: bool,
    case_id_override: str | None,
    force_insert: bool,
    case_number_override: str | None,
    use_idempotent_composite: bool,
) -> None:
    if composite:
        await do_composite(case_number_override, use_idempotent_composite)
    elif entity:
        if case_id_override:
            case_id = case_id_override
        else:
            case = make_smoke_case(case_number_override)
            case_id, status = await insert_case(case, force_insert=force_insert)
            print(f"{status} case_id:", case_id)
        await do_entity_only(case_id)
    else:
        if force_insert:
            case = make_smoke_case(case_number_override)
            case_id, status = await insert_case(case, force_insert=True)
            print(f"{status} case_id:", case_id)
        else:
            await do_case_only(case_number_override)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Supabase RPC smoke helper")
    parser.add_argument("--composite", action="store_true", help="Insert case with demo entities")
    parser.add_argument("--entity", action="store_true", help="Insert entity only")
    parser.add_argument(
        "--case-id",
        dest="case_id",
        help="Existing case_id to reuse with --entity",
    )
    parser.add_argument(
        "--case-number",
        dest="case_number",
        help="Override generated case_number for smoke inserts",
    )
    parser.add_argument(
        "--use-idempotent-composite",
        action="store_true",
        help="Use insert_or_get_case_with_entities RPC",
    )
    parser.add_argument(
        "--force-insert",
        action="store_true",
        help="Call insert_case directly instead of insert_or_get_case",
    )
    args = parser.parse_args()

    asyncio.run(
        main(
            args.composite,
            args.entity,
            args.case_id,
            args.force_insert,
            args.case_number,
            args.use_idempotent_composite,
        )
    )
