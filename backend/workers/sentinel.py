"""
═══════════════════════════════════════════════════════════════════════════
backend/workers/sentinel.py - SRE Pipeline Health Monitor
═══════════════════════════════════════════════════════════════════════════

Purpose:
    Automated health monitoring for the Dragonfly ingestion engine.
    Detects stuck batches, error spikes, and PostgREST schema cache issues.

Checks Performed:
    1. STUCK BATCHES: Any batch in processing states for > 10 minutes
    2. ERROR SPIKES: Hourly error rate exceeds 15% threshold
    3. SCHEMA CACHE: PostgREST PGRST002 errors (auto-reloads schema)

Usage:
    # Run health check (dev)
    SUPABASE_MODE=dev python -m backend.workers.sentinel

    # Run continuously (cron/systemd)
    SUPABASE_MODE=prod python -m backend.workers.sentinel --loop --interval 300

    # JSON output for alerting integrations
    SUPABASE_MODE=prod python -m backend.workers.sentinel --json

Exit Codes:
    0 = Healthy
    1 = Warning (degraded but operational)
    2 = Critical (requires immediate attention)

Alerting Integration:
    - Stdout: JSON health summary for log aggregators
    - Exit code: For cron job alerting
    - Future: Discord webhook for CRITICAL alerts

Author: Dragonfly SRE Team
Created: 2025-01-04
═══════════════════════════════════════════════════════════════════════════
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import httpx

from src.supabase_client import create_supabase_client, get_supabase_env

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

STUCK_BATCH_THRESHOLD_MINUTES = 10
ERROR_SPIKE_THRESHOLD_PCT = 15.0
SCHEMA_CACHE_TIMEOUT_SECONDS = 5

# ═══════════════════════════════════════════════════════════════════════════
# TYPES
# ═══════════════════════════════════════════════════════════════════════════


class HealthStatus(str, Enum):
    """Overall system health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"


