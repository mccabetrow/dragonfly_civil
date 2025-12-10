"""Example worker that pushes an enrichment bundle to Supabase."""

from __future__ import annotations

import json
import random
import time
from typing import Any, Dict

from src.db.supabase_client import COMMON, postgrest
from src.transforms.models_enrichment import Asset, Contact, EnrichmentBundle

_MAX_RETRIES = 5


def send_bundle(bundle: EnrichmentBundle) -> Dict[str, Any]:
    """Call the Supabase RPC with retries on throttling or 5xx errors."""

    payload = bundle.to_jsonb()
    headers = {"Content-Type": "application/json"}
    for attempt in range(1, _MAX_RETRIES + 1):
        with postgrest(timeout=10.0) as client:
            response = client.post("/rpc/upsert_enrichment_bundle", json=payload, headers=headers)
        if response.status_code < 400:
            return response.json()
        if response.status_code not in {429} and response.status_code < 500:
            response.raise_for_status()
        if attempt == _MAX_RETRIES:
            response.raise_for_status()
        sleep_for = min(2**attempt, 30) + random.uniform(0, 1)
        time.sleep(sleep_for)
    raise RuntimeError("RPC call failed after retries")


def _fetch_sample_case() -> Dict[str, Any]:
    params = {
        "select": "case_id,index_no,status",
        "status": "in.(new,enriched)",
        "order": "updated_at.desc",
        "limit": 1,
    }
    with postgrest(timeout=10.0) as client:
        response = client.get("/v_cases", params=params)
        response.raise_for_status()
        rows = response.json()
        if not rows:
            raise RuntimeError("No cases available for enrichment sample")
        return rows[0]


def _fetch_defendant(case_id: str) -> Dict[str, Any]:
    with postgrest(timeout=10.0) as client:
        headers = {
            **COMMON,
            "Accept-Profile": "parties",
            "Content-Profile": "parties",
        }
        response = client.get(
            "/roles",
            params={
                "case_id": f"eq.{case_id}",
                "role": "eq.defendant",
                "select": "entity_id,role",
                "limit": 1,
            },
            headers=headers,
        )
        response.raise_for_status()
        rows = response.json()
        if not rows:
            raise RuntimeError("No defendant entity found for sample bundle")
        return rows[0]


def main() -> None:
    case = _fetch_sample_case()
    case_id = case["case_id"]
    role = _fetch_defendant(case_id)
    entity_id = role["entity_id"]

    bundle = EnrichmentBundle(
        case_id=case_id,
        contacts=[
            Contact(
                entity_id=entity_id,
                kind="phone",
                value="(212) 555-1212",
                source="mock",
                score=92.0,
                validated_bool=True,
            ),
            Contact(
                entity_id=entity_id,
                kind="email",
                value="defendant@example.com",
                source="mock",
                score=88.0,
                validated_bool=True,
            ),
            Contact(
                entity_id=entity_id,
                kind="address",
                value="123 Mockingbird Ln, Queens, NY 11432",
                source="mock",
                validated_bool=False,
            ),
        ],
        assets=[
            Asset(
                entity_id=entity_id,
                asset_type="employment",
                source="mock",
                confidence=75.0,
                meta_json={"employer": "Example Corp", "title": "Manager"},
            )
        ],
    )

    result = send_bundle(bundle)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":  # pragma: no cover - manual run hook
    main()
