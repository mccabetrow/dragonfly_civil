"""
Dragonfly Queue Inspector - Real-time Queue Depth Dashboard

Provides operational visibility into pgmq queue health:
- Queue depth monitoring (total messages)
- Age tracking (oldest message timestamp)
- Processing visibility (invisible message count)
- Worker status (online/offline based on heartbeats)
- Dead letter queue warnings

Usage:
    python -m tools.queue_inspect                # Default dashboard
    python -m tools.queue_inspect --env dev      # Target dev environment
    python -m tools.queue_inspect --env prod     # Target prod environment
    python -m tools.queue_inspect --json         # JSON output for alerting
    python -m tools.queue_inspect --watch        # Continuous refresh (5s)

Exit Codes:
    0 - Success
    1 - Database connection failed
    2 - Query execution failed
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import click
import psycopg
from psycopg.rows import dict_row

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.supabase_client import get_supabase_db_url, get_supabase_env

# Exit codes
EXIT_OK = 0
EXIT_DB_ERROR = 1
EXIT_QUERY_ERROR = 2

# Queue topology (must match 20260110000000_queue_topology.sql)
QUEUE_NAMES = [
    "q_ingest_raw",
    "q_enrich_skiptrace",
    "q_score_collectability",
    "q_monitoring_recheck",
    "q_comms_outbound",
    "q_dead_letter",
]

# DLQ alert threshold
DLQ_WARNING_THRESHOLD = 10

# Worker status thresholds
WORKER_STALE_THRESHOLD_MINUTES = 5


@dataclass
class WorkerStatus:
    """Status of workers for a queue."""

    active_count: int
    last_heartbeat: Optional[datetime]
    status: str  # "online", "offline", "stale"

    @property
    def status_display(self) -> str:
        """Human-readable status."""
        if self.status == "online":
            return "🟢 Online"
        elif self.status == "stale":
            return "🟡 Stale"
        else:
            return "🔴 Offline"


@dataclass
class QueueMetrics:
    """Metrics for a single queue."""

    queue_name: str
    total_messages: int
    oldest_message_age_seconds: Optional[float]
    processing_count: int  # Messages currently invisible (being processed)
    newest_msg_id: Optional[int]
    queue_length: int
    scrape_time: datetime
    worker_status: Optional[WorkerStatus] = None
    last_success_at: Optional[datetime] = None

    @property
    def oldest_age_human(self) -> str:
        """Human-readable age of oldest message."""
        if self.oldest_message_age_seconds is None:
            return "-"
        age = self.oldest_message_age_seconds
        if age < 60:
            return f"{int(age)}s"
        elif age < 3600:
            return f"{int(age / 60)}m"
        elif age < 86400:
            return f"{int(age / 3600)}h"
        else:
            return f"{int(age / 86400)}d"

    @property
    def last_success_human(self) -> str:
        """Human-readable time since last success."""
        if self.last_success_at is None:
            return "-"
        now = datetime.now(timezone.utc)
        if self.last_success_at.tzinfo is None:
            last = self.last_success_at.replace(tzinfo=timezone.utc)
        else:
            last = self.last_success_at
        age = (now - last).total_seconds()
        if age < 60:
            return f"{int(age)}s ago"
        elif age < 3600:
            return f"{int(age / 60)}m ago"
        elif age < 86400:
            return f"{int(age / 3600)}h ago"
        else:
            return f"{int(age / 86400)}d ago"


def connect_db(dsn: str) -> psycopg.Connection:
    """Establish database connection."""
    return psycopg.connect(dsn, row_factory=dict_row)


def fetch_worker_status_for_queue(
    conn: psycopg.Connection,
    queue_name: str,
) -> Optional[WorkerStatus]:
    """Fetch worker status for a specific queue from workers.heartbeats."""
    try:
        # Count active workers (heartbeat within threshold, status healthy)
        result = conn.execute(
            """
            SELECT 
                COUNT(*) FILTER (
                    WHERE status = 'healthy' 
                    AND last_heartbeat_at > now() - INTERVAL '%s minutes'
                ) AS active_count,
                MAX(last_heartbeat_at) AS last_heartbeat
            FROM workers.heartbeats
            WHERE queue_name = %s
            """,
            [WORKER_STALE_THRESHOLD_MINUTES, queue_name],
        ).fetchone()

        if not result:
            return WorkerStatus(active_count=0, last_heartbeat=None, status="offline")

        active = result["active_count"] or 0
        last_hb = result["last_heartbeat"]

        # Determine status
        if active > 0:
            status = "online"
        elif last_hb:
            # Check if last heartbeat is stale
            now = datetime.now(timezone.utc)
            if last_hb.tzinfo is None:
                last_hb = last_hb.replace(tzinfo=timezone.utc)
            age_minutes = (now - last_hb).total_seconds() / 60
            if age_minutes > WORKER_STALE_THRESHOLD_MINUTES:
                status = "stale"
            else:
                status = "online"
        else:
            status = "offline"

        return WorkerStatus(
            active_count=active,
            last_heartbeat=last_hb,
            status=status,
        )

    except Exception:
        # Table might not exist or other error - return None
        return None


def fetch_queue_metrics_from_workers(
    conn: psycopg.Connection,
    queue_name: str,
) -> Optional[datetime]:
    """Fetch last_success_at from workers.metrics table."""
    try:
        result = conn.execute(
            "SELECT last_success_at FROM workers.metrics WHERE queue_name = %s",
            [queue_name],
        ).fetchone()
        return result["last_success_at"] if result else None
    except Exception:
        return None


def fetch_queue_metrics(conn: psycopg.Connection, queue_name: str) -> Optional[QueueMetrics]:
    """
    Fetch metrics for a single queue using pgmq.metrics().

    pgmq.metrics() returns:
        - queue_name: text
        - queue_length: bigint (total readable messages)
        - newest_msg_id: bigint
        - oldest_msg_id: bigint
        - total_messages: bigint
        - scrape_time: timestamptz
    """
    try:
        # Get basic metrics from pgmq
        result = conn.execute(
            "SELECT * FROM pgmq.metrics(%s)",
            [queue_name],
        ).fetchone()

        if not result:
            return None

        now = datetime.now(timezone.utc)
        scrape_time = result.get("scrape_time", now)

        # Calculate oldest message age by reading the oldest message timestamp
        oldest_age = None
        oldest_msg = conn.execute(
            f"SELECT enqueued_at FROM pgmq.q_{queue_name} ORDER BY msg_id ASC LIMIT 1"
        ).fetchone()
        if oldest_msg and oldest_msg.get("enqueued_at"):
            enqueued = oldest_msg["enqueued_at"]
            if enqueued.tzinfo is None:
                enqueued = enqueued.replace(tzinfo=timezone.utc)
            oldest_age = (now - enqueued).total_seconds()

        # Count invisible (processing) messages
        # Invisible = vt (visibility timeout) > now
        processing_result = conn.execute(
            f"SELECT COUNT(*) as cnt FROM pgmq.q_{queue_name} WHERE vt > NOW()"
        ).fetchone()
        processing_count = processing_result["cnt"] if processing_result else 0

        # Fetch worker status from heartbeats table
        worker_status = fetch_worker_status_for_queue(conn, queue_name)

        # Fetch last success time from workers.metrics
        last_success_at = fetch_queue_metrics_from_workers(conn, queue_name)

        return QueueMetrics(
            queue_name=queue_name,
            total_messages=result.get("total_messages", 0),
            oldest_message_age_seconds=oldest_age,
            processing_count=processing_count,
            newest_msg_id=result.get("newest_msg_id"),
            queue_length=result.get("queue_length", 0),
            scrape_time=scrape_time if isinstance(scrape_time, datetime) else now,
            worker_status=worker_status,
            last_success_at=last_success_at,
        )
    except Exception as e:
        click.echo(f"  ⚠️  Error fetching metrics for {queue_name}: {e}", err=True)
        return None


def print_dashboard(metrics: list[QueueMetrics], env: str) -> None:
    """Print formatted dashboard table."""
    click.echo()
    click.echo(f"{'=' * 110}")
    click.echo(f"  DRAGONFLY QUEUE DASHBOARD  |  Environment: {env.upper()}")
    click.echo(f"  Timestamp: {datetime.now(timezone.utc).isoformat()}")
    click.echo(f"{'=' * 110}")
    click.echo()

    # Header - now includes Worker Status and Last Success
    header = (
        f"{'Queue Name':<24} "
        f"{'Depth':<8} "
        f"{'Worker Status':<14} "
        f"{'Last Success':<14} "
        f"{'Oldest':<10} "
        f"{'Processing':<12} "
        f"{'Readable':<10}"
    )
    click.echo(header)
    click.echo("-" * 110)

    dlq_warning = False
    offline_workers = []

    for m in metrics:
        # Highlight DLQ if above threshold
        queue_display = m.queue_name
        if m.queue_name == "q_dead_letter" and m.total_messages >= DLQ_WARNING_THRESHOLD:
            queue_display = f"⚠️ {m.queue_name}"
            dlq_warning = True

        # Worker status display
        if m.worker_status:
            worker_display = m.worker_status.status_display
            if m.worker_status.status in ("offline", "stale"):
                offline_workers.append(m.queue_name)
        else:
            worker_display = "❓ Unknown"

        # Last success display
        last_success_display = m.last_success_human

        row = (
            f"{queue_display:<24} "
            f"{m.total_messages:<8} "
            f"{worker_display:<14} "
            f"{last_success_display:<14} "
            f"{m.oldest_age_human:<10} "
            f"{m.processing_count:<12} "
            f"{m.queue_length:<10}"
        )
        click.echo(row)

    click.echo("-" * 110)
    click.echo()

    # Summary stats
    total_all = sum(m.total_messages for m in metrics)
    total_processing = sum(m.processing_count for m in metrics)
    online_count = sum(1 for m in metrics if m.worker_status and m.worker_status.status == "online")
    offline_count = len(offline_workers)

    click.echo(f"  Total Messages: {total_all}  |  Processing: {total_processing}")
    click.echo(f"  Workers Online: {online_count}  |  Offline/Stale: {offline_count}")

    if offline_workers:
        click.echo()
        click.secho(
            f"  ⚠️  WARNING: {len(offline_workers)} queue(s) have no active workers!",
            fg="yellow",
            bold=True,
        )
        click.echo(f"     Affected: {', '.join(offline_workers)}")
        click.echo("     Run: python -m tools.monitor_workers --alert to notify")

    if dlq_warning:
        click.echo()
        click.secho(
            f"  ⚠️  WARNING: Dead Letter Queue has {metrics[-1].total_messages} messages!",
            fg="yellow",
            bold=True,
        )
        click.echo("     Run: python -m tools.replay_dlq --dry-run to inspect")

    click.echo()


def print_json(metrics: list[QueueMetrics]) -> None:
    """Print JSON output for alerting integrations."""
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "queues": [],
        "summary": {
            "total_messages": 0,
            "total_processing": 0,
            "workers_online": 0,
            "workers_offline": 0,
        },
    }

    for m in metrics:
        # Worker status
        worker_status_data = None
        if m.worker_status:
            worker_status_data = {
                "status": m.worker_status.status,
                "active_count": m.worker_status.active_count,
                "last_heartbeat": (
                    m.worker_status.last_heartbeat.isoformat()
                    if m.worker_status.last_heartbeat
                    else None
                ),
            }
            if m.worker_status.status == "online":
                output["summary"]["workers_online"] += 1
            else:
                output["summary"]["workers_offline"] += 1

        queue_data = {
            "queue_name": m.queue_name,
            "total_messages": m.total_messages,
            "oldest_message_age_seconds": m.oldest_message_age_seconds,
            "processing_count": m.processing_count,
            "queue_length": m.queue_length,
            "worker_status": worker_status_data,
            "last_success_at": (m.last_success_at.isoformat() if m.last_success_at else None),
        }
        output["queues"].append(queue_data)
        output["summary"]["total_messages"] += m.total_messages
        output["summary"]["total_processing"] += m.processing_count

    click.echo(json.dumps(output, indent=2, default=str))


@click.command()
@click.option(
    "--env",
    type=click.Choice(["dev", "prod"]),
    default=None,
    help="Target environment (default: auto-detect from SUPABASE_MODE)",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Output as JSON for alerting/monitoring",
)
@click.option(
    "--watch",
    is_flag=True,
    default=False,
    help="Continuous refresh every 5 seconds",
)
@click.option(
    "--interval",
    type=int,
    default=5,
    help="Refresh interval in seconds (with --watch)",
)
def main(
    env: Optional[str],
    json_output: bool,
    watch: bool,
    interval: int,
) -> None:
    """
    Dragonfly Queue Inspector - Real-time queue depth dashboard.

    Displays queue health metrics across all pgmq queues including
    message counts, age tracking, and processing visibility.
    """
    # Determine environment
    if env:
        os.environ["SUPABASE_MODE"] = env
    target_env = env or get_supabase_env()

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
        while True:
            # Fetch metrics for all queues
            metrics: list[QueueMetrics] = []
            for queue_name in QUEUE_NAMES:
                m = fetch_queue_metrics(conn, queue_name)
                if m:
                    metrics.append(m)

            # Output
            if json_output:
                print_json(metrics)
            else:
                # Clear screen for watch mode
                if watch:
                    click.clear()
                print_dashboard(metrics, target_env)

            if not watch:
                break

            time.sleep(interval)

    except KeyboardInterrupt:
        if not json_output:
            click.echo("\n👋 Queue inspector stopped.")
    except Exception as e:
        click.secho(f"❌ Query execution failed: {e}", fg="red", err=True)
        sys.exit(EXIT_QUERY_ERROR)
    finally:
        conn.close()

    sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
