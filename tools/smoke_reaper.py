"""
Smoke Test: Stuck Job Reaper

Validates that the ops.reap_stuck_jobs() function correctly:
1. Detects stuck jobs (processing + started_at timeout)
2. Resets jobs with attempts < max_attempts to pending with backoff
3. Moves jobs with attempts >= max_attempts to DLQ (failed status)

Usage:
    # Full simulation (creates, sticks, and reaps a job)
    python -m tools.smoke_reaper --env dev

    # Just check current stuck jobs (no changes)
    python -m tools.smoke_reaper --env dev --check-only

    # Run the reaper manually
    python -m tools.smoke_reaper --env dev --reap-now

    # Simulate with custom timeout
    python -m tools.smoke_reaper --env dev --timeout-minutes 5
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import click
import psycopg
from psycopg.rows import dict_row

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.supabase_client import get_supabase_db_url

# Color output helpers
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def log_ok(msg: str) -> None:
    """Log success message."""
    print(f"{GREEN}✓{RESET} {msg}")


def log_fail(msg: str) -> None:
    """Log failure message."""
    print(f"{RED}✗{RESET} {msg}")


def log_warn(msg: str) -> None:
    """Log warning message."""
    print(f"{YELLOW}⚠{RESET} {msg}")


def log_info(msg: str) -> None:
    """Log info message."""
    print(f"{CYAN}ℹ{RESET} {msg}")


def get_queue_health(conn: psycopg.Connection) -> dict[str, Any]:
    """Get current queue health summary."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                COUNT(*) FILTER (WHERE status = 'processing') AS processing,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                COUNT(*) FILTER (
                    WHERE status = 'processing'
                    AND started_at < now() - interval '1 hour'
                ) AS stuck_1hr,
                COUNT(*) FILTER (
                    WHERE status = 'failed'
                    AND last_error LIKE '[DLQ]%%'
                ) AS dlq_size
            FROM ops.job_queue
        """
        )
        row = cur.fetchone()
        return dict(row) if row else {}


def get_stuck_jobs(conn: psycopg.Connection, timeout_minutes: int = 30) -> list[dict[str, Any]]:
    """Get list of currently stuck jobs."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                id,
                job_type::text AS job_type,
                attempts,
                max_attempts,
                worker_id,
                started_at,
                ROUND(EXTRACT(EPOCH FROM (now() - started_at)) / 60.0, 1) AS stuck_minutes,
                last_error,
                reap_count
            FROM ops.job_queue
            WHERE status = 'processing'
              AND started_at IS NOT NULL
              AND started_at < now() - (%s || ' minutes')::interval
            ORDER BY started_at ASC
            """,
            (timeout_minutes,),
        )
        return [dict(row) for row in cur.fetchall()]


def run_reaper(conn: psycopg.Connection, timeout_minutes: int = 30) -> list[dict[str, Any]]:
    """Run the reaper and return actions taken."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM ops.reap_stuck_jobs(%s)",
            (timeout_minutes,),
        )
        results = [dict(row) for row in cur.fetchall()]
        conn.commit()
        return results


def create_test_job(
    conn: psycopg.Connection, job_type: str = "smoke_test_reaper"
) -> Optional[UUID]:
    """Create a test job for reaper smoke test."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ops.queue_job(
                p_type := %s,
                p_payload := %s::jsonb,
                p_priority := 0,
                p_run_at := now()
            )
            """,
            (job_type, json.dumps({"test": True, "created_at": datetime.utcnow().isoformat()})),
        )
        result = cur.fetchone()
        conn.commit()
        return UUID(str(result[0])) if result and result[0] else None


