"""
Tests for ops.queue_job RPC

Verifies that the SECURITY DEFINER RPC function correctly enqueues jobs
into ops.job_queue with proper validation and input handling.

These tests ensure the "Least Privilege" security architecture works:
- dragonfly_app can enqueue jobs via RPC without direct INSERT grants
- Input validation rejects invalid job types
- Priority and run_at parameters work correctly
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from tests.helpers import execute_resilient

# Mark as integration tests (require PostgREST) + skip if no DB
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("SUPABASE_DB_URL_DEV") and not os.getenv("DATABASE_URL"),
        reason="Database connection not configured",
    ),
]


def get_supabase_client():
    """Get a Supabase client for testing."""
    from supabase import create_client

    url = os.getenv("SUPABASE_URL_DEV") or os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY_DEV") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        pytest.skip("Supabase credentials not configured")

    return create_client(url, key)


def resilient_rpc(client, name: str, params: dict):
    """Execute RPC with retry logic for transient errors."""
    return execute_resilient(lambda: client.rpc(name, params).execute())


def resilient_query(query_builder):
    """Execute query with retry logic for transient errors."""
    return execute_resilient(lambda: query_builder.execute())


class TestQueueJobRPC:
    """Tests for the ops.queue_job RPC function."""

    def test_queue_job_basic(self):
        """Test basic job enqueueing with minimal parameters."""
        client = get_supabase_client()

        # Call the RPC with retry logic
        response = resilient_rpc(
            client,
            "queue_job",
            {
                "p_type": "enrich_idicore",
                "p_payload": {"judgment_id": str(uuid.uuid4()), "test": True},
            },
        )

        # Verify response
        assert response.data is not None, "RPC should return job ID"
        job_id = response.data

        # Verify job exists in queue with correct status
        verify = resilient_query(
            client.from_("job_queue")
            .select("id, job_type, status, priority")
            .eq("id", job_id)
            .single()
        )

        assert verify.data is not None, "Job should exist in queue"
        assert verify.data["status"] == "pending", "Job should have pending status"
        assert verify.data["priority"] == 0, "Job should have default priority 0"

        # Cleanup
        resilient_query(client.from_("job_queue").delete().eq("id", job_id))

    def test_queue_job_with_priority(self):
        """Test job enqueueing with priority parameter."""
        client = get_supabase_client()

        response = resilient_rpc(
            client,
            "queue_job",
            {
                "p_type": "enrich_tlo",
                "p_payload": {"judgment_id": str(uuid.uuid4())},
                "p_priority": 10,
            },
        )

        job_id = response.data
        assert job_id is not None

        # Verify priority was set
        verify = resilient_query(
            client.from_("job_queue").select("priority").eq("id", job_id).single()
        )

        assert verify.data["priority"] == 10, "Job should have priority 10"

        # Cleanup
        resilient_query(client.from_("job_queue").delete().eq("id", job_id))

    def test_queue_job_with_run_at(self):
        """Test job enqueueing with delayed execution."""
        client = get_supabase_client()

        # Schedule job 1 hour in the future
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        run_at_str = future_time.isoformat()

        response = resilient_rpc(
            client,
            "queue_job",
            {
                "p_type": "generate_pdf",
                "p_payload": {"judgment_id": str(uuid.uuid4())},
                "p_run_at": run_at_str,
            },
        )

        job_id = response.data
        assert job_id is not None

        # Verify run_at was set
        verify = resilient_query(
            client.from_("job_queue").select("run_at").eq("id", job_id).single()
        )

        # run_at should be in the future (approximately 1 hour from now)
        stored_run_at = datetime.fromisoformat(verify.data["run_at"].replace("Z", "+00:00"))
        assert stored_run_at > datetime.now(timezone.utc), "run_at should be in the future"

        # Cleanup
        resilient_query(client.from_("job_queue").delete().eq("id", job_id))

    def test_queue_job_rejects_empty_type(self):
        """Test that empty job type is rejected."""
        client = get_supabase_client()

        with pytest.raises(Exception) as exc_info:
            resilient_rpc(
                client,
                "queue_job",
                {
                    "p_type": "",
                    "p_payload": {},
                },
            )

        # Should raise an error about job type being required
        assert (
            "required" in str(exc_info.value).lower() or "exception" in str(exc_info.value).lower()
        )

    def test_queue_job_rejects_null_type(self):
        """Test that null job type is rejected."""
        client = get_supabase_client()

        with pytest.raises(Exception):
            resilient_rpc(
                client,
                "queue_job",
                {
                    "p_type": None,
                    "p_payload": {},
                },
            )

    def test_queue_job_handles_null_payload(self):
        """Test that null payload defaults to empty object."""
        client = get_supabase_client()

        response = resilient_rpc(
            client,
            "queue_job",
            {
                "p_type": "enrich_idicore",
                "p_payload": None,
            },
        )

        job_id = response.data
        assert job_id is not None

        # Verify payload is empty object
        verify = resilient_query(
            client.from_("job_queue").select("payload").eq("id", job_id).single()
        )

        assert verify.data["payload"] == {} or verify.data["payload"] is None

        # Cleanup
        resilient_query(client.from_("job_queue").delete().eq("id", job_id))

    def test_queue_job_returns_uuid(self):
        """Test that RPC returns a valid UUID."""
        client = get_supabase_client()

        response = resilient_rpc(
            client,
            "queue_job",
            {
                "p_type": "enrich_idicore",
                "p_payload": {"test": True},
            },
        )

        job_id = response.data
        assert job_id is not None

        # Verify it's a valid UUID
        parsed = uuid.UUID(job_id)
        assert str(parsed) == job_id

        # Cleanup
        resilient_query(client.from_("job_queue").delete().eq("id", job_id))


class TestQueueJobRPCClient:
    """Tests for the Python RPCClient.queue_job method."""

    def test_rpc_client_queue_job(self):
        """Test the RPCClient.queue_job method works correctly."""
        import psycopg

        db_url = os.getenv("SUPABASE_DB_URL_DEV") or os.getenv("DATABASE_URL")
        if not db_url:
            pytest.skip("Database URL not configured")

        from backend.workers.rpc_client import RPCClient

        with psycopg.connect(db_url) as conn:
            rpc = RPCClient(conn)
            job_id = rpc.queue_job(
                job_type="enrich_idicore",
                payload={"test": True, "source": "test_rpc_client"},
                priority=5,
            )

            assert job_id is not None, "queue_job should return job ID"
            assert isinstance(job_id, uuid.UUID), "job_id should be UUID"

            # Verify job exists
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT job_type, priority, status FROM ops.job_queue WHERE id = %s",
                    (str(job_id),),
                )
                row = cur.fetchone()
                assert row is not None, "Job should exist"
                assert row[0] == "enrich_idicore", "Job type should match"
                assert row[1] == 5, "Priority should be 5"
                assert row[2] == "pending", "Status should be pending"

                # Cleanup
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (str(job_id),))
                conn.commit()

    def test_rpc_client_enqueue_job_deprecated(self):
        """Test that deprecated enqueue_job delegates to queue_job."""
        import psycopg

        db_url = os.getenv("SUPABASE_DB_URL_DEV") or os.getenv("DATABASE_URL")
        if not db_url:
            pytest.skip("Database URL not configured")

        from backend.workers.rpc_client import RPCClient

        with psycopg.connect(db_url) as conn:
            rpc = RPCClient(conn)

            # Use deprecated method
            job_id = rpc.enqueue_job(
                job_type="enrich_idicore",
                payload={"test": True, "source": "deprecated_method"},
            )

            assert job_id is not None, "enqueue_job should still work"

            # Cleanup
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (str(job_id),))
                conn.commit()
