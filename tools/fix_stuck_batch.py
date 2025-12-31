#!/usr/bin/env python3
"""
tools/fix_stuck_batch.py - Batch Unsticker

Detects and resolves stuck batches in the Simplicity pipeline.
A batch is considered "stuck" if it has been in 'processing' status > 30 minutes.

Usage:
    python -m tools.fix_stuck_batch                     # Auto-detect stuck batches
    python -m tools.fix_stuck_batch --batch-id UUID     # Fix specific batch
    python -m tools.fix_stuck_batch --action retry      # Reset to 'uploaded' for retry
    python -m tools.fix_stuck_batch --action abort      # Mark as 'failed'
    python -m tools.fix_stuck_batch --env prod --dry-run

Failure Mode: Batch Stuck in Processing
Resolution: Reset to 'uploaded' (retry) or 'failed' (abort)
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import psycopg

if TYPE_CHECKING:
    from psycopg import Connection

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STUCK_THRESHOLD_MINUTES = 30
VALID_ACTIONS = ["retry", "abort"]

# ---------------------------------------------------------------------------
# Environment Setup
# ---------------------------------------------------------------------------


def get_config(env: str) -> dict[str, str]:
    """Load configuration for the specified environment."""
    os.environ["SUPABASE_MODE"] = env

    from src.supabase_client import get_supabase_db_url, get_supabase_env

    return {
        "env": get_supabase_env(),
        "db_url": get_supabase_db_url(),
    }


def find_stuck_batches(
    conn: Connection, threshold_minutes: int = STUCK_THRESHOLD_MINUTES
) -> list[dict]:
    """
    Find batches stuck in 'processing' status beyond threshold.

    Returns list of dicts with batch info.
    """
    threshold = datetime.now(timezone.utc) - timedelta(minutes=threshold_minutes)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 
                id,
                filename,
                status,
                row_count_total,
                created_at,
                COALESCE(staged_at, transformed_at, created_at) as updated_at,
                EXTRACT(EPOCH FROM (NOW() - COALESCE(staged_at, transformed_at, created_at))) / 60 as minutes_stuck
            FROM intake.simplicity_batches
            WHERE status IN ('processing', 'staging', 'transforming')
              AND COALESCE(staged_at, transformed_at, created_at) < %s
            ORDER BY created_at ASC
            """,
            (threshold,),
        )

        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_batch_info(conn: Connection, batch_id: str) -> dict | None:
    """Get detailed info for a specific batch."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 
                id,
                filename,
                file_hash,
                status,
                row_count_total,
                row_count_invalid,
                rejection_reason,
                created_at,
                COALESCE(completed_at, staged_at, transformed_at, created_at) as updated_at,
                EXTRACT(EPOCH FROM (NOW() - COALESCE(completed_at, staged_at, created_at))) / 60 as minutes_since_update
            FROM intake.simplicity_batches
            WHERE id = %s
            """,
            (batch_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row))


