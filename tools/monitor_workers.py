#!/usr/bin/env python3
"""
Dragonfly Worker Monitor - Stale Heartbeat Detection & Alerting

Watches workers.heartbeats for stale workers and alerts Discord when
workers go missing (no heartbeat in 5+ minutes).

Features:
- Stale worker detection (configurable threshold)
- Discord alerts for missing workers
- Optional cleanup of old heartbeat records
- JSON output for monitoring integrations
- Continuous watch mode

Usage:
    python -m tools.monitor_workers                    # Check once
    python -m tools.monitor_workers --env dev          # Target dev
    python -m tools.monitor_workers --watch            # Continuous (60s)
    python -m tools.monitor_workers --alert            # Send Discord alerts
    python -m tools.monitor_workers --prune            # Cleanup old records
    python -m tools.monitor_workers --json             # JSON output

Exit Codes:
    0 - All workers healthy
    1 - Stale workers detected
    2 - Database connection failed
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import click
import psycopg
from psycopg.rows import dict_row

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.supabase_client import get_supabase_db_url, get_supabase_env

# Exit codes
EXIT_HEALTHY = 0
EXIT_STALE = 1
EXIT_DB_ERROR = 2

# Default thresholds
DEFAULT_STALE_THRESHOLD_MINUTES = 5
DEFAULT_PRUNE_THRESHOLD_HOURS = 24
DEFAULT_WATCH_INTERVAL = 60


@dataclass
class WorkerHeartbeat:
    """Represents a worker heartbeat record."""

    worker_id: str
    queue_name: str
    hostname: str
    version: str
    pid: int
    status: str
    last_heartbeat_at: datetime
    jobs_processed: int
    jobs_failed: int

    @property
    def seconds_since_heartbeat(self) -> float:
        """Seconds since last heartbeat."""
        now = datetime.now(timezone.utc)
        if self.last_heartbeat_at.tzinfo is None:
            last = self.last_heartbeat_at.replace(tzinfo=timezone.utc)
        else:
            last = self.last_heartbeat_at
        return (now - last).total_seconds()

    @property
    def minutes_since_heartbeat(self) -> float:
        """Minutes since last heartbeat."""
        return self.seconds_since_heartbeat / 60

    @property
    def age_human(self) -> str:
        """Human-readable age."""
        secs = self.seconds_since_heartbeat
        if secs < 60:
            return f"{int(secs)}s"
        elif secs < 3600:
            return f"{int(secs / 60)}m"
        elif secs < 86400:
            return f"{int(secs / 3600)}h"
        else:
            return f"{int(secs / 86400)}d"

    @property
    def is_stale(self) -> bool:
        """Check if heartbeat is stale (> 5 minutes)."""
        return self.minutes_since_heartbeat > DEFAULT_STALE_THRESHOLD_MINUTES

    @property
    def health_status(self) -> str:
        """Computed health status."""
        if self.status == "stopped":
            return "stopped"
        elif self.minutes_since_heartbeat > 5:
            return "dead"
        elif self.minutes_since_heartbeat > 2:
            return "stale"
        else:
            return "alive"


def connect_db(dsn: str) -> psycopg.Connection:
    """Establish database connection."""
    return psycopg.connect(dsn, row_factory=dict_row)


def fetch_all_heartbeats(conn: psycopg.Connection) -> list[WorkerHeartbeat]:
    """Fetch all worker heartbeats."""
    result = conn.execute(
        """
        SELECT 
            worker_id::text,
            queue_name,
            hostname,
            version,
            pid,
            status::text,
            last_heartbeat_at,
            jobs_processed,
            jobs_failed
        FROM workers.heartbeats
        ORDER BY queue_name, last_heartbeat_at DESC
    """
    ).fetchall()

    return [
        WorkerHeartbeat(
            worker_id=row["worker_id"],
            queue_name=row["queue_name"],
            hostname=row["hostname"],
            version=row["version"],
            pid=row["pid"],
            status=row["status"],
            last_heartbeat_at=row["last_heartbeat_at"],
            jobs_processed=row["jobs_processed"],
            jobs_failed=row["jobs_failed"],
        )
        for row in result
    ]


def fetch_stale_workers(
    conn: psycopg.Connection,
    threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
) -> list[WorkerHeartbeat]:
    """Fetch only stale workers (no heartbeat in threshold minutes)."""
    result = conn.execute(
        """
        SELECT 
            worker_id::text,
            queue_name,
            hostname,
            version,
            pid,
            status::text,
            last_heartbeat_at,
            jobs_processed,
            jobs_failed
        FROM workers.heartbeats
        WHERE status NOT IN ('stopped')
          AND last_heartbeat_at < now() - (%s || ' minutes')::INTERVAL
        ORDER BY last_heartbeat_at ASC
        """,
        [threshold_minutes],
    ).fetchall()

    return [
        WorkerHeartbeat(
            worker_id=row["worker_id"],
            queue_name=row["queue_name"],
            hostname=row["hostname"],
            version=row["version"],
            pid=row["pid"],
            status=row["status"],
            last_heartbeat_at=row["last_heartbeat_at"],
            jobs_processed=row["jobs_processed"],
            jobs_failed=row["jobs_failed"],
        )
        for row in result
    ]


def prune_old_heartbeats(
    conn: psycopg.Connection,
    threshold_hours: int = DEFAULT_PRUNE_THRESHOLD_HOURS,
) -> int:
    """Delete heartbeats older than threshold hours. Returns count deleted."""
    result = conn.execute(
        """
        DELETE FROM workers.heartbeats
        WHERE last_heartbeat_at < now() - (%s || ' hours')::INTERVAL
        RETURNING worker_id
        """,
        [threshold_hours],
    ).fetchall()
    conn.commit()
    return len(result)


def send_discord_alert(
    stale_workers: list[WorkerHeartbeat],
    env: str,
) -> bool:
    """Send Discord alert for stale workers."""
    try:
        from backend.utils.discord import AlertColor, send_alert

        # Build fields for each stale worker
        fields = {
            "Environment": env.upper(),
            "Stale Workers": str(len(stale_workers)),
        }

        # Add details for up to 5 workers
        for i, worker in enumerate(stale_workers[:5]):
            fields[f"💀 {worker.queue_name}"] = (
                f"Last: {worker.age_human} ago | Host: {worker.hostname}"
            )

        if len(stale_workers) > 5:
            fields["...and more"] = f"{len(stale_workers) - 5} additional stale workers"

        return send_alert(
            title="💀 Worker(s) Missing",
            description=(
                f"Detected {len(stale_workers)} worker(s) with stale heartbeats. "
                f"No heartbeat received in over 5 minutes."
            ),
            color=AlertColor.FAILURE,
            fields=fields,
        )

    except ImportError:
        click.secho("⚠️  Discord module not available", fg="yellow", err=True)
        return False
    except Exception as e:
        click.secho(f"⚠️  Discord alert failed: {e}", fg="yellow", err=True)
        return False


def print_dashboard(
    heartbeats: list[WorkerHeartbeat],
    stale_workers: list[WorkerHeartbeat],
    env: str,
) -> None:
    """Print formatted dashboard table."""
    click.echo()
    click.echo(f"{'=' * 90}")
    click.echo(f"  DRAGONFLY WORKER MONITOR  |  Environment: {env.upper()}")
    click.echo(f"  Timestamp: {datetime.now(timezone.utc).isoformat()}")
    click.echo(f"{'=' * 90}")
    click.echo()

    if not heartbeats:
        click.echo("  No worker heartbeats found.")
        click.echo()
        return

    # Header
    header = (
        f"{'Queue':<24} "
        f"{'Status':<10} "
        f"{'Health':<8} "
        f"{'Last HB':<10} "
        f"{'Processed':<12} "
        f"{'Host':<20}"
    )
    click.echo(header)
    click.echo("-" * 90)

    for hb in heartbeats:
        # Color-code health status
        health = hb.health_status
        if health == "alive":
            health_display = click.style("✅ alive", fg="green")
        elif health == "stale":
            health_display = click.style("⚠️ stale", fg="yellow")
        elif health == "dead":
            health_display = click.style("💀 dead", fg="red")
        else:
            health_display = click.style("⏹ stop", fg="bright_black")

        row = (
            f"{hb.queue_name:<24} "
            f"{hb.status:<10} "
            f"{health_display:<18} "  # Extra for ANSI codes
            f"{hb.age_human:<10} "
            f"{hb.jobs_processed:<12} "
            f"{hb.hostname[:20]:<20}"
        )
        click.echo(row)

    click.echo("-" * 90)
    click.echo()

    # Summary
    alive_count = sum(1 for h in heartbeats if h.health_status == "alive")
    stale_count = len(stale_workers)
    stopped_count = sum(1 for h in heartbeats if h.status == "stopped")

    click.echo(f"  Total Workers: {len(heartbeats)}")
    click.echo(f"  Alive: {alive_count}  |  Stale: {stale_count}  |  Stopped: {stopped_count}")

    if stale_count > 0:
        click.echo()
        click.secho(
            f"  ⚠️  WARNING: {stale_count} worker(s) have stale heartbeats!",
            fg="red",
            bold=True,
        )
        click.echo("     These workers may be dead or stuck.")
        click.echo("     Run with --alert to send Discord notification.")

    click.echo()


def print_json(
    heartbeats: list[WorkerHeartbeat],
    stale_workers: list[WorkerHeartbeat],
) -> None:
    """Print JSON output for monitoring integrations."""
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workers": [
            {
                "worker_id": h.worker_id,
                "queue_name": h.queue_name,
                "hostname": h.hostname,
                "version": h.version,
                "pid": h.pid,
                "status": h.status,
                "health_status": h.health_status,
                "last_heartbeat_at": h.last_heartbeat_at.isoformat(),
                "seconds_since_heartbeat": round(h.seconds_since_heartbeat, 1),
                "jobs_processed": h.jobs_processed,
                "jobs_failed": h.jobs_failed,
            }
            for h in heartbeats
        ],
        "summary": {
            "total_workers": len(heartbeats),
            "alive": sum(1 for h in heartbeats if h.health_status == "alive"),
            "stale": len(stale_workers),
            "stopped": sum(1 for h in heartbeats if h.status == "stopped"),
        },
        "stale_workers": [
            {
                "worker_id": h.worker_id,
                "queue_name": h.queue_name,
                "hostname": h.hostname,
                "minutes_since_heartbeat": round(h.minutes_since_heartbeat, 1),
            }
            for h in stale_workers
        ],
    }

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
    help="Output as JSON for monitoring integrations",
)
@click.option(
    "--watch",
    is_flag=True,
    default=False,
    help="Continuous monitoring (default: 60s interval)",
)
@click.option(
    "--interval",
    type=int,
    default=DEFAULT_WATCH_INTERVAL,
    help="Watch interval in seconds (default: 60)",
)
@click.option(
    "--alert",
    is_flag=True,
    default=False,
    help="Send Discord alert if stale workers detected",
)
@click.option(
    "--prune",
    is_flag=True,
    default=False,
    help="Delete heartbeats older than 24 hours",
)
@click.option(
    "--threshold",
    type=int,
    default=DEFAULT_STALE_THRESHOLD_MINUTES,
    help="Stale threshold in minutes (default: 5)",
)
def main(
    env: Optional[str],
    json_output: bool,
    watch: bool,
    interval: int,
    alert: bool,
    prune: bool,
    threshold: int,
) -> None:
    """
    Dragonfly Worker Monitor - Detect stale worker heartbeats.

    Monitors workers.heartbeats table for workers that have stopped
    sending heartbeats, indicating they may be dead or stuck.
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

    exit_code = EXIT_HEALTHY

    try:
        while True:
            # Fetch all heartbeats and stale workers
            heartbeats = fetch_all_heartbeats(conn)
            stale_workers = fetch_stale_workers(conn, threshold)

            # Output
            if json_output:
                print_json(heartbeats, stale_workers)
            else:
                # Clear screen for watch mode
                if watch:
                    click.clear()
                print_dashboard(heartbeats, stale_workers, target_env)

            # Send Discord alert if enabled and stale workers detected
            if alert and stale_workers:
                if not json_output:
                    click.echo("  📢 Sending Discord alert...")
                if send_discord_alert(stale_workers, target_env):
                    if not json_output:
                        click.echo("  ✅ Discord alert sent")
                else:
                    if not json_output:
                        click.echo("  ⚠️  Discord alert failed or not configured")

            # Prune old records if requested
            if prune:
                deleted = prune_old_heartbeats(conn)
                if not json_output and deleted > 0:
                    click.echo(f"  🧹 Pruned {deleted} old heartbeat records")

            # Set exit code based on stale workers
            if stale_workers:
                exit_code = EXIT_STALE

            if not watch:
                break

            time.sleep(interval)

    except KeyboardInterrupt:
        if not json_output:
            click.echo("\n👋 Worker monitor stopped.")
    except Exception as e:
        click.secho(f"❌ Error: {e}", fg="red", err=True)
        sys.exit(EXIT_DB_ERROR)
    finally:
        conn.close()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
