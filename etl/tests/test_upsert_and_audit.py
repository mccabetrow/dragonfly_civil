import os
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE = os.environ["SUPABASE_URL"].rstrip("/")
ANON = os.environ["SUPABASE_ANON_KEY"]
SERVICE = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

INSERT_OR_GET_CASE = f"{BASE}/rest/v1/rpc/insert_or_get_case"
CASES_VIEW = f"{BASE}/rest/v1/v_cases_with_org"
AUDIT_VIEW = f"{BASE}/rest/v1/v_ingestion_runs"

HEADERS_ANON = {
    "apikey": ANON,
    "Authorization": f"Bearer {ANON}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Prefer": "return=representation",
}

HEADERS_SERVICE = {
    "apikey": SERVICE,
    "Authorization": f"Bearer {SERVICE}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def _random_case_number() -> str:
    return f"SMOKE-UP-{uuid.uuid4().hex[:6].upper()}"


def _call_insert_or_get(case_number: str) -> str:
    payload = {
        "payload": {
            "case_number": case_number,
            "source": "pytest",
            "title": "Upsert Smoke",
            "court": "NYC Civil Court",
            "amount_awarded": 100.0,
        }
    }
    response = httpx.post(INSERT_OR_GET_CASE, headers=HEADERS_ANON, json=payload, timeout=20)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, str):
        value = data
    else:
        if not isinstance(data, dict):
            raise AssertionError(f"Unexpected RPC response: {data!r}")
        value = data.get("insert_or_get_case") or data.get("case_id") or next(iter(data.values()), None)
    if not value:
        raise AssertionError(f"Missing case id in response: {data!r}")
    return str(value)


def test_upsert_creates_audit_entry() -> None:
    case_number = _random_case_number()

    first_id = _call_insert_or_get(case_number)
    second_id = _call_insert_or_get(case_number)

    assert first_id == second_id

    params = {
        "case_id": f"eq.{first_id}",
        "limit": "1",
    }
    response = httpx.get(CASES_VIEW, headers=HEADERS_ANON, params=params, timeout=20)
    response.raise_for_status()
    rows = response.json()
    assert isinstance(rows, list) and rows, "Case view returned no rows"

    audit_params = {
        "event": "eq.insert_case",
        "ref_id": f"eq.{first_id}",
    }
    response = httpx.get(AUDIT_VIEW, headers=HEADERS_SERVICE, params=audit_params, timeout=20)
    response.raise_for_status()
    audits = response.json()
    assert isinstance(audits, list)
    assert len(audits) >= 1
