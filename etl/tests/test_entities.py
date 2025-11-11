import os
import uuid
from typing import Dict, Any

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE = os.environ["SUPABASE_URL"].rstrip("/")
ANON = os.environ["SUPABASE_ANON_KEY"]

INSERT_CASE_WITH_ENTITIES = f"{BASE}/rest/v1/rpc/insert_case_with_entities"
ENTITIES_VIEW = f"{BASE}/rest/v1/v_entities_simple"

HEADERS = {
    "apikey": ANON,
    "Authorization": f"Bearer {ANON}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Prefer": "return=representation",
}


def _random_case_number() -> str:
    return f"SMOKE-ENT-{uuid.uuid4().hex[:6].upper()}"


def _composite_payload() -> Dict[str, Any]:
    return {
        "payload": {
            "case": {
                "case_number": _random_case_number(),
                "source": "pytest",
                "title": "Gamma v. Delta",
                "court": "NYC Civil Court",
            },
            "entities": [
                {
                    "role": "plaintiff",
                    "name_full": "Alice Plaintiff",
                    "emails": ["alice@example.com"],
                },
                {
                    "role": "defendant",
                    "name_full": "Bob Defendant",
                    "phones": ["555-0100"],
                },
            ],
        }
    }


def _assert_response_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    assert "case_id" in payload
    assert "entity_ids" in payload
    assert isinstance(payload["case_id"], str)
    assert isinstance(payload["entity_ids"], list)
    assert len(payload["entity_ids"]) == 2
    uuid.UUID(payload["case_id"])  # raises if invalid
    for entity_id in payload["entity_ids"]:
        uuid.UUID(entity_id)
    return payload


def test_insert_case_with_entities_roundtrip() -> None:
    payload = _composite_payload()

    response = httpx.post(INSERT_CASE_WITH_ENTITIES, headers=HEADERS, json=payload, timeout=20)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list) and data:
        data = data[0]
    assert isinstance(data, dict)

    record = _assert_response_payload(data)
    case_id = record["case_id"]

    params = {"case_id": f"eq.{case_id}"}
    response = httpx.get(ENTITIES_VIEW, headers=HEADERS, params=params, timeout=20)
    response.raise_for_status()
    rows = response.json()
    assert isinstance(rows, list)
    assert len(rows) == 2

    roles = {row["role"] for row in rows}
    assert roles == {"plaintiff", "defendant"}