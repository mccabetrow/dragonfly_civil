# tools/verify_worker_startup.py
"""
Worker Startup Verifier - Confirms workers are alive after deployment.

This script polls ops.worker_heartbeats for fresh heartbeats that occurred
AFTER the deployment started, confirming workers actually booted and are
processing jobs.

Usage:
    python -m tools.verify_worker_startup
    python -m tools.verify_worker_startup --timeout 120 --min-workers 2
    python -m tools.verify_worker_startup --mode prod

Exit Codes:
    0 - Workers healthy (heartbeats detected)
    1 - Workers failed to heartbeat within timeout
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
from datetime import datetime, timezone
from typing import NamedTuple

# Fix Windows console encoding for Unicode (emoji) output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


class WorkerStatus(NamedTuple):
    """Status of worker verification."""

    worker_count: int
    worker_ids: list[str]
    oldest_heartbeat: datetime | None
    newest_heartbeat: datetime | None


def get_db_connection():
    """Get database connection using SUPABASE_MIGRATE_DB_URL (direct connection)."""
    import psycopg

    # Use migration URL for direct DB access (bypasses pooler issues)
    db_url = os.environ.get("SUPABASE_MIGRATE_DB_URL")
    if not db_url:
        # Fallback to runtime URL
        db_url = os.environ.get("SUPABASE_DB_URL")

    if not db_url:
        raise RuntimeError("No database URL found. Set SUPABASE_MIGRATE_DB_URL or SUPABASE_DB_URL")

    return psycopg.connect(db_url, connect_timeout=15)


def check_worker_heartbeats(since: datetime) -> WorkerStatus:
    """
    Check for worker heartbeats that occurred after the given timestamp.

    Args:
        since: Only count heartbeats after this timestamp

    Returns:
        WorkerStatus with count and details of active workers
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # First check if the table exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_tables 
                        WHERE schemaname = 'ops' 
                        AND tablename = 'worker_heartbeats'
                    )
                """
                )
                table_exists = cur.fetchone()[0]

                if not table_exists:
                    return WorkerStatus(
                        worker_count=0,
                        worker_ids=[],
                        oldest_heartbeat=None,
                        newest_heartbeat=None,
                    )

                # Query for workers with heartbeats after our start time
                # Column is 'last_seen_at' per 20251215100000_worker_heartbeats.sql
                cur.execute(
                    """
                    SELECT 
                        worker_id,
                        last_seen_at,
                        worker_type,
                        status
                    FROM ops.worker_heartbeats 
                    WHERE last_seen_at > %s
                    ORDER BY last_seen_at DESC
                """,
                    (since,),
                )
                rows = cur.fetchall()

                if not rows:
                    return WorkerStatus(
                        worker_count=0,
                        worker_ids=[],
                        oldest_heartbeat=None,
                        newest_heartbeat=None,
                    )

                worker_ids = [row[0] for row in rows]
                heartbeats = [row[1] for row in rows]

                return WorkerStatus(
                    worker_count=len(rows),
                    worker_ids=worker_ids,
                    oldest_heartbeat=min(heartbeats),
                    newest_heartbeat=max(heartbeats),
                )

    except Exception as e:
        print(f"  ⚠️  Database error: {e}")
        return WorkerStatus(
            worker_count=0,
            worker_ids=[],
            oldest_heartbeat=None,
            newest_heartbeat=None,
        )


def verify_workers(
    timeout_seconds: int = 90,
    poll_interval: int = 5,
    min_workers: int = 1,
    verbose: bool = False,
) -> bool:
    """
    Poll for worker heartbeats until timeout or success.

    Args:
        timeout_seconds: Maximum time to wait for workers
        poll_interval: Seconds between checks
        min_workers: Minimum number of workers required
        verbose: Print detailed status on each poll

    Returns:
        True if workers are healthy, False if timeout
    """
    start_time = datetime.now(timezone.utc)
    deadline = start_time.timestamp() + timeout_seconds
    attempt = 0

    print(f"\n  Start time: {start_time.strftime('%H:%M:%S UTC')}")
    print(
        f"  Timeout: {timeout_seconds}s | Poll interval: {poll_interval}s | Min workers: {min_workers}"
    )
    print()

    while time.time() < deadline:
        attempt += 1
        elapsed = int(time.time() - start_time.timestamp())
        remaining = timeout_seconds - elapsed

        status = check_worker_heartbeats(since=start_time)

        if status.worker_count >= min_workers:
            print(f"  [{elapsed}s] ✅ {status.worker_count} worker(s) detected!")
            if verbose and status.worker_ids:
                for wid in status.worker_ids[:5]:  # Show first 5
                    print(f"       - {wid}")
            return True

        # Progress indicator
        if verbose or attempt == 1 or attempt % 3 == 0:
            print(
                f"  [{elapsed}s] ⏳ Waiting... ({status.worker_count}/{min_workers} workers, {remaining}s remaining)"
            )

        time.sleep(poll_interval)

    # Timeout reached
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Worker Startup Verifier - Confirms workers are alive after deployment"
    )
    parser.add_argument(
        "--mode",
        choices=["dev", "prod"],
        default="prod",
        help="Environment mode (default: prod)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=90,
        help="Timeout in seconds (default: 90)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=5,
        help="Poll interval in seconds (default: 5)",
    )
    parser.add_argument(
        "--min-workers",
        type=int,
        default=1,
        help="Minimum number of workers required (default: 1)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output on each poll",
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print(f"  WORKER STARTUP VERIFICATION ({args.mode.upper()})")
    print("=" * 60)

    success = verify_workers(
        timeout_seconds=args.timeout,
        poll_interval=args.poll_interval,
        min_workers=args.min_workers,
        verbose=args.verbose,
    )

    print()
    print("=" * 60)
    if success:
        print("  ✅ WORKERS HEALTHY - Heartbeats detected after deployment")
        print("=" * 60)
        sys.exit(0)
    else:
        print("  ❌ FATAL: Workers failed to heartbeat after deployment")
        print("=" * 60)
        print()
        print("  Troubleshooting:")
        print("    1. Check Railway logs: railway logs --service dragonfly-workers")
        print("    2. Verify SUPABASE_DB_URL is set in Railway")
        print("    3. Check for Python/dependency errors in worker startup")
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()
