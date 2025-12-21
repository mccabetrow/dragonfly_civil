"""
Dragonfly Monitor Worker - Native Monitoring Service

Replaces n8n for production health monitoring. Runs SQL-based health checks
every 60 seconds and logs CRITICAL | ALERT messages for Railway to capture.

Usage:
    python -m backend.workers.monitor                    # Run with default interval
    python -m backend.workers.monitor --interval 30     # Run every 30 seconds
    python -m backend.workers.monitor --once            # Run once and exit

Health Checks:
    - stuck_jobs: Jobs in 'processing' > 30 minutes
    - high_failure_rate: > 10% failures in last hour
    - dead_workers: No heartbeat in > 5 minutes
    - dlq_growing: Failed jobs with max retries in last hour
    - pending_backlog: > 100 pending jobs per type

Exit Codes:
    0 - Clean shutdown
    1 - General error
    2 - Database unavailable
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import psycopg
from psycopg.rows import dict_row

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.supabase_client import get_supabase_db_url

logger = logging.getLogger(__name__)

# Default check interval (seconds)
DEFAULT_CHECK_INTERVAL = 60

# Severity levels
SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_WARNING = "WARNING"


@dataclass
class AlertCheck:
    """Definition of a health check."""

    name: str
    severity: str
    query: str
    description: str


# =============================================================================
# HEALTH CHECK DEFINITIONS
# =============================================================================

ALERT_CHECKS: list[AlertCheck] = [
    AlertCheck(
        name="stuck_jobs",
        severity=SEVERITY_CRITICAL,
        description="Jobs in 'processing' state for over 30 minutes",
        query="""
            SELECT
                id,
                job_type,
                worker_id,
                locked_at,
                EXTRACT(EPOCH FROM (NOW() - locked_at)) / 60 AS minutes_stuck
            FROM ops.job_queue
            WHERE status = 'processing'
              AND locked_at < NOW() - INTERVAL '30 minutes'
            ORDER BY locked_at ASC
            LIMIT 10
        """,
    ),
    AlertCheck(
        name="high_failure_rate",
        severity=SEVERITY_CRITICAL,
        description="More than 10% of jobs failed in the last hour",
        query="""
            WITH hourly_stats AS (
                SELECT
                    COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                    COUNT(*) AS total
                FROM ops.job_queue
                WHERE updated_at >= NOW() - INTERVAL '1 hour'
            )
            SELECT
                completed,
                failed,
                total,
                ROUND(100.0 * failed / NULLIF(total, 0), 2) AS failure_rate_pct
            FROM hourly_stats
            WHERE total > 10
              AND (100.0 * failed / NULLIF(total, 0)) > 10
        """,
    ),
    AlertCheck(
        name="dead_workers",
        severity=SEVERITY_WARNING,
        description="Workers with no heartbeat in over 5 minutes",
        query="""
            SELECT
                worker_id,
                worker_type,
                status,
                last_seen_at,
                EXTRACT(EPOCH FROM (NOW() - last_seen_at)) / 60 AS minutes_since_heartbeat
            FROM ops.worker_heartbeats
            WHERE status NOT IN ('stopped', 'error')
              AND last_seen_at < NOW() - INTERVAL '5 minutes'
            ORDER BY last_seen_at ASC
            LIMIT 10
        """,
    ),
    AlertCheck(
        name="dlq_growing",
        severity=SEVERITY_WARNING,
        description="Dead letter queue has entries (failed jobs that exceeded retries)",
        query="""
            SELECT
                id,
                job_type,
                last_error,
                attempts,
                updated_at
            FROM ops.job_queue
            WHERE status = 'failed'
              AND attempts >= 3
              AND updated_at >= NOW() - INTERVAL '1 hour'
            ORDER BY updated_at DESC
            LIMIT 10
        """,
    ),
    AlertCheck(
        name="pending_backlog",
        severity=SEVERITY_WARNING,
        description="More than 100 pending jobs per type",
        query="""
            SELECT
                job_type,
                COUNT(*) AS pending_count,
                MIN(created_at) AS oldest_pending
            FROM ops.job_queue
            WHERE status = 'pending'
            GROUP BY job_type
            HAVING COUNT(*) > 100
            ORDER BY pending_count DESC
        """,
    ),
]


class MonitorWorker:
    """Native monitoring worker that runs health checks and logs alerts."""

    def __init__(self, check_interval: int = DEFAULT_CHECK_INTERVAL):
        self.check_interval = check_interval
        self.shutdown_requested = False
        self.db_url: str | None = None

        # Register signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    def _handle_shutdown(self, signum: int, frame: Any) -> None:
        """Handle shutdown signal."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_requested = True

    def _connect_db(self) -> psycopg.Connection[dict[str, Any]] | None:
        """Establish database connection."""
        try:
            if not self.db_url:
                self.db_url = get_supabase_db_url()

            conn = psycopg.connect(
                self.db_url,
                row_factory=dict_row,
                connect_timeout=10,
                application_name="dragonfly_monitor",
            )
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            return None

    def _run_check(
        self, conn: psycopg.Connection[dict[str, Any]], check: AlertCheck
    ) -> list[dict[str, Any]]:
        """Run a single health check and return alert rows."""
        try:
            with conn.cursor() as cur:
                cur.execute(check.query)
                rows = cur.fetchall()
                return list(rows)
        except Exception as e:
            logger.error(f"Check '{check.name}' failed: {e}")
            return []

    def _format_alert(self, check: AlertCheck, rows: list[dict[str, Any]]) -> str:
        """Format an alert message for logging."""
        lines = [
            f"ALERT: {check.name.upper()} - {check.description}",
            f"  Count: {len(rows)} issue(s) detected",
        ]

        for i, row in enumerate(rows[:5], 1):  # Limit to 5 examples
            row_str = ", ".join(f"{k}={v}" for k, v in row.items())
            lines.append(f"  [{i}] {row_str}")

        if len(rows) > 5:
            lines.append(f"  ... and {len(rows) - 5} more")

        return "\n".join(lines)

    def run_once(self) -> dict[str, int]:
        """Run all health checks once and return results."""
        results: dict[str, int] = {}
        conn = self._connect_db()

        if not conn:
            logger.error("CRITICAL | ALERT: Cannot connect to database")
            return {"_db_error": 1}

        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            logger.info(f"Running {len(ALERT_CHECKS)} health checks at {timestamp}")

            for check in ALERT_CHECKS:
                rows = self._run_check(conn, check)
                results[check.name] = len(rows)

                if rows:
                    alert_msg = self._format_alert(check, rows)
                    # Log with severity prefix that Railway can capture
                    if check.severity == SEVERITY_CRITICAL:
                        logger.critical(f"CRITICAL | {alert_msg}")
                    else:
                        logger.warning(f"WARNING | {alert_msg}")
                else:
                    logger.info(f"CHECK OK: {check.name}")

            # Summary
            alert_count = sum(1 for v in results.values() if v > 0)
            if alert_count == 0:
                logger.info(f"All {len(ALERT_CHECKS)} checks passed")
            else:
                logger.warning(f"{alert_count}/{len(ALERT_CHECKS)} checks have alerts")

        finally:
            conn.close()

        return results

    def run(self) -> int:
        """Run the monitor worker in a continuous loop."""
        logger.info("=" * 60)
        logger.info("DRAGONFLY MONITOR WORKER STARTING")
        logger.info(f"Check interval: {self.check_interval}s")
        logger.info(f"Health checks: {', '.join(c.name for c in ALERT_CHECKS)}")
        logger.info("=" * 60)

        cycle_count = 0

        while not self.shutdown_requested:
            cycle_count += 1
            logger.info(f"--- Monitor cycle {cycle_count} ---")

            try:
                self.run_once()
            except Exception as e:
                logger.error(f"CRITICAL | Monitor cycle failed: {e}")

            # Sleep with periodic checks for shutdown signal
            for _ in range(self.check_interval):
                if self.shutdown_requested:
                    break
                time.sleep(1)

        logger.info("Monitor worker shutting down gracefully")
        return 0


@click.command()
@click.option(
    "--interval",
    default=DEFAULT_CHECK_INTERVAL,
    type=int,
    help=f"Check interval in seconds (default: {DEFAULT_CHECK_INTERVAL})",
)
@click.option(
    "--once",
    is_flag=True,
    help="Run checks once and exit",
)
@click.option(
    "--env",
    type=click.Choice(["dev", "prod"]),
    help="Target environment",
)
def main(interval: int, once: bool, env: str | None) -> None:
    """Run the Dragonfly Monitor Worker."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if env:
        os.environ["SUPABASE_MODE"] = env

    worker = MonitorWorker(check_interval=interval)

    if once:
        results = worker.run_once()
        alert_count = sum(1 for v in results.values() if v > 0)
        raise SystemExit(1 if alert_count > 0 else 0)
    else:
        exit_code = worker.run()
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
