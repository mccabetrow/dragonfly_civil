"""
Dragonfly DLQ Replayer - Resurrect Failed Jobs from Dead Letter Queue

Provides operational tools to recover from transient failures:
- Inspect failed jobs in the DLQ
- Filter by original target queue
- Dry-run mode to preview without changes
- Re-inject messages back to their original queues
- Clean up DLQ after successful replay

Usage:
    python -m tools.replay_dlq --dry-run                     # Preview all DLQ messages
    python -m tools.replay_dlq --queue q_ingest_raw          # Replay ingest failures
    python -m tools.replay_dlq --queue q_enrich_skiptrace    # Replay skiptrace failures
    python -m tools.replay_dlq --limit 10                    # Replay max 10 messages
    python -m tools.replay_dlq --env prod --dry-run          # Check prod DLQ

Exit Codes:
    0 - Success
    1 - Database connection failed
    2 - Replay failed
    3 - No messages to replay
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

import click
import psycopg
from psycopg.rows import dict_row

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.supabase_client import get_supabase_db_url, get_supabase_env

# Exit codes
EXIT_OK = 0
EXIT_DB_ERROR = 1
EXIT_REPLAY_ERROR = 2
EXIT_NO_MESSAGES = 3

# DLQ queue name (must match 20260110000000_queue_topology.sql)
DLQ_QUEUE = "q_dead_letter"

# Valid target queues for replay
VALID_TARGET_QUEUES = [
    "q_ingest_raw",
    "q_enrich_skiptrace",
    "q_score_collectability",
    "q_monitoring_recheck",
    "q_comms_outbound",
]


@dataclass
class DLQMessage:
    """A message from the Dead Letter Queue."""

    msg_id: int
    enqueued_at: datetime
    vt: datetime  # visibility timeout
    message: dict
    read_ct: int

    # Extracted from message payload
    original_queue: Optional[str] = None
    original_job_id: Optional[int] = None
    error_message: Optional[str] = None
    attempt_count: int = 0

    def __post_init__(self):
        """Extract DLQ metadata from message payload."""
        if isinstance(self.message, dict):
            self.original_queue = self.message.get("original_queue")
            self.original_job_id = self.message.get("original_job_id")
            self.error_message = self.message.get("error_message")
            self.attempt_count = self.message.get("attempt_count", 0)


def connect_db(dsn: str) -> psycopg.Connection:
    """Establish database connection."""
    return psycopg.connect(dsn, row_factory=dict_row)


def fetch_dlq_messages(
    conn: psycopg.Connection,
    target_queue: Optional[str],
    limit: int,
) -> list[DLQMessage]:
    """
    Fetch messages from the Dead Letter Queue.

    Args:
        conn: Database connection
        target_queue: Filter by original queue (None = all)
        limit: Maximum messages to return
    """
    # Read messages from DLQ (don't mark as invisible - we want inspection)
    # We read with vt=0 to get all messages including those being processed
    query = f"""
        SELECT msg_id, enqueued_at, vt, message, read_ct
        FROM pgmq.q_{DLQ_QUEUE}
        ORDER BY enqueued_at ASC
        LIMIT %s
    """

    rows = conn.execute(query, [limit * 5]).fetchall()  # Over-fetch to filter

    messages = []
    for row in rows:
        msg = DLQMessage(
            msg_id=row["msg_id"],
            enqueued_at=row["enqueued_at"],
            vt=row["vt"],
            message=row["message"] if isinstance(row["message"], dict) else {},
            read_ct=row["read_ct"],
        )

        # Filter by target queue if specified
        if target_queue:
            if msg.original_queue == target_queue:
                messages.append(msg)
        else:
            messages.append(msg)

        if len(messages) >= limit:
            break

    return messages


def print_dlq_summary(messages: list[DLQMessage], target_queue: Optional[str]) -> None:
    """Print summary of DLQ messages."""
    click.echo()
    click.echo(f"{'=' * 80}")
    click.echo("  DEAD LETTER QUEUE INSPECTION")
    if target_queue:
        click.echo(f"  Filter: {target_queue}")
    click.echo(f"  Found: {len(messages)} message(s)")
    click.echo(f"{'=' * 80}")
    click.echo()

    if not messages:
        click.secho("  ✅ Dead Letter Queue is empty!", fg="green")
        return

    # Group by original queue
    by_queue: dict[str, list[DLQMessage]] = {}
    for m in messages:
        queue = m.original_queue or "unknown"
        by_queue.setdefault(queue, []).append(m)

    for queue, msgs in by_queue.items():
        click.echo(f"  📦 {queue}: {len(msgs)} message(s)")

    click.echo()
    click.echo("-" * 80)

    # Detail view
    header = f"{'MsgID':<10} {'Original Queue':<26} {'Age':<12} {'Attempts':<10} {'Error':<20}"
    click.echo(header)
    click.echo("-" * 80)

    now = datetime.now(timezone.utc)
    for m in messages:
        age = now - m.enqueued_at.replace(tzinfo=timezone.utc)
        age_str = format_age(age.total_seconds())
        error_preview = (
            (m.error_message or "-")[:18] + "..."
            if m.error_message and len(m.error_message) > 20
            else (m.error_message or "-")
        )

        row = (
            f"{m.msg_id:<10} "
            f"{m.original_queue or 'unknown':<26} "
            f"{age_str:<12} "
            f"{m.attempt_count:<10} "
            f"{error_preview:<20}"
        )
        click.echo(row)

    click.echo("-" * 80)
    click.echo()


def format_age(seconds: float) -> str:
    """Format age in human-readable form."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m"
    elif seconds < 86400:
        return f"{int(seconds / 3600)}h"
    else:
        return f"{int(seconds / 86400)}d"