class AlertLevel(str, Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """Individual health check alert."""

    check: str  # e.g., "stuck_batches"
    level: AlertLevel
    message: str
    details: dict[str, Any] | None = None


@dataclass
class HealthReport:
    """Complete health check report."""

    timestamp: str
    environment: str
    overall_status: HealthStatus
    alerts: list[Alert]
    metrics: dict[str, Any]

    def to_json(self, pretty: bool = False) -> str:
        """Serialize to JSON string."""
        data = asdict(self)
        # Convert enums to strings
        data["overall_status"] = self.overall_status.value
        data["alerts"] = [
            {
                "check": a.check,
                "level": a.level.value,
                "message": a.message,
                "details": a.details,
            }
            for a in self.alerts
        ]
        if pretty:
            return json.dumps(data, indent=2, default=str)
        return json.dumps(data, default=str)


# ═══════════════════════════════════════════════════════════════════════════
# HEALTH CHECKS
# ═══════════════════════════════════════════════════════════════════════════


def check_stuck_batches(sb: Any, logger: logging.Logger) -> Alert | None:
    """
    Check for batches stuck in processing states.

    Returns Alert if any batch has been processing for > 10 minutes.
    """
    try:
        # Query ops.v_pipeline_health view
        result = (
            sb.schema("ops")
            .table("v_pipeline_health")
            .select("*")
            .in_(
                "status",
                [
                    "uploaded",
                    "staging",
                    "validating",
                    "transforming",
                    "inserting",
                    "upserting",
                    "processing",
                ],
            )
            .execute()
        )

        if not result.data:
            logger.info("[stuck_batches] No batches in processing states")
            return None

        stuck = [
            b for b in result.data if b.get("oldest_age_minutes", 0) > STUCK_BATCH_THRESHOLD_MINUTES
        ]

        if stuck:
            total_stuck = sum(b.get("batch_count", 0) for b in stuck)
            statuses = ", ".join(f"{b['status']}({b['batch_count']})" for b in stuck)

            return Alert(
                check="stuck_batches",
                level=AlertLevel.CRITICAL,
                message=f"{total_stuck} batches stuck > {STUCK_BATCH_THRESHOLD_MINUTES}m: {statuses}",
                details={
                    "stuck_batches": stuck,
                    "threshold_minutes": STUCK_BATCH_THRESHOLD_MINUTES,
                },
            )

        logger.info(f"[stuck_batches] {len(result.data)} processing states, none stuck")
        return None

    except Exception as e:
        logger.error(f"[stuck_batches] Check failed: {e}")
        return Alert(
            check="stuck_batches",
            level=AlertLevel.CRITICAL,
            message=f"Health check failed: {e}",
            details={"error": str(e)},
        )


def check_error_spike(sb: Any, logger: logging.Logger) -> Alert | None:
    """
    Check for error rate spikes in the last hour.

    Returns Alert if error rate exceeds 15% threshold.
    """
    try:
        # Query last hour's performance from ops.v_batch_performance
        result = (
            sb.schema("ops")
            .table("v_batch_performance")
            .select("*")
            .order("hour_bucket", desc=True)
            .limit(1)
            .execute()
        )

        if not result.data:
            logger.info("[error_spike] No recent batch data")
            return None

        last_hour = result.data[0]
        error_rate = last_hour.get("error_rate_pct", 0.0)

        if error_rate > ERROR_SPIKE_THRESHOLD_PCT:
            return Alert(
                check="error_spike",
                level=AlertLevel.WARNING,
                message=f"Error rate {error_rate:.1f}% > {ERROR_SPIKE_THRESHOLD_PCT}% threshold",
                details={
                    "error_rate_pct": error_rate,
                    "threshold_pct": ERROR_SPIKE_THRESHOLD_PCT,
                    "hour_bucket": last_hour.get("hour_bucket"),
                    "error_rows": last_hour.get("error_rows", 0),
                    "total_rows": last_hour.get("total_rows", 0),
                },
            )

        logger.info(f"[error_spike] Last hour error rate: {error_rate:.1f}%")
        return None

    except Exception as e:
        logger.error(f"[error_spike] Check failed: {e}")
        return Alert(
            check="error_spike",
            level=AlertLevel.WARNING,
            message=f"Health check failed: {e}",
            details={"error": str(e)},
        )


def check_schema_cache(sb: Any, logger: logging.Logger) -> Alert | None:
    """
    Check for PostgREST schema cache errors (PGRST002).

    Attempts to query a view. If PGRST002 is detected, sends NOTIFY to reload schema.
    """
    try:
        # Test query to intake.simplicity_batches to detect PGRST002
        sb.schema("intake").table("simplicity_batches").select("id").limit(1).execute()

        logger.info("[schema_cache] PostgREST responding normally")
        return None

    except Exception as e:
        error_str = str(e)

        # Check if it's a PGRST002 schema cache error
        if "PGRST002" in error_str or "schema cache" in error_str.lower():
            logger.warning(f"[schema_cache] PGRST002 detected: {error_str}")

            # Attempt auto-reload via NOTIFY (requires direct DB connection)
            try:
                import asyncpg

                from src.supabase_client import get_supabase_db_url

                db_url = get_supabase_db_url()

                async def reload_schema():
                    conn = await asyncpg.connect(db_url)
                    await conn.execute("NOTIFY pgrst, 'reload'")
                    await conn.close()

                import asyncio

                asyncio.run(reload_schema())

                logger.info("[schema_cache] Sent NOTIFY pgrst, 'reload' - schema reloading")

                return Alert(
                    check="schema_cache",
                    level=AlertLevel.WARNING,
                    message="PGRST002 detected - auto-reload triggered",
                    details={
                        "error": error_str,
                        "action_taken": "NOTIFY pgrst, 'reload'",
                    },
                )

            except Exception as reload_err:
                logger.error(f"[schema_cache] Auto-reload failed: {reload_err}")
                return Alert(
                    check="schema_cache",
                    level=AlertLevel.CRITICAL,
                    message=f"PGRST002 detected - auto-reload failed: {reload_err}",
                    details={
                        "error": error_str,
                        "reload_error": str(reload_err),
                    },
                )

        # Other PostgREST errors
        logger.error(f"[schema_cache] PostgREST error: {e}")
        return Alert(
            check="schema_cache",
            level=AlertLevel.WARNING,
            message=f"PostgREST query failed: {e}",
            details={"error": error_str},
        )


# ═══════════════════════════════════════════════════════════════════════════
# MAIN SENTINEL LOGIC
# ═══════════════════════════════════════════════════════════════════════════


def run_health_checks(logger: logging.Logger) -> HealthReport:
    """
    Execute all health checks and compile a report.

    Returns:
        HealthReport with overall status and alerts
    """
    env = get_supabase_env()
    sb = create_supabase_client()

    alerts: list[Alert] = []
    metrics: dict[str, Any] = {}

    # Check 1: Stuck Batches
    logger.info("Running stuck_batches check...")
    alert = check_stuck_batches(sb, logger)
    if alert:
        alerts.append(alert)

    # Check 2: Error Spikes
    logger.info("Running error_spike check...")
    alert = check_error_spike(sb, logger)
    if alert:
        alerts.append(alert)

    # Check 3: Schema Cache
    logger.info("Running schema_cache check...")
    alert = check_schema_cache(sb, logger)
    if alert:
        alerts.append(alert)

    # Determine overall status
    if any(a.level == AlertLevel.CRITICAL for a in alerts):
        overall_status = HealthStatus.CRITICAL
    elif any(a.level == AlertLevel.WARNING for a in alerts):
        overall_status = HealthStatus.DEGRADED
    else:
        overall_status = HealthStatus.HEALTHY

    # Compile metrics
    metrics = {
        "total_checks": 3,
        "alerts_triggered": len(alerts),
        "critical_alerts": sum(1 for a in alerts if a.level == AlertLevel.CRITICAL),
        "warning_alerts": sum(1 for a in alerts if a.level == AlertLevel.WARNING),
    }

    return HealthReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        environment=env,
        overall_status=overall_status,
        alerts=alerts,
        metrics=metrics,
    )


