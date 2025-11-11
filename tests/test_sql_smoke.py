import os
import uuid

import httpx

from src.config.api_surface import SCHEMA_PROFILE

BASE = f'https://{os.environ["SUPABASE_PROJECT_REF"]}.supabase.co'
KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
H = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Accept": "application/json",
    "Content-Profile": SCHEMA_PROFILE,
    "Accept-Profile": SCHEMA_PROFILE,
}


def _rest(path: str) -> str:
    return f"{BASE}/rest/v1{path}"


def test_insert_case_and_read_tier() -> None:
    case_number = f"PYTEST-{uuid.uuid4().hex[:6].upper()}"
    case = {
        "case_number": case_number,
        "court": "NYC Civil",
        "county": "Kings",
        "principal_amt": 1234,
        "status": "new",
        "source": "pytest",
        "title": "pytest smoke",
    }

    with httpx.Client(timeout=30) as client:
        response = client.post(
            _rest("/rpc/insert_case"),
            headers={
                **H,
                "Content-Profile": "public",
                "Accept-Profile": "public",
                "Accept": "application/json",
            },
            json={"payload": case},
        )
        response.raise_for_status()
        body = response.json()
        if isinstance(body, list) and body:
            body = body[0]
        if isinstance(body, dict):
            case_id = body.get("insert_case") or body.get("case_id") or body.get("id")
        else:
            case_id = body
        if not isinstance(case_id, str) or not case_id:
            raise AssertionError(f"Unexpected RPC response payload: {body!r}")

        public_headers = {
            **H,
            "Content-Profile": "public",
            "Accept-Profile": "public",
            "Accept": "application/json",
        }
        client.get(
            _rest("/v_cases"),
            params={"case_id": f"eq.{case_id}", "select": "case_id"},
            headers=public_headers,
        ).raise_for_status()

        audit_response = client.get(
            _rest("/v_ingestion_runs"),
            params={
                "ref_id": f"eq.{case_id}",
                "event": "eq.insert_case",
                "select": "run_id,created_at",
                "limit": "1",
            },
            headers={**H, "Accept": "application/json"},
        )
        audit_response.raise_for_status()
        audit_rows = audit_response.json()

    assert isinstance(audit_rows, list)
    assert audit_rows, "Expected at least one audit run for inserted case"