def replay_message(
    conn: psycopg.Connection,
    msg: DLQMessage,
    dry_run: bool,
) -> bool:
    """
    Replay a single message from DLQ back to its original queue.

    Args:
        conn: Database connection
        msg: DLQ message to replay
        dry_run: If True, only preview without changes

    Returns:
        True if replayed successfully
    """
    if not msg.original_queue:
        click.secho(f"  ⚠️  MsgID {msg.msg_id}: No original_queue in payload, skipping", fg="yellow")
        return False

    if msg.original_queue not in VALID_TARGET_QUEUES:
        click.secho(
            f"  ⚠️  MsgID {msg.msg_id}: Invalid target queue '{msg.original_queue}', skipping",
            fg="yellow",
        )
        return False

    if dry_run:
        click.echo(f"  [DRY-RUN] Would replay MsgID {msg.msg_id} → {msg.original_queue}")
        return True

    try:
        # Extract original payload (remove DLQ metadata)
        original_payload = msg.message.get("original_payload", msg.message)

        # Remove DLQ-specific fields from payload to prevent recursion
        replay_payload = {
            k: v
            for k, v in original_payload.items()
            if k
            not in (
                "original_queue",
                "original_job_id",
                "error_message",
                "attempt_count",
                "moved_to_dlq_at",
            )
        }

        # Add replay metadata
        replay_payload["_replayed_from_dlq"] = True
        replay_payload["_dlq_msg_id"] = msg.msg_id
        replay_payload["_replay_timestamp"] = datetime.now(timezone.utc).isoformat()

        with conn.transaction():
            # 1. Send to original queue using pgmq.send()
            result = conn.execute(
                "SELECT pgmq.send(%s, %s::jsonb) AS new_msg_id",
                [msg.original_queue, json.dumps(replay_payload)],
            ).fetchone()

            new_msg_id = result["new_msg_id"] if result else None

            # 2. Delete from DLQ using pgmq.delete()
            conn.execute(
                "SELECT pgmq.delete(%s, %s)",
                [DLQ_QUEUE, msg.msg_id],
            )

            # 3. Update dead_letter_log if entry exists
            conn.execute(
                """
                UPDATE workers.dead_letter_log
                SET resolved_at = NOW(),
                    resolution_notes = %s
                WHERE original_job_id = %s
                  AND original_queue = %s
                  AND resolved_at IS NULL
                """,
                [
                    f"Replayed via replay_dlq tool at {datetime.now(timezone.utc).isoformat()}. New msg_id: {new_msg_id}",
                    msg.original_job_id or msg.msg_id,
                    msg.original_queue,
                ],
            )

        click.secho(
            f"  ✅ MsgID {msg.msg_id} → {msg.original_queue} (new: {new_msg_id})",
            fg="green",
        )
        return True

    except Exception as e:
        click.secho(f"  ❌ MsgID {msg.msg_id}: Replay failed - {e}", fg="red")
        return False