def write_audit_log(
    conn: Connection, batch_id: str, action: str, old_status: str, new_status: str, reason: str
) -> None:
    """Write an audit log entry for batch status change."""
    with conn.cursor() as cur:
        # Check if ops.audit_log table exists
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'ops' AND table_name = 'audit_log'
            )
            """
        )
        table_exists = cur.fetchone()[0]

        if table_exists:
            cur.execute(
                """
                INSERT INTO ops.audit_log (entity_type, entity_id, action, old_value, new_value, reason, created_by)
                VALUES ('simplicity_batch', %s, %s, %s, %s, %s, 'fix_stuck_batch')
                """,
                (str(batch_id), action, old_status, new_status, reason),
            )
        else:
            # Log to console if audit table doesn't exist
            print(f"  📝 Audit (no table): {action} batch {batch_id}: {old_status} -> {new_status}")


def reset_batch_status(
    conn: Connection, batch_id: str, new_status: str, reason: str, dry_run: bool = False
) -> bool:
    """
    Reset batch status with audit logging.

    Args:
        conn: Database connection
        batch_id: Batch UUID
        new_status: 'uploaded' for retry, 'failed' for abort
        reason: Reason for the status change
        dry_run: If True, don't actually modify

    Returns:
        True if successful
    """
    batch = get_batch_info(conn, batch_id)
    if not batch:
        print(f"  ❌ Batch {batch_id} not found")
        return False

    old_status = batch["status"]

    if dry_run:
        print(f"  🔍 [DRY RUN] Would change: {old_status} -> {new_status}")
        return True

    with conn.cursor() as cur:
        # Write audit log first
        write_audit_log(conn, batch_id, f"unstick_{new_status}", old_status, new_status, reason)

        # Update the batch status
        if new_status == "failed":
            cur.execute(
                """
                UPDATE intake.simplicity_batches
                SET status = 'failed',
                    rejection_reason = %s,
                    completed_at = NOW()
                WHERE id = %s
                """,
                (reason, batch_id),
            )
        else:  # retry -> uploaded
            cur.execute(
                """
                UPDATE intake.simplicity_batches
                SET status = 'uploaded',
                    rejection_reason = NULL,
                    staged_at = NULL,
                    transformed_at = NULL,
                    completed_at = NULL
                WHERE id = %s
                """,
                (batch_id,),
            )

    conn.commit()
    return True


def format_batch_table(batches: list[dict]) -> str:
    """Format batch list as a table."""
    if not batches:
        return "  No stuck batches found."

    lines = []
    lines.append("  " + "-" * 90)
    lines.append(f"  {'ID':<38} {'File':<25} {'Status':<12} {'Stuck (min)':<12}")
    lines.append("  " + "-" * 90)

    for b in batches:
        batch_id = str(b["id"])[:36]
        filename = (b["filename"] or "unknown")[:24]
        status = b["status"]
        minutes = int(b.get("minutes_stuck", 0))
        lines.append(f"  {batch_id:<38} {filename:<25} {status:<12} {minutes:<12}")

    lines.append("  " + "-" * 90)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect and resolve stuck batches in the Simplicity pipeline"
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Target environment (default: dev)",
    )
    parser.add_argument(
        "--batch-id",
        type=str,
        help="Specific batch ID to fix (auto-detect if not provided)",
    )
    parser.add_argument(
        "--action",
        choices=VALID_ACTIONS,
        default="retry",
        help="Action: 'retry' (reset to uploaded) or 'abort' (mark failed)",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=STUCK_THRESHOLD_MINUTES,
        help=f"Minutes before considering a batch stuck (default: {STUCK_THRESHOLD_MINUTES})",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Fix all detected stuck batches (use with caution)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  BATCH UNSTICKER - Stuck Batch Resolution Tool")
    print("=" * 70)
    print(f"\n  Environment: {args.env.upper()}")
    print(f"  Action: {args.action.upper()}")
    print(f"  Threshold: {args.threshold} minutes")
    if args.dry_run:
        print("  Mode: DRY RUN (no changes)")
    print()

    # Load configuration
    try:
        config = get_config(args.env)
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        return 1

    # Connect to database
    try:
        conn = psycopg.connect(config["db_url"])
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return 1

    try:
        # Specific batch ID provided
        if args.batch_id:
            print("─" * 70)
            print(f"  Checking Batch: {args.batch_id}")
            print("─" * 70)

            # Validate UUID format
            try:
                uuid.UUID(args.batch_id)
            except ValueError:
                print(f"  ❌ Invalid UUID format: {args.batch_id}")
                return 1

            batch = get_batch_info(conn, args.batch_id)
            if not batch:
                print(f"  ❌ Batch not found: {args.batch_id}")
                return 1

            print(f"  File: {batch['filename']}")
            print(f"  Status: {batch['status']}")
            print(f"  Rows: {batch['row_count_total']}")
            print(f"  Minutes since update: {int(batch.get('minutes_since_update', 0))}")
            print()

            # Determine new status based on action
            new_status = "uploaded" if args.action == "retry" else "failed"
            reason = f"Manual unstick via fix_stuck_batch ({args.action})"

            success = reset_batch_status(conn, args.batch_id, new_status, reason, args.dry_run)

            if success and not args.dry_run:
                print(f"  ✅ Batch {args.action}d: {batch['status']} -> {new_status}")

            return 0 if success else 1

        # Auto-detect stuck batches
        print("─" * 70)
        print("  Auto-Detecting Stuck Batches")
        print("─" * 70)

        stuck_batches = find_stuck_batches(conn, args.threshold)

        print(format_batch_table(stuck_batches))
        print()

        if not stuck_batches:
            print("  ✅ No stuck batches detected - pipeline is healthy")
            return 0

        print(f"  Found {len(stuck_batches)} stuck batch(es)")
        print()

        # Fix all if --all flag
        if args.all:
            print("─" * 70)
            print(f"  Fixing All Stuck Batches ({args.action})")
            print("─" * 70)

            new_status = "uploaded" if args.action == "retry" else "failed"
            reason = f"Auto-unstick via fix_stuck_batch --all ({args.action})"

            success_count = 0
            for batch in stuck_batches:
                batch_id = str(batch["id"])
                print(f"  Processing {batch_id[:8]}...", end=" ")

                if reset_batch_status(conn, batch_id, new_status, reason, args.dry_run):
                    success_count += 1
                    print("✅")
                else:
                    print("❌")

            print()
            if args.dry_run:
                print(f"  🔍 [DRY RUN] Would fix {success_count}/{len(stuck_batches)} batches")
            else:
                print(f"  ✅ Fixed {success_count}/{len(stuck_batches)} batches")

            return 0 if success_count == len(stuck_batches) else 1

        # Interactive mode - show instructions
        print("─" * 70)
        print("  Next Steps")
        print("─" * 70)
        print()
        print("  To fix a specific batch:")
        print(f"    python -m tools.fix_stuck_batch --batch-id <UUID> --action {args.action}")
        print()
        print("  To fix all stuck batches:")
        print(f"    python -m tools.fix_stuck_batch --all --action {args.action}")
        print()
        print("  Actions:")
        print("    --action retry  : Reset to 'uploaded' for reprocessing")
        print("    --action abort  : Mark as 'failed' and skip")

        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
