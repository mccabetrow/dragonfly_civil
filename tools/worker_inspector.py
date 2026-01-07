#!/usr/bin/env python3
"""
Dragonfly Worker Inspector - Combined Heartbeat & Metrics Dashboard

Provides unified visibility into worker fleet health by combining:
- workers.heartbeats: Real-time worker status and heartbeat freshness
- workers.metrics: Per-queue performance metrics and last success times

Features:
- Combined heartbeat + metrics view per queue
- Age-based alerting for stale workers (>5 min)
- Age-based alerting for stale queues (no success in threshold)
- JSON output for monitoring integrations
- Exit code 1 if any heartbeat is stale

Usage:
    python -m tools.worker_inspector                 # Default dashboard
    python -m tools.worker_inspector --env dev       # Target dev environment
    python -m tools.worker_inspector --env prod      # Target prod environment
    python -m tools.worker_inspector --json          # JSON output
    python -m tools.worker_inspector --alert         # Send Discord alerts

Exit Codes:
    0 - All workers healthy
    1 - Stale workers detected (heartbeat > 5 minutes old)
    2 - Database connection failed
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
DEFAULT_HEARTBEAT_STALE_MINUTES = 5
DEFAULT_SUCCESS_STALE_MINUTES = 30


@dataclass
class WorkerRecord:
    """Combined worker heartbeat and metrics record."""

    # Heartbeat fields
    worker_id: str
    queue_name: str
    hostname: str
    version: str
    pid: int
    status: str
    last_heartbeat_at: datetime
    jobs_processed: int
    jobs_failed: int

    # Metrics fields (may be None if no metrics yet)
    last_success_at: Optional[datetime] = None
    avg_latency_ms: Optional[float] = None
    total_processed: Optional[int] = None
    total_failed: Optional[int] = None

    @property
    def heartbeat_age_seconds(self) -> float:
        """Seconds since last heartbeat."""
        now = datetime.now(timezone.utc)
        last = self.last_heartbeat_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (now - last).total_seconds()

    @property
    def heartbeat_age_human(self) -> str:
        """Human-readable heartbeat age."""
        secs = self.heartbeat_age_seconds
        if secs < 60:
            return f"{int(secs)}s"
        elif secs < 3600:
            return f"{int(secs / 60)}m"
        elif secs < 86400:
            return f"{int(secs / 3600)}h"
        else:
            return f"{int(secs / 86400)}d"

    @property
    def success_age_seconds(self) -> Optional[float]:
        """Seconds since last successful job."""
        if self.last_success_at is None:
            return None
        now = datetime.now(timezone.utc)
        last = self.last_success_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (now - last).total_seconds()

    @property
    def success_age_human(self) -> str:
        """Human-readable success age."""
        secs = self.success_age_seconds
        if secs is None:
            return "never"
        if secs < 60:
            return f"{int(secs)}s"
        elif secs < 3600:
            return f"{int(secs / 60)}m"
        elif secs < 86400:
            return f"{int(secs / 3600)}h"
        else:
            return f"{int(secs / 86400)}d"

    @property
    def is_heartbeat_stale(self) -> bool:
        """Check if heartbeat is stale (> 5 minutes)."""
        return self.heartbeat_age_seconds > (DEFAULT_HEARTBEAT_STALE_MINUTES * 60)

    @property
    def health_status(self) -> str:
        """Computed health status based on heartbeat age."""
        if self.status == "stopped":
            return "stopped"
        mins = self.heartbeat_age_seconds / 60
        if mins > 5:
            return "dead"
        elif mins > 2:
            return "stale"
        else:
            return "alive"


def connect_db(dsn: str) -> psycopg.Connection:
    """Establish database connection."""
    return psycopg.connect(dsn, row_factory=dict_row, connect_timeout=10)


def fetch_worker_records(conn: psycopg.Connection) -> list[WorkerRecord]:
    """
    Fetch combined heartbeat and metrics data for all workers.

    Joins workers.heartbeats with workers.metrics on queue_name.
    """
    result = conn.execute(
        """
        SELECT 
            h.worker_id::text,
            h.queue_name,
            h.hostname,
            h.version,
            h.pid,
            h.status::text,
            h.last_heartbeat_at,
            h.jobs_processed,
            h.jobs_failed,
            m.last_success_at,
            m.avg_latency_ms,
            m.total_processed,
            m.total_failed
        FROM workers.heartbeats h
        LEFT JOIN workers.metrics m ON h.queue_name = m.queue_name
        ORDER BY h.queue_name, h.last_heartbeat_at DESC
        """
    ).fetchall()

    return [
        WorkerRecord(
            worker_id=row["worker_id"],
            queue_name=row["queue_name"],
            hostname=row["hostname"],
            version=row["version"],
            pid=row["pid"],
            status=row["status"],
            last_heartbeat_at=row["last_heartbeat_at"],
            jobs_processed=row["jobs_processed"],
            jobs_failed=row["jobs_failed"],
            last_success_at=row.get("last_success_at"),
            avg_latency_ms=row.get("avg_latency_ms"),
            total_processed=row.get("total_processed"),
            total_failed=row.get("total_failed"),
        )
        for row in result
    ]


def print_dashboard(
    workers: list[WorkerRecord],
    env: str,
) -> None:
    """Print formatted dashboard table."""
    click.echo()
    click.echo("=" * 110)
    click.echo(f"  DRAGONFLY WORKER INSPECTOR  |  Environment: {env.upper()}")
    click.echo(f"  Timestamp: {datetime.now(timezone.utc).isoformat()}")
    click.echo("=" * 110)
    click.echo()

    if not workers:
        click.echo("  No worker heartbeats found in workers.heartbeats")
        click.echo()
        return

    # Header
    header = (
        f"{'Worker Name':<26} "
        f"{'Status':<10} "
        f"{'Last Heartbeat':<16} "
        f"{'Last Success':<14} "
        f"{'Processed':<10} "
        f"{'Latency':<10} "
        f"{'Host':<16}"
    )
    click.echo(header)
    click.echo("-" * 110)

    stale_count = 0
    for w in workers:
        # Color-code health status
        health = w.health_status
        if health == "alive":
            status_display = click.style("✅ alive", fg="green")
        elif health == "stale":
            status_display = click.style("⚠️ stale", fg="yellow")
            stale_count += 1
        elif health == "dead":
            status_display = click.style("💀 dead", fg="red")
            stale_count += 1
        else:
            status_display = click.style("⏹ stop", fg="bright_black")

        # Format latency
        latency_str = f"{w.avg_latency_ms:.0f}ms" if w.avg_latency_ms else "—"

        # Format processed count
        processed_str = str(w.total_processed) if w.total_processed else str(w.jobs_processed)

        row = (
            f"{w.queue_name:<26} "
            f"{status_display:<20} "  # Extra chars for ANSI codes
            f"{w.heartbeat_age_human + ' ago':<16} "
            f"{w.success_age_human + ' ago':<14} "
            f"{processed_str:<10} "
            f"{latency_str:<10} "
            f"{w.hostname[:16]:<16}"
        )
        click.echo(row)

    click.echo("-" * 110)
    click.echo()

    # Summary
    alive_count = sum(1 for w in workers if w.health_status == "alive")
    stopped_count = sum(1 for w in workers if w.status == "stopped")

    click.echo(f"  Total Workers: {len(workers)}")
    click.echo(
        f"  ✅ Alive: {alive_count}  |  ⚠️ Stale/Dead: {stale_count}  |  ⏹ Stopped: {stopped_count}"
    )

    if stale_count > 0:
        click.echo()
        click.secho(
            f"  ⚠️  ALERT: {stale_count} worker(s) have stale heartbeats (>5 min)!",
            fg="red",
            bold=True,
        )
        click.echo("     These workers may be dead or stuck. Check Railway logs.")

    click.echo()


def print_json(workers: list[WorkerRecord]) -> None:
    """Print JSON output for monitoring integrations."""
    stale_workers = [w for w in workers if w.is_heartbeat_stale and w.status != "stopped"]

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_workers": len(workers),
            "alive_count": sum(1 for w in workers if w.health_status == "alive"),
            "stale_count": len(stale_workers),
            "stopped_count": sum(1 for w in workers if w.status == "stopped"),
        },
        "workers": [
            {
                "worker_id": w.worker_id,
                "queue_name": w.queue_name,
                "hostname": w.hostname,
                "version": w.version,
                "status": w.status,
                "health": w.health_status,
                "last_heartbeat_at": (
                    w.last_heartbeat_at.isoformat() if w.last_heartbeat_at else None
                ),
                "heartbeat_age_seconds": int(w.heartbeat_age_seconds),
                "last_success_at": w.last_success_at.isoformat() if w.last_success_at else None,
                "success_age_seconds": (
                    int(w.success_age_seconds) if w.success_age_seconds else None
                ),
                "jobs_processed": w.jobs_processed,
                "jobs_failed": w.jobs_failed,
                "total_processed": w.total_processed,
                "total_failed": w.total_failed,
                "avg_latency_ms": w.avg_latency_ms,
            }
            for w in workers
        ],
        "alerts": [
            {
                "worker_id": w.worker_id,
                "queue_name": w.queue_name,
                "heartbeat_age_seconds": int(w.heartbeat_age_seconds),
                "message": f"No heartbeat in {w.heartbeat_age_human}",
            }
            for w in stale_workers
        ],
    }

    click.echo(json.dumps(output, indent=2))


def send_discord_alert(stale_workers: list[WorkerRecord], env: str) -> bool:
    """Send Discord alert for stale workers."""
    try:
        from backend.utils.discord import AlertColor, send_alert

        fields = {
            "Environment": env.upper(),
            "Stale Workers": str(len(stale_workers)),
        }

        for w in stale_workers[:5]:
            fields[f"💀 {w.queue_name}"] = (
                f"Last HB: {w.heartbeat_age_human} ago | Host: {w.hostname}"
            )

        if len(stale_workers) > 5:
            fields["...and more"] = f"{len(stale_workers) - 5} additional stale workers"

        return send_alert(
            title="💀 Worker(s) Missing",
            description=f"Detected {len(stale_workers)} worker(s) with stale heartbeats (>5 min).",
            color=AlertColor.FAILURE,
            fields=fields,
        )

    except ImportError:
        click.secho("⚠️ Discord module not available", fg="yellow", err=True)
        return False
    except Exception as e:
        click.secho(f"⚠️ Discord alert failed: {e}", fg="yellow", err=True)
        return False


@click.command()
@click.option(
    "--env",
    type=click.Choice(["dev", "prod"]),
    default=None,
    help="Target environment (default: from SUPABASE_MODE)",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output in JSON format",
)
@click.option(
    "--alert",
    is_flag=True,
    help="Send Discord alert if stale workers detected",
)
def main(
    env: Optional[str],
    output_json: bool,
    alert: bool,
) -> None:
    """
    Inspect worker fleet health via heartbeats and metrics.

    Displays a combined table of:
    - Worker Name (queue_name)
    - Status (alive/stale/dead/stopped)
    - Last Heartbeat (age)
    - Last Success (age)
    - Jobs Processed
    - Avg Latency

    Exit code 1 if any worker has a stale heartbeat (>5 minutes).
    """
    # Resolve environment
    if env:
        os.environ["SUPABASE_MODE"] = env
    active_env = get_supabase_env()

    # Connect to database
    try:
        db_url = get_supabase_db_url(active_env)
        conn = connect_db(db_url)
    except Exception as e:
        if output_json:
            click.echo(json.dumps({"error": str(e), "exit_code": EXIT_DB_ERROR}))
        else:
            click.secho(f"❌ Database connection failed: {e}", fg="red", err=True)
        sys.exit(EXIT_DB_ERROR)

    try:
        # Fetch worker data
        workers = fetch_worker_records(conn)

        # Identify stale workers (not stopped, heartbeat > 5 min)
        stale_workers = [w for w in workers if w.is_heartbeat_stale and w.status != "stopped"]

        # Output
        if output_json:
            print_json(workers)
        else:
            print_dashboard(workers, active_env)

        # Send Discord alert if requested and stale workers exist
        if alert and stale_workers:
            send_discord_alert(stale_workers, active_env)

        # Exit with appropriate code
        if stale_workers:
            sys.exit(EXIT_STALE)
        else:
            sys.exit(EXIT_HEALTHY)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
