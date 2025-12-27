#!/usr/bin/env python3
"""
Dragonfly Watchdog - Proactive Health Monitoring + Discord Alerting

A self-healing monitor that continuously checks system health and sends
Discord alerts when thresholds are breached. Implements debouncing and
burn-rate based alerting for actionable, runbook-linked notifications.

Usage:
    python -m backend.workers.watchdog               # Run continuously
    python -m backend.workers.watchdog --once        # Single check and exit
    python -m backend.workers.watchdog --interval 30 # Custom interval

Environment:
    DISCORD_WEBHOOK_URL: Required. Discord webhook for alerts.
    SUPABASE_MODE: dev | prod (determines which Supabase to check)

Alert Conditions:
    - No active workers (0 heartbeats in last 5 min) -> CRITICAL
    - Queue stale (oldest pending job > 30 min) -> WARNING
    - Reaper stale (last reap > 15 min ago) -> WARNING
    - Reaper heartbeat stale (> 20 min) -> CRITICAL
    - High error rate (> 5% failures in last hour) -> CRITICAL
    - High burn rate (> 50% increase in failures) -> CRITICAL
    - WATCHDOG BLIND: Database unreachable after retries -> CRITICAL

Burn Rate Alerting:
    Instead of static thresholds, burn rate alerts trigger when failure
    rate accelerates (e.g., 50% more failures in last 5 min vs previous 5 min).

Runbook Integration:
    All alerts include hyperlinks to relevant runbook documentation.

Debouncing:
    Each alert type can only fire once per hour (configurable).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import click
import psycopg
import requests
from psycopg.rows import dict_row

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.utils.db import DatabaseOutageError, PoolerUnavailableError, get_db_connection

# =============================================================================
# RUNBOOK CONFIGURATION
# =============================================================================
# Map alert types to runbook URLs for actionable alerts
RUNBOOKS: dict[str, str] = {
    "active_workers": "https://docs.dragonfly.com/runbooks/no-active-workers",
    "queue_freshness": "https://docs.dragonfly.com/runbooks/scaling-workers",
    "reaper_health": "https://docs.dragonfly.com/runbooks/reaper-stale",
    "reaper_heartbeat": "https://docs.dragonfly.com/runbooks/reaper-dead",
    "error_rate_24h": "https://docs.dragonfly.com/runbooks/error-spike",
    "stuck_jobs": "https://docs.dragonfly.com/runbooks/stuck-jobs",
    "burn_rate": "https://docs.dragonfly.com/runbooks/burn-rate-alert",
    "watchdog_blind": "https://docs.dragonfly.com/runbooks/database-outage",
    "db_connection": "https://docs.dragonfly.com/runbooks/database-connection",
}

# Burn rate thresholds
BURN_RATE_WARNING_THRESHOLD = 50.0  # 50% increase triggers warning
BURN_RATE_CRITICAL_THRESHOLD = 100.0  # 100% increase triggers critical

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_CHECK_INTERVAL = 60  # seconds
DEBOUNCE_WINDOW = timedelta(hours=1)  # Alert once per hour per issue type

# Thresholds - all configurable via environment variables
THRESHOLD_WORKER_HEARTBEAT_MINUTES = int(
    os.environ.get("WATCHDOG_HEARTBEAT_THRESHOLD_MINUTES", "5")
)
THRESHOLD_QUEUE_STALE_MINUTES = int(os.environ.get("WATCHDOG_QUEUE_STALE_THRESHOLD_MINUTES", "30"))
THRESHOLD_REAPER_STALE_MINUTES = int(
    os.environ.get("WATCHDOG_REAPER_STALE_THRESHOLD_MINUTES", "15")
)
THRESHOLD_REAPER_HEARTBEAT_MINUTES = int(
    os.environ.get("WATCHDOG_REAPER_HEARTBEAT_THRESHOLD_MINUTES", "20")
)
THRESHOLD_ERROR_RATE_PERCENT = float(
    os.environ.get("WATCHDOG_ERROR_RATE_THRESHOLD_PERCENT", "10.0")
)  # 24h window


@dataclass
class AlertState:
    """Tracks debounce state for each alert type."""

    last_alert_times: dict[str, datetime] = field(default_factory=dict)

    def can_alert(self, alert_type: str) -> bool:
        """Check if we can send an alert (respects debounce window)."""
        last_time = self.last_alert_times.get(alert_type)
        if last_time is None:
            return True
        return datetime.now(timezone.utc) - last_time > DEBOUNCE_WINDOW

    def mark_alerted(self, alert_type: str) -> None:
        """Mark that we sent an alert."""
        self.last_alert_times[alert_type] = datetime.now(timezone.utc)

    def clear(self, alert_type: str) -> None:
        """Clear alert state (issue resolved)."""
        self.last_alert_times.pop(alert_type, None)


@dataclass
class HealthCheck:
    """Result of a health check."""

    name: str
    passed: bool
    severity: str  # "CRITICAL" | "WARNING" | "OK"
    message: str
    value: Optional[Any] = None
    threshold: Optional[Any] = None


class WatchdogMonitor:
    """
    Proactive health monitor with Discord alerting.
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        check_interval: float = DEFAULT_CHECK_INTERVAL,
    ) -> None:
        self.webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
        self.check_interval = check_interval
        self.alert_state = AlertState()
        self._shutdown_requested = False

        if not self.webhook_url:
            logger.warning("DISCORD_WEBHOOK_URL not set - alerts will be logged only")

    # =========================================================================
    # HEALTH CHECKS
    # =========================================================================

    def check_active_workers(self, conn: psycopg.Connection) -> HealthCheck:
        """Check if any workers have heartbeated in the last 5 minutes."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(DISTINCT worker_id) AS active_workers
                FROM ops.worker_heartbeats
                WHERE last_seen_at > NOW() - INTERVAL '%s minutes'
            """,
                (THRESHOLD_WORKER_HEARTBEAT_MINUTES,),
            )
            row = cur.fetchone()
            active = row["active_workers"] if row else 0

        if active == 0:
            return HealthCheck(
                name="active_workers",
                passed=False,
                severity="CRITICAL",
                message=f"No active workers in last {THRESHOLD_WORKER_HEARTBEAT_MINUTES} minutes",
                value=active,
                threshold=">= 1",
            )
        return HealthCheck(
            name="active_workers",
            passed=True,
            severity="OK",
            message=f"{active} workers active",
            value=active,
        )

    def check_queue_freshness(self, conn: psycopg.Connection) -> HealthCheck:
        """Check if the oldest pending job is too old."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    EXTRACT(EPOCH FROM (NOW() - MIN(created_at))) / 60 AS oldest_pending_minutes
                FROM ops.job_queue
                WHERE status = 'pending'
            """
            )
            row = cur.fetchone()
            oldest_minutes = (
                row["oldest_pending_minutes"] if row and row["oldest_pending_minutes"] else 0
            )

        if oldest_minutes > THRESHOLD_QUEUE_STALE_MINUTES:
            return HealthCheck(
                name="queue_freshness",
                passed=False,
                severity="WARNING",
                message=f"Oldest pending job is {oldest_minutes:.1f} minutes old",
                value=oldest_minutes,
                threshold=f"<= {THRESHOLD_QUEUE_STALE_MINUTES} min",
            )
        return HealthCheck(
            name="queue_freshness",
            passed=True,
            severity="OK",
            message=f"Queue is fresh (oldest: {oldest_minutes:.1f} min)",
            value=oldest_minutes,
        )

    def check_reaper_health(self, conn: psycopg.Connection) -> HealthCheck:
        """Check if the reaper has run recently."""
        with conn.cursor() as cur:
            # Check for recently reaped jobs (jobs with attempts > 0 and status = pending)
            cur.execute(
                """
                SELECT
                    MAX(updated_at) AS last_reap_time
                FROM ops.job_queue
                WHERE status = 'pending' AND attempts > 0
            """
            )
            row = cur.fetchone()
            last_reap = row["last_reap_time"] if row else None

        if last_reap is None:
            # No reaped jobs ever - check if reaper job exists in cron
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COUNT(*) as count FROM cron.job
                        WHERE jobname IN ('dragonfly_reaper', 'reap_stuck_jobs')
                    """
                    )
                    cron_row = cur.fetchone()
                    if cron_row and cron_row["count"] > 0:
                        return HealthCheck(
                            name="reaper_health",
                            passed=True,
                            severity="OK",
                            message="Reaper scheduled, no jobs to reap yet",
                        )
            except psycopg.errors.UndefinedTable:
                # cron schema doesn't exist - using Python fallback
                pass

            return HealthCheck(
                name="reaper_health",
                passed=True,
                severity="OK",
                message="No reaper activity (may be using Python fallback)",
            )

        # Calculate minutes since last reap
        minutes_since = (
            datetime.now(timezone.utc) - last_reap.replace(tzinfo=timezone.utc)
        ).total_seconds() / 60

        if minutes_since > THRESHOLD_REAPER_STALE_MINUTES:
            return HealthCheck(
                name="reaper_health",
                passed=False,
                severity="WARNING",
                message=f"Reaper hasn't run in {minutes_since:.1f} minutes",
                value=minutes_since,
                threshold=f"<= {THRESHOLD_REAPER_STALE_MINUTES} min",
            )
        return HealthCheck(
            name="reaper_health",
            passed=True,
            severity="OK",
            message=f"Reaper active (last: {minutes_since:.1f} min ago)",
            value=minutes_since,
        )

    def check_reaper_heartbeat(self, conn: psycopg.Connection) -> HealthCheck:
        """
        Check if reaper has written a heartbeat recently.

        The reaper must write to ops.reaper_heartbeat after each run.
        If the heartbeat is stale (> 20 min), this is CRITICAL because
        the reaper may be dead and stuck jobs won't be cleaned up.
        """
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        last_run_at,
                        jobs_reaped,
                        run_count,
                        status,
                        error_message,
                        EXTRACT(EPOCH FROM (NOW() - last_run_at)) / 60 AS minutes_since_last_run
                    FROM ops.reaper_heartbeat
                    WHERE id = 1
                """
                )
                row = cur.fetchone()
        except psycopg.errors.UndefinedTable:
            # Table doesn't exist yet - migration not applied
            return HealthCheck(
                name="reaper_heartbeat",
                passed=True,
                severity="OK",
                message="Reaper heartbeat table not yet deployed (migration pending)",
            )

        if row is None:
            return HealthCheck(
                name="reaper_heartbeat",
                passed=False,
                severity="CRITICAL",
                message="Reaper heartbeat missing - reaper has never run!",
            )

        minutes_since = row["minutes_since_last_run"]
        status = row["status"]
        jobs_reaped = row["jobs_reaped"]
        run_count = row["run_count"]
        error_message = row["error_message"]

        # Check for error status
        if status == "error":
            return HealthCheck(
                name="reaper_heartbeat",
                passed=False,
                severity="CRITICAL",
                message=f"Reaper last run failed: {error_message}",
                value=status,
            )

        # Check for stale heartbeat
        if minutes_since > THRESHOLD_REAPER_HEARTBEAT_MINUTES:
            return HealthCheck(
                name="reaper_heartbeat",
                passed=False,
                severity="CRITICAL",
                message=f"Reaper heartbeat stale ({minutes_since:.1f} min > {THRESHOLD_REAPER_HEARTBEAT_MINUTES} min threshold). Reaper may be dead!",
                value=minutes_since,
                threshold=f"<= {THRESHOLD_REAPER_HEARTBEAT_MINUTES} min",
            )

        return HealthCheck(
            name="reaper_heartbeat",
            passed=True,
            severity="OK",
            message=f"Reaper healthy (last: {minutes_since:.1f} min ago, runs: {run_count}, last reaped: {jobs_reaped})",
            value=minutes_since,
        )

    def check_error_rate(self, conn: psycopg.Connection) -> HealthCheck:
        """Check failure rate in the last 24 hours (Deadman Switch: Error Spike)."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                    COUNT(*) AS total
                FROM ops.job_queue
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            """
            )
            row = cur.fetchone()
            row["completed"] or 0
            failed = row["failed"] or 0
            total = row["total"] or 0

        if total == 0:
            return HealthCheck(
                name="error_rate_24h",
                passed=True,
                severity="OK",
                message="No jobs in last 24h",
                value=0.0,
            )

        failure_rate = (failed / total) * 100

        if failure_rate > THRESHOLD_ERROR_RATE_PERCENT:
            return HealthCheck(
                name="error_rate_24h",
                passed=False,
                severity="CRITICAL",
                message=f"Error Spike: {failure_rate:.1f}% failures ({failed}/{total} in 24h)",
                value=failure_rate,
                threshold=f"<= {THRESHOLD_ERROR_RATE_PERCENT}%",
            )
        return HealthCheck(
            name="error_rate_24h",
            passed=True,
            severity="OK",
            message=f"Error rate OK: {failure_rate:.1f}% (24h)",
            value=failure_rate,
        )

    def check_stuck_jobs(self, conn: psycopg.Connection) -> HealthCheck:
        """Check for jobs stuck in processing state."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS stuck_count
                FROM ops.job_queue
                WHERE status = 'processing'
                  AND started_at < NOW() - INTERVAL '15 minutes'
            """
            )
            row = cur.fetchone()
            stuck_count = row["stuck_count"] or 0

        if stuck_count > 0:
            return HealthCheck(
                name="stuck_jobs",
                passed=False,
                severity="CRITICAL",
                message=f"{stuck_count} jobs stuck in processing > 15 min",
                value=stuck_count,
                threshold="0",
            )
        return HealthCheck(
            name="stuck_jobs",
            passed=True,
            severity="OK",
            message="No stuck jobs",
            value=0,
        )

    def check_burn_rate(self, conn: psycopg.Connection) -> list[HealthCheck]:
        """
        Check failure burn rate across all domains.

        Burn rate = (failures in last 5 min - failures in previous 5 min) / previous failures

        This detects rapid failure acceleration rather than just high absolute counts.
        """
        results = []

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        domain,
                        failures_last_5min,
                        failures_prev_5min,
                        burn_rate_pct
                    FROM ops.v_audit_burn_rate
                    WHERE failures_last_5min > 0
                """
                )

                for row in cur.fetchall():
                    domain = row["domain"]
                    failures_now = row["failures_last_5min"]
                    failures_prev = row["failures_prev_5min"]
                    burn_rate = row["burn_rate_pct"] or 0

                    if burn_rate >= BURN_RATE_CRITICAL_THRESHOLD:
                        results.append(
                            HealthCheck(
                                name=f"burn_rate_{domain}",
                                passed=False,
                                severity="CRITICAL",
                                message=f"🔥 High Burn Rate [{domain}]: {burn_rate:.0f}% increase ({failures_prev} → {failures_now} failures in 5 min)",
                                value=burn_rate,
                                threshold=f"< {BURN_RATE_CRITICAL_THRESHOLD}%",
                            )
                        )
                    elif burn_rate >= BURN_RATE_WARNING_THRESHOLD:
                        results.append(
                            HealthCheck(
                                name=f"burn_rate_{domain}",
                                passed=False,
                                severity="WARNING",
                                message=f"⚠️ Elevated Burn Rate [{domain}]: {burn_rate:.0f}% increase ({failures_prev} → {failures_now} failures in 5 min)",
                                value=burn_rate,
                                threshold=f"< {BURN_RATE_WARNING_THRESHOLD}%",
                            )
                        )

        except psycopg.errors.UndefinedTable:
            # View doesn't exist yet (migration not applied)
            logger.debug("ops.v_audit_burn_rate not yet deployed")
        except Exception as e:
            logger.warning(f"Burn rate check failed: {e}")

        return results

    # =========================================================================
    # RUN ALL CHECKS
    # =========================================================================

    def run_all_checks(self) -> list[HealthCheck]:
        """Run all health checks and return results."""
        results = []
        try:
            with get_db_connection(use_pooler=True) as conn:
                results.append(self.check_active_workers(conn))
                results.append(self.check_queue_freshness(conn))
                results.append(self.check_reaper_health(conn))
                results.append(self.check_reaper_heartbeat(conn))
                results.append(self.check_error_rate(conn))
                results.append(self.check_stuck_jobs(conn))
                # Add burn rate checks (can return multiple)
                results.extend(self.check_burn_rate(conn))
        except (DatabaseOutageError, PoolerUnavailableError) as e:
            # WATCHDOG BLIND: Database is unreachable after retries
            logger.critical(f"🔴 WATCHDOG BLIND: Database unreachable after {e.attempts} attempts")
            results.append(
                HealthCheck(
                    name="watchdog_blind",
                    passed=False,
                    severity="CRITICAL",
                    message=f"WATCHDOG BLIND: Database unreachable after {e.attempts} retries. Monitoring unavailable!",
                )
            )
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            results.append(
                HealthCheck(
                    name="db_connection",
                    passed=False,
                    severity="CRITICAL",
                    message=f"Database unavailable: {str(e)[:100]}",
                )
            )
        return results

    # =========================================================================
    # ALERTING
    # =========================================================================

    def _get_runbook_url(self, check_name: str) -> str | None:
        """Get the runbook URL for a check type."""
        # Handle burn rate checks with domain suffix
        if check_name.startswith("burn_rate_"):
            return RUNBOOKS.get("burn_rate")
        return RUNBOOKS.get(check_name)

    def _build_discord_payload(self, checks: list[HealthCheck]) -> dict:
        """Build a Discord webhook payload with runbook links."""
        failed = [c for c in checks if not c.passed]

        # Determine overall color and title based on severity
        has_critical = any(c.severity == "CRITICAL" for c in failed)
        has_burn_rate = any("burn_rate" in c.name for c in failed)

        color = 0xFF0000 if has_critical else 0xFFAA00  # Red or Orange

        if has_burn_rate and has_critical:
            title = "🔥 High Burn Rate Alert"
            description = "Failure rate is accelerating rapidly. Immediate action required."
        elif has_critical:
            title = "🚨 Critical System Alert"
            description = "One or more critical systems are failing."
        else:
            title = "⚠️ Dragonfly Watchdog Warning"
            description = "System health issues detected."

        # Build embed
        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fields": [],
        }

        for check in failed:
            emoji = "🔴" if check.severity == "CRITICAL" else "🟠"

            # Build field value with runbook link
            field_value = check.message
            runbook_url = self._get_runbook_url(check.name)
            if runbook_url:
                field_value += f"\n[📖 Open Runbook]({runbook_url})"

            embed["fields"].append(
                {
                    "name": f"{emoji} {check.name.replace('_', ' ').title()}",
                    "value": field_value,
                    "inline": False,  # Full width for runbook links
                }
            )

        env = os.environ.get("SUPABASE_MODE", "unknown").upper()
        embed["footer"] = {"text": f"Environment: {env} | Watchdog v2.0"}

        return {
            "username": "Dragonfly Watchdog",
            "embeds": [embed],
        }

    def send_discord_alert(self, checks: list[HealthCheck]) -> bool:
        """Send alert to Discord webhook."""
        if not self.webhook_url:
            logger.warning("No Discord webhook configured")
            return False

        payload = self._build_discord_payload(checks)

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            logger.info("Discord alert sent successfully")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to send Discord alert: {e}")
            return False

    def process_alerts(self, checks: list[HealthCheck]) -> None:
        """Process check results and send alerts if needed (with debouncing)."""
        failed = [c for c in checks if not c.passed]
        passed = [c for c in checks if c.passed]

        # Clear alert state for recovered issues
        for check in passed:
            if check.name in self.alert_state.last_alert_times:
                logger.info(f"Issue resolved: {check.name}")
                self.alert_state.clear(check.name)

        if not failed:
            logger.info("All health checks passed")
            return

        # Check which alerts can be sent (debouncing)
        alertable = []
        for check in failed:
            if self.alert_state.can_alert(check.name):
                alertable.append(check)
                self.alert_state.mark_alerted(check.name)
            else:
                logger.debug(f"Debounced alert for {check.name}")

        if alertable:
            logger.warning(f"Sending alerts for: {[c.name for c in alertable]}")
            self.send_discord_alert(alertable)

        # Log all failures
        for check in failed:
            log_fn = logger.critical if check.severity == "CRITICAL" else logger.warning
            log_fn(f"[{check.severity}] {check.name}: {check.message}")

    # =========================================================================
    # MAIN LOOP
    # =========================================================================

    def run_once(self) -> int:
        """Run a single check cycle."""
        logger.info("Running health checks...")
        checks = self.run_all_checks()
        self.process_alerts(checks)

        # Return exit code based on results
        has_critical = any(c.severity == "CRITICAL" and not c.passed for c in checks)
        return 1 if has_critical else 0

    def run_loop(self) -> int:
        """Run continuous monitoring loop."""
        logger.info(f"Starting watchdog (interval: {self.check_interval}s)")

        def handle_shutdown(signum, frame):
            logger.info("Shutdown signal received")
            self._shutdown_requested = True

        signal.signal(signal.SIGTERM, handle_shutdown)
        signal.signal(signal.SIGINT, handle_shutdown)

        while not self._shutdown_requested:
            try:
                self.run_once()
            except Exception as e:
                logger.exception(f"Error in watchdog loop: {e}")

            # Sleep in small increments to allow clean shutdown
            for _ in range(int(self.check_interval)):
                if self._shutdown_requested:
                    break
                time.sleep(1)

        logger.info("Watchdog shutdown complete")
        return 0


# =============================================================================
# CLI
# =============================================================================


@click.command()
@click.option("--once", is_flag=True, help="Run once and exit")
@click.option("--interval", default=DEFAULT_CHECK_INTERVAL, help="Check interval in seconds")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def main(once: bool, interval: int, verbose: bool) -> None:
    """Dragonfly Watchdog - Proactive Health Monitoring"""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    watchdog = WatchdogMonitor(check_interval=interval)

    if once:
        exit_code = watchdog.run_once()
    else:
        exit_code = watchdog.run_loop()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