@click.command()
@click.option(
    "--env",
    type=click.Choice(["dev", "prod"]),
    default=None,
    help="Target environment (default: auto-detect from SUPABASE_MODE)",
)
@click.option(
    "--queue",
    "target_queue",
    type=click.Choice(VALID_TARGET_QUEUES),
    default=None,
    help="Filter by original target queue",
)
@click.option(
    "--limit",
    type=int,
    default=100,
    help="Maximum messages to replay (default: 100)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Preview without making changes",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt",
)
def main(
    env: Optional[str],
    target_queue: Optional[str],
    limit: int,
    dry_run: bool,
    yes: bool,
) -> None:
    """
    Dragonfly DLQ Replayer - Resurrect failed jobs from Dead Letter Queue.

    Reads messages from q_dead_letter, filters by original target queue,
    and re-injects them back to their original queues for reprocessing.
    """
    # Determine environment
    if env:
        os.environ["SUPABASE_MODE"] = env
    target_env = env or get_supabase_env()

    if not dry_run:
        click.secho(
            f"\n⚠️  LIVE MODE - Replaying to {target_env.upper()} environment\n",
            fg="yellow",
            bold=True,
        )

    # Get database URL
    try:
        db_url = get_supabase_db_url()
    except Exception as e:
        click.secho(f"❌ Failed to get database URL: {e}", fg="red", err=True)
        sys.exit(EXIT_DB_ERROR)

    # Connect to database
    try:
        conn = connect_db(db_url)
    except Exception as e:
        click.secho(f"❌ Database connection failed: {e}", fg="red", err=True)
        sys.exit(EXIT_DB_ERROR)

    try:
        # Fetch DLQ messages
        messages = fetch_dlq_messages(conn, target_queue, limit)

        # Print summary
        print_dlq_summary(messages, target_queue)

        if not messages:
            sys.exit(EXIT_NO_MESSAGES)

        # Dry-run mode just shows the summary
        if dry_run:
            click.echo("  [DRY-RUN] No changes made. Remove --dry-run to replay.")
            click.echo()
            sys.exit(EXIT_OK)

        # Confirmation prompt
        if not yes:
            click.echo()
            confirmed = click.confirm(
                f"Replay {len(messages)} message(s) to their original queues?",
                default=False,
            )
            if not confirmed:
                click.echo("Aborted.")
                sys.exit(EXIT_OK)

        click.echo()
        click.echo("Replaying messages...")
        click.echo("-" * 40)

        # Replay each message
        success_count = 0
        fail_count = 0

        for msg in messages:
            if replay_message(conn, msg, dry_run):
                success_count += 1
            else:
                fail_count += 1

        click.echo("-" * 40)
        click.echo()
        click.secho(f"  ✅ Replayed: {success_count}", fg="green")
        if fail_count > 0:
            click.secho(f"  ❌ Failed:   {fail_count}", fg="red")
        click.echo()

        if fail_count > 0:
            sys.exit(EXIT_REPLAY_ERROR)

    except Exception as e:
        click.secho(f"❌ Replay failed: {e}", fg="red", err=True)
        sys.exit(EXIT_REPLAY_ERROR)
    finally:
        conn.close()

    sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
