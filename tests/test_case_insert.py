from __future__ import annotations

import os
from typing import Any

import pytest

from src.supabase_client import create_supabase_client
from tools.demo_insert_case import (
    DEFAULT_AMOUNT_CENTS,
    DEFAULT_CASE_NUMBER,
    build_demo_payload,
    upsert_case,
)


def _ensure_supabase_credentials() -> tuple[Any, str]:
    supabase_env = os.getenv("DEMO_CASE_SUPABASE_ENV", "prod")
    try:
        client = create_supabase_client(supabase_env)
    except Exception as exc:  # pragma: no cover - exercised in integration context
        pytest.fail(f"Supabase credentials missing or invalid: {exc}")
    return client, supabase_env


def _fetch_entities(client: Any, case_id: str) -> list[dict[str, Any]]:
    try:
        response = (
            client.table("v_entities_simple")
            .select("entity_id,case_id,role,name_full")
            .eq("case_id", case_id)
            .execute()
        )
    except Exception as exc:  # pragma: no cover - integration guardrail
        pytest.fail(f"Supabase entity lookup failed: {exc}")
    return list(getattr(response, "data", []) or [])


@pytest.mark.integration
@pytest.mark.parametrize(
    "case_number",
    [os.getenv("DEMO_CASE_NUMBER", DEFAULT_CASE_NUMBER)],
)
def test_insert_case_is_idempotent(case_number: str) -> None:
    """Verify insert_or_get_case_with_entities remains idempotent for demo payload."""
    client, supabase_env = _ensure_supabase_credentials()
    normalized_case_number = case_number.strip().upper()
    payload = build_demo_payload(normalized_case_number, DEFAULT_AMOUNT_CENTS)

    first = upsert_case(
        client,
        payload,
        supabase_env=supabase_env,
        case_number_hint=normalized_case_number,
        amount_cents=DEFAULT_AMOUNT_CENTS,
    )
    second = upsert_case(
        client,
        payload,
        supabase_env=supabase_env,
        case_number_hint=normalized_case_number,
        amount_cents=DEFAULT_AMOUNT_CENTS,
    )

    assert first["case_id"] == second["case_id"], "Case insert must be idempotent"
    assert (
        second["entity_ids"] == first["entity_ids"]
    ), "Entity ids should remain stable"
    assert len(second["entity_ids"]) == len(
        set(second["entity_ids"])
    ), "Entity ids should be unique"

    entities = _fetch_entities(client, second["case_id"])
    assert len(entities) >= 2, "Expected at least plaintiff and defendant entities"
    roles_by_entity = [entity.get("role") for entity in entities]
    assert (
        roles_by_entity.count("plaintiff") == 1
    ), "Exactly one plaintiff entity expected"
    assert (
        roles_by_entity.count("defendant") == 1
    ), "Exactly one defendant entity expected"
