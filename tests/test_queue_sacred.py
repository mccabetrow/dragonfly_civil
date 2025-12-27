"""
Sacred Queue Tests - Locking, Reaper, and Idempotency

These tests verify the "Sacred" guarantees of ops.job_queue:
1. LOCKING: Two workers cannot claim the same job (FOR UPDATE SKIP LOCKED)
2. REAPER: Stuck jobs are recovered or moved to DLQ deterministically
3. IDEMPOTENCY: Duplicate job submissions are prevented by unique constraint

Uses psycopg (direct DB) for full transaction control and concurrent testing.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

# Require psycopg v3 for true async/concurrent testing
try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None

# Mark as integration tests + require DB
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("SUPABASE_DB_URL_DEV") and not os.getenv("DATABASE_URL"),
        reason="Database connection not configured",
    ),
    pytest.mark.skipif(psycopg is None, reason="psycopg v3 required"),
]


def get_db_url() -> str:
    """Get direct database URL (port 5432, not pooler)."""
    url = os.getenv("SUPABASE_DB_URL_DEV") or os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("Database URL not configured")
    # Ensure we're using direct connection (port 5432) for transaction tests
    if ":6543" in url:
        url = url.replace(":6543", ":5432")
    return url


def get_connection():
    """Get a new database connection."""
    return psycopg.connect(get_db_url(), row_factory=dict_row)


class TestSacredLocking:
    """Test 1: Two workers cannot claim the same job (FOR UPDATE SKIP LOCKED)."""

    def test_two_workers_cannot_claim_same_job(self):
        """
        Insert one job. Two threads call claim_pending_job simultaneously.
        Assert only ONE gets the job.
        """
        job_id = None
        claim_results = []
        lock = threading.Lock()

        # Setup: Insert a single pending job
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ops.job_queue (job_type, payload, status, idempotency_key)
                    VALUES ('enrich_idicore', '{"test": true}'::jsonb, 'pending', %s)
                    RETURNING id
                """,
                    (f"lock-test-{uuid.uuid4()}",),
                )
                job_id = cur.fetchone()["id"]
                conn.commit()

        def worker_claim(worker_id: str):
            """Simulate a worker trying to claim a job."""
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        # Small random delay to stagger claims
                        time.sleep(0.01 * (hash(worker_id) % 5))

                        cur.execute(
                            """
                            SELECT * FROM ops.claim_pending_job(
                                ARRAY['enrich_idicore']::text[],
                                30,
                                %s
                            )
                        """,
                            (worker_id,),
                        )
                        result = cur.fetchone()
                        conn.commit()

                        with lock:
                            claim_results.append(
                                {
                                    "worker": worker_id,
                                    "claimed": result is not None,
                                    "job_id": result["job_id"] if result else None,
                                }
                            )
            except Exception as e:
                with lock:
                    claim_results.append({"worker": worker_id, "claimed": False, "error": str(e)})

        # Execute: Two workers try to claim simultaneously
        with ThreadPoolExecutor(max_workers=2) as executor:
            executor.submit(worker_claim, "worker-A")
            executor.submit(worker_claim, "worker-B")

        # Assert: Exactly ONE worker got the job
        successful_claims = [r for r in claim_results if r.get("claimed")]
        assert len(successful_claims) == 1, (
            f"Expected exactly 1 successful claim, got {len(successful_claims)}: {claim_results}"
        )

        # Verify the winner got the correct job
        winner = successful_claims[0]
        assert winner["job_id"] == job_id, f"Winner got wrong job: {winner['job_id']} != {job_id}"

        # Cleanup
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                conn.commit()

    def test_multiple_jobs_distributed_across_workers(self):
        """
        Insert 5 jobs. 3 workers claim simultaneously.
        Each worker should get different jobs (no overlap).
        """
        job_ids = []
        claim_results = []
        lock = threading.Lock()

        # Setup: Insert 5 pending jobs
        with get_connection() as conn:
            with conn.cursor() as cur:
                for i in range(5):
                    cur.execute(
                        """
                        INSERT INTO ops.job_queue (job_type, payload, status, idempotency_key)
                        VALUES ('enrich_idicore', %s::jsonb, 'pending', %s)
                        RETURNING id
                    """,
                        (f'{{"job_num": {i}}}', f"multi-lock-{uuid.uuid4()}"),
                    )
                    job_ids.append(cur.fetchone()["id"])
                conn.commit()

        def worker_claim_multiple(worker_id: str):
            """Worker claims up to 2 jobs."""
            claimed = []
            for _ in range(2):
                try:
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                SELECT * FROM ops.claim_pending_job(
                                    ARRAY['enrich_idicore']::text[],
                                    30,
                                    %s
                                )
                            """,
                                (worker_id,),
                            )
                            result = cur.fetchone()
                            conn.commit()
                            if result:
                                claimed.append(result["job_id"])
                except Exception:
                    pass

            with lock:
                claim_results.append({"worker": worker_id, "claimed_jobs": claimed})

        # Execute: 3 workers claim simultaneously
        with ThreadPoolExecutor(max_workers=3) as executor:
            for i in range(3):
                executor.submit(worker_claim_multiple, f"worker-{i}")

        # Assert: No job claimed by multiple workers
        all_claimed = []
        for r in claim_results:
            all_claimed.extend(r["claimed_jobs"])

        assert len(all_claimed) == len(set(all_claimed)), (
            f"Duplicate claims detected: {all_claimed}"
        )

        # Cleanup
        with get_connection() as conn:
            with conn.cursor() as cur:
                for jid in job_ids:
                    cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (jid,))
                conn.commit()


class TestSacredReaper:
    """Test 2: Stuck jobs are recovered or moved to DLQ deterministically."""

    def test_reaper_recovers_stuck_job_within_max_attempts(self):
        """
        Insert a job, manually set status='processing' and started_at=1 hour ago.
        Run reap_stuck_jobs. Assert it returns to 'pending' with backoff.
        """
        job_id = None

        with get_connection() as conn:
            with conn.cursor() as cur:
                # Insert job with attempts < max_attempts
                cur.execute(
                    """
                    INSERT INTO ops.job_queue (
                        job_type, payload, status, attempts, max_attempts,
                        started_at, worker_id, idempotency_key
                    )
                    VALUES (
                        'enrich_idicore',
                        '{"test": true}'::jsonb,
                        'processing',
                        1,
                        3,
                        NOW() - INTERVAL '1 hour',
                        'stuck-worker-1',
                        %s
                    )
                    RETURNING id
                """,
                    (f"reaper-test-{uuid.uuid4()}",),
                )
                job_id = cur.fetchone()["id"]
                conn.commit()

                # Run the reaper (30 min timeout, job is 1 hour old = stuck)
                cur.execute("SELECT * FROM ops.reap_stuck_jobs(30)")
                reaped = cur.fetchall()
                conn.commit()

        # Assert: Job was reaped
        assert len(reaped) >= 1, "Reaper should have found the stuck job"
        reaped_job = next((r for r in reaped if r["job_id"] == job_id), None)
        assert reaped_job is not None, "Our test job should be in reaped results"
        assert reaped_job["action_taken"] == "recovered", (
            f"Expected 'recovered', got '{reaped_job['action_taken']}'"
        )

        # Verify job is now pending with backoff
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, next_run_at, last_error, reap_count
                    FROM ops.job_queue WHERE id = %s
                """,
                    (job_id,),
                )
                job = cur.fetchone()

        assert job["status"] == "pending", f"Expected 'pending', got '{job['status']}'"
        assert job["next_run_at"] is not None, "Backoff should set next_run_at"
        assert job["reap_count"] >= 1, "reap_count should be incremented"
        assert "[RECOVERED]" in (job["last_error"] or ""), (
            f"last_error should contain recovery message: {job['last_error']}"
        )

        # Cleanup
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                conn.commit()

    def test_reaper_moves_exhausted_job_to_dlq(self):
        """
        Insert a job with attempts >= max_attempts.
        Run reap_stuck_jobs. Assert it moves to 'failed' (DLQ).
        """
        job_id = None

        with get_connection() as conn:
            with conn.cursor() as cur:
                # Insert job with attempts >= max_attempts (exhausted)
                cur.execute(
                    """
                    INSERT INTO ops.job_queue (
                        job_type, payload, status, attempts, max_attempts,
                        started_at, worker_id, idempotency_key
                    )
                    VALUES (
                        'enrich_idicore',
                        '{"test": true}'::jsonb,
                        'processing',
                        3,
                        3,
                        NOW() - INTERVAL '1 hour',
                        'stuck-worker-dlq',
                        %s
                    )
                    RETURNING id
                """,
                    (f"reaper-dlq-{uuid.uuid4()}",),
                )
                job_id = cur.fetchone()["id"]
                conn.commit()

                # Run the reaper
                cur.execute("SELECT * FROM ops.reap_stuck_jobs(30)")
                reaped = cur.fetchall()
                conn.commit()

        # Assert: Job was moved to DLQ
        reaped_job = next((r for r in reaped if r["job_id"] == job_id), None)
        assert reaped_job is not None, "Our test job should be in reaped results"
        assert reaped_job["action_taken"] == "dlq", (
            f"Expected 'dlq', got '{reaped_job['action_taken']}'"
        )

        # Verify job is now failed
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, last_error, reap_count
                    FROM ops.job_queue WHERE id = %s
                """,
                    (job_id,),
                )
                job = cur.fetchone()

        assert job["status"] == "failed", f"Expected 'failed', got '{job['status']}'"
        assert "[DLQ]" in (job["last_error"] or ""), (
            f"last_error should contain DLQ message: {job['last_error']}"
        )

        # Cleanup
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                conn.commit()

    def test_reaper_ignores_fresh_jobs(self):
        """
        Insert a job that started recently (within timeout).
        Reaper should NOT touch it.
        """
        job_id = None

        with get_connection() as conn:
            with conn.cursor() as cur:
                # Insert job that started 5 minutes ago (within 30 min timeout)
                cur.execute(
                    """
                    INSERT INTO ops.job_queue (
                        job_type, payload, status, attempts, max_attempts,
                        started_at, worker_id, idempotency_key
                    )
                    VALUES (
                        'enrich_idicore',
                        '{"test": true}'::jsonb,
                        'processing',
                        1,
                        3,
                        NOW() - INTERVAL '5 minutes',
                        'active-worker',
                        %s
                    )
                    RETURNING id
                """,
                    (f"fresh-job-{uuid.uuid4()}",),
                )
                job_id = cur.fetchone()["id"]
                conn.commit()

                # Run the reaper with 30 min timeout
                cur.execute("SELECT * FROM ops.reap_stuck_jobs(30)")
                reaped = cur.fetchall()
                conn.commit()

        # Assert: Fresh job was NOT reaped
        reaped_job = next((r for r in reaped if r["job_id"] == job_id), None)
        assert reaped_job is None, "Fresh job should NOT be reaped"

        # Verify job is still processing
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM ops.job_queue WHERE id = %s", (job_id,))
                job = cur.fetchone()

        assert job["status"] == "processing", "Fresh job should remain processing"

        # Cleanup
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                conn.commit()


class TestSacredIdempotency:
    """Test 3: Duplicate job submissions are prevented by unique constraint."""

    def test_duplicate_idempotency_key_raises_unique_violation(self):
        """
        Insert two jobs with the same job_type + idempotency_key.
        Assert the second one raises UniqueViolation.
        """
        idem_key = f"dup-test-{uuid.uuid4()}"
        job_id = None

        with get_connection() as conn:
            with conn.cursor() as cur:
                # First insert succeeds
                cur.execute(
                    """
                    INSERT INTO ops.job_queue (job_type, payload, status, idempotency_key)
                    VALUES ('enrich_idicore', '{"n": 1}'::jsonb, 'pending', %s)
                    RETURNING id
                """,
                    (idem_key,),
                )
                job_id = cur.fetchone()["id"]
                conn.commit()

                # Second insert with SAME idempotency_key should fail
                with pytest.raises(psycopg.errors.UniqueViolation):
                    cur.execute(
                        """
                        INSERT INTO ops.job_queue (job_type, payload, status, idempotency_key)
                        VALUES ('enrich_idicore', '{"n": 2}'::jsonb, 'pending', %s)
                    """,
                        (idem_key,),
                    )

        # Cleanup
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                conn.commit()

    def test_same_key_different_job_type_allowed(self):
        """
        Same idempotency_key with DIFFERENT job_types should succeed.
        """
        idem_key = f"cross-type-{uuid.uuid4()}"
        job_ids = []

        with get_connection() as conn:
            with conn.cursor() as cur:
                # Insert with job_type = enrich_idicore
                cur.execute(
                    """
                    INSERT INTO ops.job_queue (job_type, payload, status, idempotency_key)
                    VALUES ('enrich_idicore', '{"type": "idicore"}'::jsonb, 'pending', %s)
                    RETURNING id
                """,
                    (idem_key,),
                )
                job_ids.append(cur.fetchone()["id"])

                # Insert with job_type = enrich_tlo (SAME key, different type) - should succeed
                cur.execute(
                    """
                    INSERT INTO ops.job_queue (job_type, payload, status, idempotency_key)
                    VALUES ('enrich_tlo', '{"type": "tlo"}'::jsonb, 'pending', %s)
                    RETURNING id
                """,
                    (idem_key,),
                )
                job_ids.append(cur.fetchone()["id"])
                conn.commit()

        assert len(job_ids) == 2, "Both inserts should succeed"

        # Cleanup
        with get_connection() as conn:
            with conn.cursor() as cur:
                for jid in job_ids:
                    cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (jid,))
                conn.commit()

    def test_queue_job_idempotent_returns_existing_id(self):
        """
        Test the ops.queue_job_idempotent RPC returns existing job_id for duplicates.
        """
        idem_key = f"idem-rpc-{uuid.uuid4()}"

        with get_connection() as conn:
            with conn.cursor() as cur:
                # First call: creates new job
                cur.execute(
                    """
                    SELECT ops.queue_job_idempotent(
                        'enrich_idicore',
                        '{"call": 1}'::jsonb,
                        %s
                    ) AS job_id
                """,
                    (idem_key,),
                )
                first_id = cur.fetchone()["job_id"]
                conn.commit()

                # Second call with SAME key: should return existing ID
                cur.execute(
                    """
                    SELECT ops.queue_job_idempotent(
                        'enrich_idicore',
                        '{"call": 2}'::jsonb,
                        %s
                    ) AS job_id
                """,
                    (idem_key,),
                )
                second_id = cur.fetchone()["job_id"]
                conn.commit()

        assert first_id == second_id, (
            f"Idempotent RPC should return same ID: {first_id} != {second_id}"
        )

        # Cleanup
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (first_id,))
                conn.commit()


class TestExponentialBackoff:
    """Verify exponential backoff formula: 2^attempts * 30s (capped at 3600s)."""

    @pytest.mark.parametrize(
        "attempts,expected_seconds",
        [
            (0, 30),  # 2^0 * 30 = 30
            (1, 60),  # 2^1 * 30 = 60
            (2, 120),  # 2^2 * 30 = 120
            (3, 240),  # 2^3 * 30 = 240
            (4, 480),  # 2^4 * 30 = 480
            (5, 960),  # 2^5 * 30 = 960
            (6, 1920),  # 2^6 * 30 = 1920
            (7, 3600),  # 2^7 * 30 = 3840 -> capped at 3600
            (8, 3600),  # Capped at 3600 (must be < max_attempts=10 to get backoff)
        ],
    )
    def test_backoff_formula(self, attempts: int, expected_seconds: int):
        """Verify backoff calculation is correct."""
        job_id = None

        with get_connection() as conn:
            with conn.cursor() as cur:
                # Insert stuck job with specific attempt count
                # max_attempts=10 so attempts < 10 will get backoff, not DLQ
                cur.execute(
                    """
                    INSERT INTO ops.job_queue (
                        job_type, payload, status, attempts, max_attempts,
                        started_at, worker_id, idempotency_key
                    )
                    VALUES (
                        'enrich_idicore',
                        '{"test": true}'::jsonb,
                        'processing',
                        %s,
                        10,
                        NOW() - INTERVAL '1 hour',
                        'backoff-worker',
                        %s
                    )
                    RETURNING id
                """,
                    (attempts, f"backoff-{attempts}-{uuid.uuid4()}"),
                )
                job_id = cur.fetchone()["id"]
                conn.commit()

                # Run reaper
                cur.execute("SELECT * FROM ops.reap_stuck_jobs(30)")
                conn.commit()

                # Check next_run_at
                cur.execute(
                    """
                    SELECT
                        EXTRACT(EPOCH FROM (next_run_at - NOW()))::integer AS backoff_secs
                    FROM ops.job_queue WHERE id = %s
                """,
                    (job_id,),
                )
                result = cur.fetchone()

        # Allow 5 second tolerance for timing
        actual = result["backoff_secs"]
        assert abs(actual - expected_seconds) < 5, (
            f"Backoff at attempt {attempts}: expected ~{expected_seconds}s, got {actual}s"
        )

        # Cleanup
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE id = %s", (job_id,))
                conn.commit()
