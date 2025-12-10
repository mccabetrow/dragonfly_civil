"""
RPC Contract Tests for Dragonfly Civil

Tests idempotency and stability guarantees for critical RPCs:
- insert_or_get_case_with_entities: Idempotent case+entity bundle insertion
- queue_job: Message queue job enqueueing
- upsert_enrichment_bundle: Enrichment data upsert

Each test calls the RPC twice with identical payloads and asserts:
1. The response is stable (same IDs, same shape)
2. DB state is not duplicated (no extra rows created)

NOTE: Marked legacy - requires specific RPC functions and DB schema.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg
import pytest

from src.supabase_client import create_supabase_client

pytestmark = pytest.mark.legacy  # Requires RPC functions not always deployed

# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


def _get_db_url() -> str:
    """Resolve the Supabase database URL from environment."""
    explicit = os.environ.get("SUPABASE_DB_URL")
    if explicit:
        return explicit
    project_ref = os.environ.get("SUPABASE_PROJECT_REF")
    password = os.environ.get("SUPABASE_DB_PASSWORD")
    if not project_ref or not password:
        pytest.skip("Supabase database credentials not configured")
    return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"


def _get_supabase_client() -> Any:
    """Create a Supabase client for RPC calls."""
    supabase_env = os.getenv("SUPABASE_MODE", "dev")
    try:
        return create_supabase_client(supabase_env)
    except Exception as exc:
        pytest.skip(f"Supabase client unavailable: {exc}")


def _unique_case_number() -> str:
    """Generate a unique case number for test isolation."""
    return f"RPC-TEST-{uuid.uuid4().hex[:8].upper()}"


def _unique_idempotency_key() -> str:
    """Generate a unique idempotency key."""
    return f"pytest-rpc:{uuid.uuid4()}"


# ---------------------------------------------------------------------------
# insert_or_get_case_with_entities Contract
# ---------------------------------------------------------------------------
#
# RPC: public.insert_or_get_case_with_entities(payload jsonb)
#
# INPUTS:
#   payload: {
#     "case": {
#       "case_number": string (required, uppercased, trimmed)
#       "source": string (default: "unknown")
#       "org_id": uuid (default: nil UUID)
#       "court": string (optional)
#       "title": string (optional)
#       "amount_awarded": numeric (optional)
#       "judgment_date": date (optional)
#     },
#     "entities": [
#       {
#         "role": "plaintiff"|"defendant"|...
#         "name_full": string
#         "name_normalized": string (optional)
#         ... additional entity fields
#       }
#     ]
#   }
#
# OUTPUTS:
#   {
#     "case_id": uuid
#     "case_number": string
#     "source": string
#     "court": string
#     "title": string
#     "amount_awarded": numeric
#     "judgment_date": date
#     "case": { ... same fields ... }
#     "entities": [ { "entity_id", "role", "name_full", "name_normalized" } ]
#     "entity_ids": [uuid, ...]
#     "meta": { "inserted_entities": int }
#   }
#
# IDEMPOTENCY GUARANTEES:
#   - Case lookup by (case_number, source): returns existing case_id if found
#   - Entity insertion: deduplicates by (case_id, role, name_normalized)
#   - Second call with same payload returns same case_id and entity_ids
#   - No duplicate rows are created in judgments.cases or parties.entities
#


@pytest.mark.integration
class TestInsertOrGetCaseWithEntities:
    """Contract tests for insert_or_get_case_with_entities RPC."""

    def test_idempotent_case_insertion(self) -> None:
        """Calling RPC twice with identical payload returns same case_id."""
        client = _get_supabase_client()
        case_number = _unique_case_number()

        payload = {
            "case": {
                "case_number": case_number,
                "source": "test-rpc-contract",
                "court": "Test Court",
                "title": "Test Plaintiff v. Test Defendant",
                "amount_awarded": 1000.00,
            },
            "entities": [
                {"role": "plaintiff", "name_full": "Test Plaintiff LLC"},
                {"role": "defendant", "name_full": "Test Defendant Inc"},
            ],
        }

        # First call
        resp1 = client.rpc("insert_or_get_case_with_entities", {"payload": payload}).execute()
        result1 = resp1.data
        assert result1 is not None, "First RPC call should return data"
        assert "case_id" in result1, "Response must include case_id"

        # Second call with identical payload
        resp2 = client.rpc("insert_or_get_case_with_entities", {"payload": payload}).execute()
        result2 = resp2.data
        assert result2 is not None, "Second RPC call should return data"

        # Assert idempotency
        assert result1["case_id"] == result2["case_id"], "Case ID must be stable across calls"
        assert result1["case_number"] == result2["case_number"]
        assert set(result1.get("entity_ids", [])) == set(
            result2.get("entity_ids", [])
        ), "Entity IDs must be stable across calls"

    def test_no_duplicate_rows_created(self) -> None:
        """Second RPC call must not create duplicate case or entity rows."""
        client = _get_supabase_client()
        db_url = _get_db_url()
        case_number = _unique_case_number()

        payload = {
            "case": {
                "case_number": case_number,
                "source": "test-rpc-contract",
            },
            "entities": [
                {"role": "plaintiff", "name_full": "Stable Plaintiff"},
            ],
        }

        # First call
        resp1 = client.rpc("insert_or_get_case_with_entities", {"payload": payload}).execute()
        result1 = resp1.data
        case_id = result1["case_id"]

        # Count rows after first call
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM judgments.cases WHERE case_id = %s",
                    (case_id,),
                )
                row = cur.fetchone()
                cases_count_1 = row[0] if row else 0

                cur.execute(
                    "SELECT count(*) FROM parties.entities WHERE case_id = %s",
                    (case_id,),
                )
                row = cur.fetchone()
                entities_count_1 = row[0] if row else 0

        # Second call
        client.rpc("insert_or_get_case_with_entities", {"payload": payload}).execute()

        # Count rows after second call
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM judgments.cases WHERE case_id = %s",
                    (case_id,),
                )
                row = cur.fetchone()
                cases_count_2 = row[0] if row else 0

                cur.execute(
                    "SELECT count(*) FROM parties.entities WHERE case_id = %s",
                    (case_id,),
                )
                row = cur.fetchone()
                entities_count_2 = row[0] if row else 0

        assert (
            cases_count_1 == cases_count_2 == 1
        ), f"Expected exactly 1 case row, got {cases_count_1} then {cases_count_2}"
        assert (
            entities_count_1 == entities_count_2
        ), f"Entity count changed from {entities_count_1} to {entities_count_2}"


# ---------------------------------------------------------------------------
# queue_job Contract
# ---------------------------------------------------------------------------
#
# RPC: public.queue_job(payload jsonb)
#
# INPUTS:
#   payload: {
#     "kind": "enrich"|"outreach"|"enforce"|"case_copilot"|"collectability"|"escalation"
#     "idempotency_key": string (required, non-empty)
#     "payload": { ... job-specific data ... }
#   }
#
# OUTPUTS:
#   bigint - the pgmq message ID
#
# IDEMPOTENCY GUARANTEES:
#   - Each call with a UNIQUE idempotency_key creates a new message
#   - The RPC itself does NOT deduplicate by idempotency_key at the DB level
#   - Idempotency is enforced by workers checking processed keys
#   - Returns a stable message ID for the enqueued job
#
# NOTE: This RPC is NOT idempotent in the database sense - calling twice
# with the same key will create two messages. Idempotency is handled by
# downstream workers that track processed idempotency_keys.
#


@pytest.mark.integration
class TestQueueJob:
    """Contract tests for queue_job RPC."""

    def test_enqueue_returns_message_id(self) -> None:
        """queue_job returns a valid message ID."""
        client = _get_supabase_client()

        payload = {
            "kind": "enforce",
            "idempotency_key": _unique_idempotency_key(),
            "payload": {
                "test": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

        resp = client.rpc("queue_job", {"payload": payload}).execute()
        msg_id = resp.data

        assert msg_id is not None, "queue_job must return a message ID"
        assert isinstance(msg_id, int), f"Message ID should be int, got {type(msg_id)}"
        assert msg_id > 0, "Message ID should be positive"

    def test_different_idempotency_keys_create_separate_messages(self) -> None:
        """Each unique idempotency_key creates a distinct message."""
        client = _get_supabase_client()

        key1 = _unique_idempotency_key()
        key2 = _unique_idempotency_key()

        resp1 = client.rpc(
            "queue_job",
            {
                "payload": {
                    "kind": "enforce",
                    "idempotency_key": key1,
                    "payload": {"test": 1},
                }
            },
        ).execute()

        resp2 = client.rpc(
            "queue_job",
            {
                "payload": {
                    "kind": "enforce",
                    "idempotency_key": key2,
                    "payload": {"test": 2},
                }
            },
        ).execute()

        assert (
            resp1.data != resp2.data
        ), "Different idempotency keys should produce different message IDs"

    def test_validates_required_kind(self) -> None:
        """queue_job raises error when kind is missing."""
        client = _get_supabase_client()

        with pytest.raises(Exception) as exc_info:
            client.rpc(
                "queue_job",
                {
                    "payload": {
                        "idempotency_key": _unique_idempotency_key(),
                        "payload": {},
                    }
                },
            ).execute()

        assert "kind" in str(exc_info.value).lower()

    def test_validates_required_idempotency_key(self) -> None:
        """queue_job raises error when idempotency_key is missing."""
        client = _get_supabase_client()

        with pytest.raises(Exception) as exc_info:
            client.rpc(
                "queue_job",
                {
                    "payload": {
                        "kind": "enforce",
                        "payload": {},
                    }
                },
            ).execute()

        assert "idempotency_key" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# upsert_enrichment_bundle Contract
# ---------------------------------------------------------------------------
#
# RPC: public.upsert_enrichment_bundle(bundle jsonb)
#
# INPUTS:
#   bundle: {
#     "case_id": uuid (required)
#     "contacts": [
#       {
#         "entity_id": uuid (required)
#         "kind": "phone"|"email"|"address" (required)
#         "value": string (required)
#         "source": string (optional)
#         "score": numeric (optional)
#         "validated_bool": boolean (optional, default false)
#       }
#     ],
#     "assets": [
#       {
#         "entity_id": uuid (required)
#         "asset_type": string (required)
#         "meta_json": object (optional)
#         "source": string (optional)
#         "confidence": numeric (optional)
#       }
#     ]
#   }
#
# OUTPUTS:
#   {
#     "contacts_upserted": int
#     "assets_upserted": int
#   }
#
# IDEMPOTENCY GUARANTEES:
#   - Contacts: UPSERT by (entity_id, kind, value) - updates source/score/validated
#   - Assets: UPSERT by (entity_id, asset_type, hash of meta_json) - updates source/confidence
#   - Second call with same data updates existing rows, does not duplicate
#   - Row counts remain stable after repeated calls
#


@pytest.mark.integration
class TestUpsertEnrichmentBundle:
    """Contract tests for upsert_enrichment_bundle RPC."""

    def _create_test_case_and_entity(self, client: Any) -> tuple[str, str]:
        """Helper to create a test case with an entity for enrichment tests."""
        case_number = _unique_case_number()
        payload = {
            "case": {
                "case_number": case_number,
                "source": "enrichment-test",
            },
            "entities": [
                {"role": "defendant", "name_full": "Enrichment Test Defendant"},
            ],
        }

        resp = client.rpc("insert_or_get_case_with_entities", {"payload": payload}).execute()
        result = resp.data
        case_id = result["case_id"]
        entity_ids = result.get("entity_ids", [])

        if not entity_ids:
            pytest.skip("Could not create test entity for enrichment test")

        return case_id, entity_ids[0]

    def test_idempotent_contact_upsert(self) -> None:
        """Calling upsert twice with same contacts does not duplicate rows."""
        client = _get_supabase_client()
        db_url = _get_db_url()

        case_id, entity_id = self._create_test_case_and_entity(client)

        bundle = {
            "case_id": case_id,
            "contacts": [
                {
                    "entity_id": entity_id,
                    "kind": "phone",
                    "value": "555-TEST-001",
                    "source": "rpc-test",
                    "score": 0.85,
                },
                {
                    "entity_id": entity_id,
                    "kind": "email",
                    "value": "test@example.com",
                    "source": "rpc-test",
                    "score": 0.90,
                },
            ],
            "assets": [],
        }

        # First upsert
        resp1 = client.rpc("upsert_enrichment_bundle", {"bundle": bundle}).execute()
        result1 = resp1.data
        assert result1 is not None

        # Count contacts after first call
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM enrichment.contacts WHERE entity_id = %s",
                    (entity_id,),
                )
                row = cur.fetchone()
                contacts_count_1 = row[0] if row else 0

        # Second upsert with same data
        resp2 = client.rpc("upsert_enrichment_bundle", {"bundle": bundle}).execute()
        result2 = resp2.data
        assert result2 is not None

        # Count contacts after second call
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM enrichment.contacts WHERE entity_id = %s",
                    (entity_id,),
                )
                row = cur.fetchone()
                contacts_count_2 = row[0] if row else 0

        assert (
            contacts_count_1 == contacts_count_2
        ), f"Contact count changed from {contacts_count_1} to {contacts_count_2}"

    def test_updates_existing_contact_fields(self) -> None:
        """Second upsert updates mutable fields on existing contacts."""
        client = _get_supabase_client()
        db_url = _get_db_url()

        case_id, entity_id = self._create_test_case_and_entity(client)

        # Initial contact
        bundle_v1 = {
            "case_id": case_id,
            "contacts": [
                {
                    "entity_id": entity_id,
                    "kind": "phone",
                    "value": "555-UPDATE-TEST",
                    "source": "source-v1",
                    "score": 0.50,
                    "validated_bool": False,
                },
            ],
            "assets": [],
        }

        client.rpc("upsert_enrichment_bundle", {"bundle": bundle_v1}).execute()

        # Updated contact (same entity_id, kind, value but different score/source)
        bundle_v2 = {
            "case_id": case_id,
            "contacts": [
                {
                    "entity_id": entity_id,
                    "kind": "phone",
                    "value": "555-UPDATE-TEST",
                    "source": "source-v2",
                    "score": 0.95,
                    "validated_bool": True,
                },
            ],
            "assets": [],
        }

        client.rpc("upsert_enrichment_bundle", {"bundle": bundle_v2}).execute()

        # Verify the contact was updated, not duplicated
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT source, score, validated_bool
                    FROM enrichment.contacts
                    WHERE entity_id = %s AND kind = 'phone' AND value = '555-UPDATE-TEST'
                    """,
                    (entity_id,),
                )
                row = cur.fetchone()

        assert row is not None, "Contact should exist"
        source, score, validated = row
        assert source == "source-v2", f"Source should be updated to source-v2, got {source}"
        assert float(score) == pytest.approx(0.95), f"Score should be 0.95, got {score}"
        assert validated is True, "validated_bool should be True"

    def test_validates_required_case_id(self) -> None:
        """upsert_enrichment_bundle raises error when case_id is missing."""
        client = _get_supabase_client()

        with pytest.raises(Exception) as exc_info:
            client.rpc(
                "upsert_enrichment_bundle",
                {
                    "bundle": {
                        "contacts": [],
                        "assets": [],
                    }
                },
            ).execute()

        assert "case_id" in str(exc_info.value).lower()
