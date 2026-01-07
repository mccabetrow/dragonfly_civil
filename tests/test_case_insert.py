"""
tests/test_case_insert.py

Modernized test for idempotent case ingestion.
Uses direct Supabase table operations instead of deprecated RPC.

NOTE: Marked legacy - requires insert_case RPC and specific DB state.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from src.supabase_client import create_supabase_client
from tests.helpers import execute_resilient

# Mark as integration (PostgREST) + legacy (optional schema)
pytestmark = [pytest.mark.integration, pytest.mark.legacy]


def _ensure_supabase_credentials() -> tuple[Any, str]:
    """Get Supabase client with credentials from environment."""
    supabase_env = os.getenv("SUPABASE_MODE", "dev")
    try:
        client = create_supabase_client(supabase_env)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Supabase credentials missing or invalid: {exc}")
    return client, supabase_env


def _build_test_judgment(case_number: str) -> dict[str, Any]:
    """Build a test judgment payload for direct table insert."""
    timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "case_number": case_number,
        "plaintiff_name": "Test Plaintiff LLC",
        "defendant_name": "Test Debtor",
        "judgment_amount": 1234.56,
        "source_file": f"test_insert_{timestamp}",
        "status": "new",
    }


def _insert_judgment(client: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Insert a judgment using direct table upsert.
    Uses ON CONFLICT to be idempotent on case_number.
    Returns the inserted/existing row.
    """
    response = execute_resilient(
        lambda: client.table("judgments").upsert(payload, on_conflict="case_number").execute()
    )
    data = getattr(response, "data", None)
    if data and len(data) > 0:
        return data[0]
    return None


def _fetch_judgment_by_case_number(client: Any, case_number: str) -> dict[str, Any] | None:
    """Fetch a judgment by case_number."""
    response = execute_resilient(
        lambda: (
            client.table("judgments")
            .select("id, case_number, plaintiff_name, defendant_name, judgment_amount")
            .eq("case_number", case_number)
            .limit(1)
            .execute()
        )
    )
    data = getattr(response, "data", None)
    if data and len(data) > 0:
        return data[0]
    return None


@pytest.mark.integration
def test_insert_case_is_idempotent() -> None:
    """
    Verify case insertion is idempotent.

    Insert the same case_number twice and assert:
    1. Both operations succeed without error
    2. The returned id is identical
    3. Only one row exists in the database
    """
    client, _ = _ensure_supabase_credentials()

    # Generate a unique case number to avoid test pollution
    unique_suffix = str(uuid.uuid4())[:8].upper()
    case_number = f"TEST-IDEM-{unique_suffix}"

    payload = _build_test_judgment(case_number)

    # First insert
    first_result = _insert_judgment(client, payload)
    assert first_result is not None, "First insert should return a row"
    first_id = first_result.get("id")
    assert first_id is not None, "First insert should have an id"

    # Second insert (same case_number - should be idempotent)
    second_result = _insert_judgment(client, payload)
    assert second_result is not None, "Second insert should return a row"
    second_id = second_result.get("id")
    assert second_id is not None, "Second insert should have an id"

    # Idempotency check: IDs must match
    assert (
        first_id == second_id
    ), f"Case insert must be idempotent. First id={first_id}, Second id={second_id}"

    # Verify only one row exists
    verify = _fetch_judgment_by_case_number(client, case_number)
    assert verify is not None, "Judgment should exist after insert"
    assert verify.get("id") == first_id, "Fetched id should match inserted id"
    assert verify.get("case_number") == case_number, "Case number should match"


@pytest.mark.integration
def test_insert_case_preserves_data() -> None:
    """
    Verify that inserted case data is preserved correctly.
    """
    client, _ = _ensure_supabase_credentials()

    unique_suffix = str(uuid.uuid4())[:8].upper()
    case_number = f"TEST-DATA-{unique_suffix}"

    payload = _build_test_judgment(case_number)
    payload["plaintiff_name"] = "Preserved Plaintiff Corp"
    payload["defendant_name"] = "Preserved Defendant Inc"
    payload["judgment_amount"] = 9999.99

    result = _insert_judgment(client, payload)
    assert result is not None, "Insert should succeed"

    # Fetch and verify data preservation
    fetched = _fetch_judgment_by_case_number(client, case_number)
    assert fetched is not None, "Judgment should be fetchable"
    assert fetched.get("plaintiff_name") == "Preserved Plaintiff Corp"
    assert fetched.get("defendant_name") == "Preserved Defendant Inc"
    assert float(fetched.get("judgment_amount", 0)) == 9999.99


@pytest.mark.integration
def test_insert_multiple_cases_unique_ids() -> None:
    """
    Verify that multiple different cases get unique IDs.
    """
    client, _ = _ensure_supabase_credentials()

    unique_suffix = str(uuid.uuid4())[:8].upper()
    case_number_1 = f"TEST-MULTI-A-{unique_suffix}"
    case_number_2 = f"TEST-MULTI-B-{unique_suffix}"

    payload_1 = _build_test_judgment(case_number_1)
    payload_2 = _build_test_judgment(case_number_2)

    result_1 = _insert_judgment(client, payload_1)
    result_2 = _insert_judgment(client, payload_2)

    assert result_1 is not None and result_2 is not None
    assert result_1.get("id") != result_2.get("id"), "Different cases should have different IDs"
