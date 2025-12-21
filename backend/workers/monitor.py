"""
Dragonfly Monitor Worker - SLO Enforcement + Native Monitoring Service

Production-grade monitoring with SLO enforcement. Runs health checks every
60 seconds and logs CRITICAL | ALERT messages for Railway to capture.

Usage:
    python -m backend.workers.monitor                    # Run with default interval
    python -m backend.workers.monitor --interval 30     # Run every 30 seconds
    python -m backend.workers.monitor --once            # Run once and exit
    python -m backend.workers.monitor --slo             # Run SLO checks only

SLO Targets (enforced):
    - Processing Freshness: P95 latency <= 10 minutes (target: 95%)
    - Data Quality: DLQ rate < 1% of total job volume
    - Worker Health: All workers must heartbeat within 5 minutes

Health Checks:
    - stuck_jobs: Jobs in 'processing' > 30 minutes
    - high_failure_rate: > 10% failures in last hour
    - dead_workers: No heartbeat in > 5 minutes
    - dlq_growing: Failed jobs with max retries in last hour
    - pending_backlog: > 100 pending jobs per type

SLO Checks (View-based):
    - slo_freshness_breach: P95 latency > 10 minutes or SLO compliance < 95%
    - slo_error_budget_breach: DLQ rate >= 1% or error budget exhausted
    - slo_worker_health: Any dead workers (>5 min no heartbeat)
    - slo_stuck_processing: Jobs stuck processing for >30 minutes

Exit Codes:
    0 - Clean shutdown
    1 - General error
    2 - Database unavailable
    3 - SLO breach detected
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

# SLO thresholds
SLO_P95_LATENCY_THRESHOLD = 10.0  # minutes
SLO_COMPLIANCE_THRESHOLD = 95.0  # percentage
SLO_DLQ_RATE_THRESHOLD = 1.0  # percentage
SLO_ERROR_BUDGET_CRITICAL = 10  # basis points (0.1%)
SLO_STUCK_THRESHOLD_MINUTES = 30


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


# =============================================================================
# SLO CHECK DEFINITIONS (View-Based)
# =============================================================================

SLO_CHECKS: list[AlertCheck] = [
    AlertCheck(
        name="slo_freshness_breach",
        severity=SEVERITY_CRITICAL,
        description=f"Processing Freshness SLO: P95 latency > {SLO_P95_LATENCY_THRESHOLD}min or compliance < {SLO_COMPLIANCE_THRESHOLD}%",
        query=f"""
            SELECT
                p95_latency_minutes,
                slo_compliance_pct,
                pending_count,
                oldest_pending_minutes,
                slo_status,
                measured_at
            FROM ops.view_slo_processing_freshness
            WHERE slo_status IN ('WARNING', 'BREACH')
               OR slo_compliance_pct < {SLO_COMPLIANCE_THRESHOLD}
               OR p95_latency_minutes > {SLO_P95_LATENCY_THRESHOLD}
        """,
    ),
    AlertCheck(
        name="slo_error_budget_breach",
        severity=SEVERITY_CRITICAL,
        description=f"Data Quality SLO: DLQ rate >= {SLO_DLQ_RATE_THRESHOLD}% or error budget < {SLO_ERROR_BUDGET_CRITICAL} bps",
        query=f"""
            SELECT
                dlq_rate_percent,
                failure_rate_percent,
                error_budget_remaining_bps,
                dlq_count_24h,
                total_jobs_24h,
                slo_status,
                measured_at
            FROM ops.view_slo_error_budget
            WHERE slo_status IN ('WARNING', 'BREACH')
               OR dlq_rate_percent >= {SLO_DLQ_RATE_THRESHOLD}
               OR error_budget_remaining_bps < {SLO_ERROR_BUDGET_CRITICAL}
        """,
    ),
    AlertCheck(
        name="slo_worker_health",
        severity=SEVERITY_WARNING,
        description="Worker SLO: Dead workers detected (no heartbeat > 5 minutes)",
        query="""
            SELECT
                worker_id,
                worker_type,
                minutes_since_heartbeat,
                health_status,
                last_seen_at
            FROM ops.view_slo_active_workers
            WHERE health_status = 'DEAD'
            ORDER BY minutes_since_heartbeat DESC
            LIMIT 10
        """,
    ),
    AlertCheck(
        name="slo_stuck_processing",
        severity=SEVERITY_CRITICAL,
        description=f"Processing SLO: Jobs stuck in processing > {SLO_STUCK_THRESHOLD_MINUTES} minutes",
        query="""
            SELECT
                stuck_jobs,
                overall_status,
                queue_depth,
                processing_count,
                measured_at
            FROM ops.view_slo_system_health
            WHERE stuck_jobs > 0
               OR overall_status = 'CRITICAL'
        """,
    ),
]


class MonitorWorker:
    """Native monitoring worker that runs health checks and SLO enforcement."""

    def __init__(
        self,
        check_interval: int = DEFAULT_CHECK_INTERVAL,
        slo_only: bool = False,
    ):
        self.check_interval = check_interval
        self.slo_only = slo_only
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
        slo_breaches: dict[str, int] = {}
        conn = self._connect_db()

        if not conn:
            logger.error("CRITICAL | ALERT: Cannot connect to database")
            return {"_db_error": 1}

        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

            # Run SLO checks first (always)
            logger.info(f"Running {len(SLO_CHECKS)} SLO checks at {timestamp}")

            for check in SLO_CHECKS:
                rows = self._run_check(conn, check)
                slo_breaches[check.name] = len(rows)

                if rows:
                    alert_msg = self._format_alert(check, rows)
                    if check.severity == SEVERITY_CRITICAL:
                        logger.critical(f"SLO BREACH | {alert_msg}")
                    else:
                        logger.warning(f"SLO WARNING | {alert_msg}")
                else:
                    logger.info(f"SLO OK: {check.name}")

            # Run legacy health checks (unless slo_only mode)
            if not self.slo_only:
                logger.info(f"Running {len(ALERT_CHECKS)} health checks")

                for check in ALERT_CHECKS:
                    rows = self._run_check(conn, check)
                    results[check.name] = len(rows)

                    if rows:
                        alert_msg = self._format_alert(check, rows)
                        if check.severity == SEVERITY_CRITICAL:
                            logger.critical(f"CRITICAL | {alert_msg}")
                        else:
                            logger.warning(f"WARNING | {alert_msg}")
                    else:
                        logger.info(f"CHECK OK: {check.name}")

            # Log SLO Dashboard Summary
            self._log_slo_summary(conn)

            # Summary
            all_checks = {**results, **slo_breaches}
            alert_count = sum(1 for v in all_checks.values() if v > 0)
            slo_breach_count = sum(1 for v in slo_breaches.values() if v > 0)

            if alert_count == 0:
                logger.info(
                    f"All checks passed (SLO: {len(SLO_CHECKS)}, Health: {len(ALERT_CHECKS)})"
                )
            else:
                logger.warning(
                    f"{alert_count} check(s) have alerts ({slo_breach_count} SLO breaches)"
                )

            # Merge results
            results.update(slo_breaches)
            results["_slo_breach_count"] = slo_breach_count

        finally:
            conn.close()

        return results

    def _log_slo_summary(self, conn: psycopg.Connection[dict[str, Any]]) -> None:
        """Log a compact SLO dashboard summary."""
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM ops.view_slo_system_health")
                row = cur.fetchone()

                if row:
                    status = row.get("overall_status", "UNKNOWN")
                    p95 = row.get("p95_latency_minutes", 0)
                    compliance = row.get("freshness_slo_pct", 0)
                    error_rate = row.get("error_rate_pct", 0)
                    dlq_rate = row.get("dlq_rate_percent", 0)
                    queue = row.get("queue_depth", 0)
                    workers = row.get("active_workers", 0)
                    stuck = row.get("stuck_jobs", 0)

                    logger.info("=" * 60)
                    logger.info("SLO DASHBOARD SUMMARY")
                    logger.info(f"  Overall Status: {status}")
                    logger.info(f"  P95 Latency: {p95:.2f} min (target: ≤10)")
                    logger.info(f"  Freshness SLO: {compliance:.1f}% (target: ≥95%)")
                    logger.info(f"  Error Rate: {error_rate:.3f}% | DLQ Rate: {dlq_rate:.3f}%")
                    logger.info(
                        f"  Queue Depth: {queue} | Active Workers: {workers} | Stuck: {stuck}"
                    )
                    logger.info("=" * 60)
        except Exception as e:
            logger.warning(f"Could not fetch SLO summary: {e}")

    def run(self) -> int:
        """Run the monitor worker in a continuous loop."""
        logger.info("=" * 60)
        logger.info("DRAGONFLY MONITOR WORKER STARTING")
        logger.info(f"Check interval: {self.check_interval}s")
        logger.info(f"Mode: {'SLO Only' if self.slo_only else 'Full (SLO + Health)'}")
        logger.info(f"SLO checks: {', '.join(c.name for c in SLO_CHECKS)}")
        if not self.slo_only:
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
    "--slo",
    is_flag=True,
    help="Run SLO checks only (skip legacy health checks)",
)
@click.option(
    "--env",
    type=click.Choice(["dev", "prod"]),
    help="Target environment",
)
def main(interval: int, once: bool, slo: bool, env: str | None) -> None:
    """Run the Dragonfly Monitor Worker with SLO enforcement."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if env:
        os.environ["SUPABASE_MODE"] = env

    worker = MonitorWorker(check_interval=interval, slo_only=slo)

    if once:
        results = worker.run_once()
        slo_breach_count = results.get("_slo_breach_count", 0)
        alert_count = sum(1 for k, v in results.items() if v > 0 and not k.startswith("_"))

        # Exit with 3 for SLO breaches
        if slo_breach_count > 0:
            raise SystemExit(3)
        elif alert_count > 0:
            raise SystemExit(1)
        else:
            raise SystemExit(0)
    else:
        exit_code = worker.run()
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