def main():
    """CLI entry point for Sentinel."""
    parser = argparse.ArgumentParser(
        description="Dragonfly Pipeline Health Monitor (Sentinel)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # One-time health check (dev)
  SUPABASE_MODE=dev python -m backend.workers.sentinel

  # Continuous monitoring (prod)
  SUPABASE_MODE=prod python -m backend.workers.sentinel --loop --interval 300

  # JSON output for log aggregators
  SUPABASE_MODE=prod python -m backend.workers.sentinel --json
        """,
    )
    parser.add_argument(
        "--json", action="store_true", help="Output JSON instead of human-readable logs"
    )
    parser.add_argument("--loop", action="store_true", help="Run continuously (for daemonization)")
    parser.add_argument(
        "--interval", type=int, default=300, help="Loop interval in seconds (default: 300)"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    if args.json:
        # Suppress logs in JSON mode (only output JSON to stdout)
        logging.basicConfig(level=logging.CRITICAL, format=log_format)
    else:
        logging.basicConfig(level=log_level, format=log_format)

    logger = logging.getLogger("sentinel")

    try:
        if args.loop:
            logger.info(f"Sentinel starting in loop mode (interval={args.interval}s)")
            while True:
                report = run_health_checks(logger)

                if args.json:
                    print(report.to_json())
                else:
                    print_human_report(report, logger)

                time.sleep(args.interval)
        else:
            # Single run
            report = run_health_checks(logger)

            if args.json:
                print(report.to_json(pretty=True))
            else:
                print_human_report(report, logger)

            # Exit with appropriate code
            if report.overall_status == HealthStatus.CRITICAL:
                sys.exit(2)
            elif report.overall_status == HealthStatus.DEGRADED:
                sys.exit(1)
            else:
                sys.exit(0)

    except KeyboardInterrupt:
        logger.info("Sentinel stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Sentinel crashed: {e}")
        sys.exit(2)


def print_human_report(report: HealthReport, logger: logging.Logger):
    """Print a human-readable health report."""
    status_icons = {
        HealthStatus.HEALTHY: "✅",
        HealthStatus.DEGRADED: "⚠️",
        HealthStatus.CRITICAL: "🔴",
    }

    icon = status_icons[report.overall_status]
    logger.info("=" * 80)
    logger.info(f"{icon} HEALTH CHECK COMPLETE - Status: {report.overall_status.value.upper()}")
    logger.info(f"Environment: {report.environment}")
    logger.info(f"Timestamp: {report.timestamp}")
    logger.info("=" * 80)

    if report.alerts:
        logger.info(f"Alerts Triggered: {len(report.alerts)}")
        for alert in report.alerts:
            level_icon = "🔴" if alert.level == AlertLevel.CRITICAL else "⚠️"
            logger.log(
                logging.CRITICAL if alert.level == AlertLevel.CRITICAL else logging.WARNING,
                f"{level_icon} [{alert.check}] {alert.message}",
            )
            if alert.details:
                logger.debug(f"   Details: {json.dumps(alert.details, indent=2, default=str)}")
    else:
        logger.info("✅ No alerts - all systems operational")

    logger.info("=" * 80)
    logger.info(f"Metrics: {json.dumps(report.metrics, indent=2)}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