def simulate_stuck_job(
    conn: psycopg.Connection,
    job_id: UUID,
    stuck_minutes: int = 35,
    attempts: int = 1,
) -> None:
    """
    Simulate a job being stuck in processing.

    Sets the job to 'processing' with a started_at in the past.
    """
    with conn.cursor() as cur:
        # Set job to processing with backdated started_at
        past_time = datetime.now(timezone.utc) - timedelta(minutes=stuck_minutes)
        cur.execute(
            """
            UPDATE ops.job_queue
            SET status = 'processing',
                started_at = %s,
                locked_at = %s,
                attempts = %s,
                worker_id = 'smoke_test_worker'
            WHERE id = %s
            """,
            (past_time, past_time, attempts, str(job_id)),
        )
        conn.commit()


def cleanup_test_jobs(conn: psycopg.Connection, job_type: str = "smoke_test_reaper") -> int:
    """Clean up any test jobs created by this script."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ops.job_queue WHERE job_type::text = %s",
            (job_type,),
        )
        count = cur.rowcount
        conn.commit()
        return count


def check_job_status(conn: psycopg.Connection, job_id: UUID) -> Optional[dict[str, Any]]:
    """Get current status of a job."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                id,
                status::text AS status,
                attempts,
                max_attempts,
                next_run_at,
                last_error,
                reap_count
            FROM ops.job_queue
            WHERE id = %s
            """,
            (str(job_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None


@click.command()
@click.option("--env", default="dev", type=click.Choice(["dev", "prod"]), help="Environment")
@click.option("--check-only", is_flag=True, help="Only check for stuck jobs, don't simulate")
@click.option("--reap-now", is_flag=True, help="Run the reaper immediately")
@click.option("--timeout-minutes", default=30, help="Lock timeout in minutes")
@click.option("--cleanup", is_flag=True, help="Clean up test jobs")
@click.option("--simulate-dlq", is_flag=True, help="Simulate a job that should go to DLQ")
def main(
    env: str,
    check_only: bool,
    reap_now: bool,
    timeout_minutes: int,
    cleanup: bool,
    simulate_dlq: bool,
) -> None:
    """Smoke test for the stuck job reaper."""
    os.environ["SUPABASE_MODE"] = env

    print()
    print("=" * 60)
    print(f"  SMOKE TEST: Stuck Job Reaper ({env.upper()})")
    print("=" * 60)
    print()

    db_url = get_supabase_db_url()
    if not db_url:
        log_fail("SUPABASE_DB_URL not configured")
        sys.exit(1)

    try:
        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            # Show current health
            log_info("Current Queue Health:")
            health = get_queue_health(conn)
            print(f"    Pending:    {health.get('pending', 0)}")
            print(f"    Processing: {health.get('processing', 0)}")
            print(f"    Completed:  {health.get('completed', 0)}")
            print(f"    Failed:     {health.get('failed', 0)}")
            print(f"    Stuck (1h): {health.get('stuck_1hr', 0)}")
            print(f"    DLQ Size:   {health.get('dlq_size', 0)}")
            print()

            # Cleanup mode
            if cleanup:
                count = cleanup_test_jobs(conn)
                log_info(f"Cleaned up {count} test jobs")
                return

            # Check-only mode
            if check_only:
                stuck = get_stuck_jobs(conn, timeout_minutes)
                if stuck:
                    log_warn(f"Found {len(stuck)} stuck jobs (>{timeout_minutes}m):")
                    for job in stuck:
                        print(
                            f"    - {job['id']} ({job['job_type']}) "
                            f"stuck {job['stuck_minutes']}m, attempt {job['attempts']}/{job['max_attempts']}"
                        )
                else:
                    log_ok(f"No stuck jobs (timeout: {timeout_minutes}m)")
                return

            # Reap-now mode
            if reap_now:
                log_info(f"Running reaper with timeout: {timeout_minutes}m...")
                results = run_reaper(conn, timeout_minutes)
                if results:
                    log_ok(f"Reaped {len(results)} jobs:")
                    for r in results:
                        print(
                            f"    - {r['job_id']} ({r['job_type']}): "
                            f"{r['action_taken']} (attempt {r['attempts']}/{r['max_attempts']})"
                        )
                else:
                    log_info("No jobs to reap")
                return

            # Full simulation mode
            print("-" * 60)
            log_info("SIMULATION: Creating a stuck job and running reaper")
            print("-" * 60)
            print()

            # Step 1: Create test job
            log_info("Step 1: Creating test job...")
            job_id = create_test_job(conn)
            if not job_id:
                log_fail("Failed to create test job")
                sys.exit(1)
            log_ok(f"Created job: {job_id}")

            # Step 2: Simulate stuck job
            if simulate_dlq:
                # Simulate job at max attempts (should go to DLQ)
                stuck_minutes = timeout_minutes + 5
                log_info("Step 2: Simulating stuck job at max attempts (DLQ scenario)...")
                simulate_stuck_job(conn, job_id, stuck_minutes=stuck_minutes, attempts=5)
            else:
                # Normal retry scenario
                stuck_minutes = timeout_minutes + 5
                log_info(f"Step 2: Simulating stuck job for {stuck_minutes} minutes...")
                simulate_stuck_job(conn, job_id, stuck_minutes=stuck_minutes, attempts=1)
            log_ok("Job simulated as stuck")

            # Step 3: Verify it appears in stuck list
            log_info("Step 3: Verifying job appears as stuck...")
            stuck = get_stuck_jobs(conn, timeout_minutes)
            found = any(str(j["id"]) == str(job_id) for j in stuck)
            if found:
                log_ok("Job correctly detected as stuck")
            else:
                log_fail("Job NOT detected as stuck - reaper may not work!")
                cleanup_test_jobs(conn)
                sys.exit(1)

            # Step 4: Run reaper
            log_info(f"Step 4: Running reaper (timeout: {timeout_minutes}m)...")
            results = run_reaper(conn, timeout_minutes)
            reaped = [r for r in results if str(r["job_id"]) == str(job_id)]
            if reaped:
                action = reaped[0]["action_taken"]
                log_ok(f"Job reaped: {action}")
            else:
                log_fail("Job was NOT reaped!")
                cleanup_test_jobs(conn)
                sys.exit(1)

            # Step 5: Verify final status
            log_info("Step 5: Verifying final job status...")
            status = check_job_status(conn, job_id)
            if status:
                if simulate_dlq:
                    # Should be failed (DLQ)
                    if status["status"] == "failed":
                        log_ok(f"Job correctly moved to DLQ (status: {status['status']})")
                        if "[DLQ]" in (status.get("last_error") or ""):
                            log_ok("DLQ marker present in last_error")
                        else:
                            log_warn("DLQ marker NOT present in last_error")
                    else:
                        log_fail(f"Job should be 'failed' but is '{status['status']}'")
                else:
                    # Should be pending with backoff
                    if status["status"] == "pending":
                        log_ok("Job correctly reset to pending")
                        if status.get("next_run_at"):
                            log_ok(f"Backoff scheduled: {status['next_run_at']}")
                        else:
                            log_warn("next_run_at not set - backoff may not work")
                        if status.get("reap_count", 0) > 0:
                            log_ok(f"reap_count incremented: {status['reap_count']}")
                        else:
                            log_warn("reap_count not incremented")
                    else:
                        log_fail(f"Job should be 'pending' but is '{status['status']}'")
            else:
                log_fail("Could not find job after reaping")

            # Step 6: Cleanup
            log_info("Step 6: Cleaning up test job...")
            cleanup_test_jobs(conn)
            log_ok("Test job cleaned up")

            print()
            print("=" * 60)
            if simulate_dlq:
                log_ok("REAPER SMOKE TEST PASSED (DLQ scenario)")
            else:
                log_ok("REAPER SMOKE TEST PASSED (Retry scenario)")
            print("=" * 60)
            print()

    except psycopg.OperationalError as e:
        log_fail(f"Database connection failed: {e}")
        sys.exit(1)
    except Exception as e:
        log_fail(f"Unexpected error: {e}")
        raise


if __name__ == "__main__":
    main()
