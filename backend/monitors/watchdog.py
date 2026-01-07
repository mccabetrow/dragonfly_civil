#!/usr/bin/env python3
"""
Dragonfly Civil - Platform Watchdog Service

The single source of truth for platform health. Enforces Hard SLOs and
processes DLQ alerts automatically with intelligent auto-triage.

SLOs Enforced:
  - MAX_QUEUE_AGE_SEC: 300s (5 min) - Queue traffic jam threshold
  - MAX_WORKER_SILENCE_SEC: 90s (1.5 min) - Worker staleness threshold
  - API_LATENCY_THRESHOLD_MS: 1000ms (1 sec) - API degradation threshold

Usage:
    python -m backend.monitors.watchdog
    python -m backend.monitors.watchdog --once  # Single iteration
    python -m backend.monitors.watchdog --env prod

Author: Principal Site Reliability Engineer
Date: 2026-01-07
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION - Hard SLOs
# ═══════════════════════════════════════════════════════════════════════════════

# Queue SLOs
MAX_QUEUE_AGE_SEC = 300  # 5 minutes - queue traffic jam threshold
QUEUE_WARNING_SEC = 180  # 3 minutes - early warning

# Worker SLOs
MAX_WORKER_SILENCE_SEC = 90  # 1.5 minutes - worker stale
WORKER_DEAD_SEC = 900  # 15 minutes - worker dead

# API SLOs
API_LATENCY_THRESHOLD_MS = 1000  # 1 second
API_TIMEOUT_SEC = 5  # Hard timeout for health check

# DLQ Configuration
DLQ_QUEUE_NAME = "q_dead_letter"
DLQ_PEEK_LIMIT = 5  # Top N messages to inspect for auto-triage

# Loop Configuration
LOOP_INTERVAL_SEC = 60  # Run every 60 seconds


# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class AlertSeverity(Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    FATAL = "fatal"


class CheckStatus(Enum):
    """Health check result status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class Alert:
    """Represents a platform alert."""

    severity: AlertSeverity
    category: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:
        icons = {
            AlertSeverity.INFO: "ℹ️",
            AlertSeverity.WARNING: "⚠️",
            AlertSeverity.CRITICAL: "🔥",
            AlertSeverity.FATAL: "💀",
        }
        icon = icons.get(self.severity, "❓")
        return f"{icon} [{self.category}] {self.message}"


@dataclass
class CheckResult:
    """Result of a health check."""

    name: str
    status: CheckStatus
    message: str
    alerts: list[Alert] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


@dataclass
class WatchdogReport:
    """Complete watchdog iteration report."""

    timestamp: datetime
    env: str
    checks: list[CheckResult]
    overall_status: CheckStatus
    duration_ms: float
    iteration: int


# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING SETUP
# ═══════════════════════════════════════════════════════════════════════════════


def setup_logging() -> logging.Logger:
    """Configure structured logging for watchdog."""
    logger = logging.getLogger("watchdog")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)

    return logger


log = setup_logging()


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE CONNECTION
# ═══════════════════════════════════════════════════════════════════════════════


def get_db_url(env: str) -> str:
    """Get database URL for the specified environment."""
    env_file = PROJECT_ROOT / f".env.{env}"
    if env_file.exists():
        load_dotenv(env_file, override=True)

    # Prefer service role connection for monitoring
    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("SUPABASE_MIGRATE_DB_URL")
    if not db_url:
        raise ValueError(f"No database URL found for env '{env}'")

    return db_url


def get_api_base_url(env: str) -> str:
    """Get API base URL for health checks."""
    env_file = PROJECT_ROOT / f".env.{env}"
    if env_file.exists():
        load_dotenv(env_file, override=True)

    # For local dev, use localhost; for deployed, use Supabase URL
    supabase_url = os.getenv("SUPABASE_URL", "")
    if "localhost" in supabase_url or env == "dev":
        return os.getenv("API_BASE_URL", "http://localhost:8000")
    return supabase_url


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 1: WORKER LIVENESS (Heartbeats)
# ═══════════════════════════════════════════════════════════════════════════════


def check_worker_liveness(conn: psycopg.Connection) -> CheckResult:
    """
    Check worker heartbeat freshness.

    SLOs:
      - last_heartbeat < 90s ago: Worker is alive
      - last_heartbeat < 15m ago: Worker is stale (⚠️)
      - last_heartbeat > 15m ago: Worker is dead (💀)
    """
    start = time.perf_counter()
    alerts: list[Alert] = []
    metrics: dict[str, Any] = {
        "workers_total": 0,
        "workers_alive": 0,
        "workers_stale": 0,
        "workers_dead": 0,
    }

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            # Check if workers.heartbeats table exists
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'workers' AND table_name = 'heartbeats'
                )
                """
            )
            if not cur.fetchone()["exists"]:
                return CheckResult(
                    name="Worker Liveness",
                    status=CheckStatus.UNKNOWN,
                    message="workers.heartbeats table not found",
                    duration_ms=(time.perf_counter() - start) * 1000,
                )

            # Fetch all worker heartbeats
            cur.execute(
                """
                SELECT
                    worker_id,
                    queue_name,
                    hostname,
                    status,
                    last_heartbeat_at,
                    EXTRACT(EPOCH FROM (NOW() - last_heartbeat_at)) AS age_seconds
                FROM workers.heartbeats
                ORDER BY last_heartbeat_at DESC
                """
            )
            workers = cur.fetchall()

            metrics["workers_total"] = len(workers)

            for worker in workers:
                age_sec = worker["age_seconds"] or 0
                worker_id = str(worker["worker_id"])[:8]
                worker_type = worker.get("queue_name", "unknown")

                if age_sec > WORKER_DEAD_SEC:
                    # Worker is DEAD
                    metrics["workers_dead"] += 1
                    alerts.append(
                        Alert(
                            severity=AlertSeverity.FATAL,
                            category="Worker",
                            message=f"💀 Worker Dead: {worker_type} ({worker_id})",
                            details={
                                "worker_id": worker_id,
                                "worker_type": worker_type,
                                "last_heartbeat": str(worker["last_heartbeat_at"]),
                                "age_minutes": round(age_sec / 60, 1),
                            },
                        )
                    )
                elif age_sec > MAX_WORKER_SILENCE_SEC:
                    # Worker is STALE
                    metrics["workers_stale"] += 1
                    alerts.append(
                        Alert(
                            severity=AlertSeverity.WARNING,
                            category="Worker",
                            message=f"⚠️ Worker Stale: {worker_type} ({worker_id})",
                            details={
                                "worker_id": worker_id,
                                "worker_type": worker_type,
                                "last_heartbeat": str(worker["last_heartbeat_at"]),
                                "age_seconds": round(age_sec, 1),
                            },
                        )
                    )
                else:
                    # Worker is ALIVE
                    metrics["workers_alive"] += 1

        # Determine overall status
        if metrics["workers_dead"] > 0:
            status = CheckStatus.UNHEALTHY
            message = f"{metrics['workers_dead']} dead worker(s)"
        elif metrics["workers_stale"] > 0:
            status = CheckStatus.DEGRADED
            message = f"{metrics['workers_stale']} stale worker(s)"
        elif metrics["workers_total"] == 0:
            status = CheckStatus.UNKNOWN
            message = "No workers registered"
        else:
            status = CheckStatus.HEALTHY
            message = f"{metrics['workers_alive']}/{metrics['workers_total']} workers alive"

        return CheckResult(
            name="Worker Liveness",
            status=status,
            message=message,
            alerts=alerts,
            metrics=metrics,
            duration_ms=(time.perf_counter() - start) * 1000,
        )

    except Exception as e:
        return CheckResult(
            name="Worker Liveness",
            status=CheckStatus.UNKNOWN,
            message=f"Error: {e}",
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 2: QUEUE FRESHNESS (SLO)
# ═══════════════════════════════════════════════════════════════════════════════


def check_queue_freshness(conn: psycopg.Connection) -> CheckResult:
    """
    Check queue message age against SLO.

    SLO: oldest_msg_age > 300s = Queue Traffic Jam
    """
    start = time.perf_counter()
    alerts: list[Alert] = []
    metrics: dict[str, Any] = {"queues_checked": 0, "max_age_seconds": 0, "total_depth": 0}

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            # Check if pgmq extension is available
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_extension WHERE extname = 'pgmq'
                )
                """
            )
            if not cur.fetchone()["exists"]:
                return CheckResult(
                    name="Queue Freshness",
                    status=CheckStatus.UNKNOWN,
                    message="pgmq extension not installed",
                    duration_ms=(time.perf_counter() - start) * 1000,
                )

            # Get queue metrics using pgmq.metrics_all()
            try:
                cur.execute("SELECT * FROM pgmq.metrics_all()")
                queues = cur.fetchall()
            except Exception:
                # Fallback: query pgmq.meta for queue names
                cur.execute("SELECT queue_name FROM pgmq.meta")
                queue_names = [r["queue_name"] for r in cur.fetchall()]
                queues = []
                for qname in queue_names:
                    try:
                        cur.execute("SELECT * FROM pgmq.metrics(%s)", (qname,))
                        q = cur.fetchone()
                        if q:
                            queues.append(q)
                    except Exception:
                        pass

            metrics["queues_checked"] = len(queues)

            for queue in queues:
                queue_name = queue.get("queue_name", "unknown")
                oldest_msg_age = queue.get("oldest_msg_age_sec") or 0
                queue_depth = queue.get("queue_length") or queue.get("total_messages") or 0

                metrics["total_depth"] += queue_depth
                if oldest_msg_age > metrics["max_age_seconds"]:
                    metrics["max_age_seconds"] = oldest_msg_age

                # Check SLO violation
                if oldest_msg_age > MAX_QUEUE_AGE_SEC:
                    alerts.append(
                        Alert(
                            severity=AlertSeverity.CRITICAL,
                            category="Queue",
                            message=f"🐢 Queue Traffic Jam: {queue_name}",
                            details={
                                "queue_name": queue_name,
                                "oldest_msg_age_sec": round(oldest_msg_age, 1),
                                "slo_threshold_sec": MAX_QUEUE_AGE_SEC,
                                "queue_depth": queue_depth,
                            },
                        )
                    )
                elif oldest_msg_age > QUEUE_WARNING_SEC:
                    alerts.append(
                        Alert(
                            severity=AlertSeverity.WARNING,
                            category="Queue",
                            message=f"⏳ Queue Slowing: {queue_name}",
                            details={
                                "queue_name": queue_name,
                                "oldest_msg_age_sec": round(oldest_msg_age, 1),
                                "queue_depth": queue_depth,
                            },
                        )
                    )

        # Determine status
        critical_count = sum(1 for a in alerts if a.severity == AlertSeverity.CRITICAL)
        warning_count = sum(1 for a in alerts if a.severity == AlertSeverity.WARNING)

        if critical_count > 0:
            status = CheckStatus.UNHEALTHY
            message = f"{critical_count} queue(s) in traffic jam"
        elif warning_count > 0:
            status = CheckStatus.DEGRADED
            message = f"{warning_count} queue(s) slowing"
        else:
            status = CheckStatus.HEALTHY
            message = f"{metrics['queues_checked']} queues healthy, depth={metrics['total_depth']}"

        return CheckResult(
            name="Queue Freshness",
            status=status,
            message=message,
            alerts=alerts,
            metrics=metrics,
            duration_ms=(time.perf_counter() - start) * 1000,
        )

    except Exception as e:
        return CheckResult(
            name="Queue Freshness",
            status=CheckStatus.UNKNOWN,
            message=f"Error: {e}",
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 3: DLQ DISCIPLINE (Truth Serum)
# ═══════════════════════════════════════════════════════════════════════════════

# Auto-triage patterns for DLQ messages
DLQ_TRIAGE_PATTERNS = {
    # Security incidents
    "security": [
        re.compile(r"authorization\s*(failed|denied|error)", re.IGNORECASE),
        re.compile(r"authentication\s*(failed|denied|error)", re.IGNORECASE),
        re.compile(r"unauthorized\s*(access|attempt|request)", re.IGNORECASE),
        re.compile(r"invalid\s*token", re.IGNORECASE),
        re.compile(r"forbidden", re.IGNORECASE),
        re.compile(r"access\s*denied", re.IGNORECASE),
        re.compile(r"invalid\s*envelope", re.IGNORECASE),
        re.compile(r"signature\s*(invalid|mismatch)", re.IGNORECASE),
    ],
    # Compliance blocks -> Remediation tasks
    "compliance": [
        re.compile(r"compliance\s*block", re.IGNORECASE),
        re.compile(r"consent\s*(missing|required|not\s*found)", re.IGNORECASE),
        re.compile(r"fcra\s*(violation|block)", re.IGNORECASE),
        re.compile(r"fdcpa\s*(violation|block)", re.IGNORECASE),
        re.compile(r"authorization\s*required", re.IGNORECASE),
        re.compile(r"legal\s*hold", re.IGNORECASE),
    ],
}


def triage_dlq_message(msg: dict) -> tuple[str | None, dict[str, Any]]:
    """
    Auto-triage a DLQ message based on payload patterns.

    Returns:
        (category, details) where category is 'security', 'compliance', or None
    """
    # Extract message content for pattern matching
    payload = msg.get("message", {})
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            pass

    # Build searchable text from message
    search_text = json.dumps(payload) if isinstance(payload, dict) else str(payload)
    error_text = str(msg.get("error", ""))
    search_text = f"{search_text} {error_text}"

    # Check security patterns
    for pattern in DLQ_TRIAGE_PATTERNS["security"]:
        if pattern.search(search_text):
            return "security", {
                "pattern_matched": pattern.pattern,
                "msg_id": msg.get("msg_id"),
                "error": error_text[:500],
            }

    # Check compliance patterns
    for pattern in DLQ_TRIAGE_PATTERNS["compliance"]:
        if pattern.search(search_text):
            return "compliance", {
                "pattern_matched": pattern.pattern,
                "msg_id": msg.get("msg_id"),
                "error": error_text[:500],
            }

    return None, {}


def check_dlq_discipline(conn: psycopg.Connection) -> CheckResult:
    """
    Check Dead Letter Queue depth and auto-triage failed messages.

    Actions:
      - Alert if DLQ has messages
      - Auto-triage top N messages
      - Insert security.incidents for auth failures
      - Insert public.tasks for compliance blocks
    """
    start = time.perf_counter()
    alerts: list[Alert] = []
    metrics: dict[str, Any] = {
        "dlq_depth": 0,
        "security_incidents": 0,
        "remediation_tasks": 0,
        "unclassified": 0,
    }

    try:
        with conn.cursor(row_factory=dict_row) as cur:
            # Check if DLQ exists
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM pgmq.meta WHERE queue_name = %s)", (DLQ_QUEUE_NAME,)
            )
            if not cur.fetchone()["exists"]:
                return CheckResult(
                    name="DLQ Discipline",
                    status=CheckStatus.HEALTHY,
                    message="DLQ not configured (OK)",
                    duration_ms=(time.perf_counter() - start) * 1000,
                )

            # Get DLQ depth
            try:
                cur.execute("SELECT * FROM pgmq.metrics(%s)", (DLQ_QUEUE_NAME,))
                dlq_metrics = cur.fetchone()
                dlq_depth = dlq_metrics.get("queue_length", 0) if dlq_metrics else 0
            except Exception:
                dlq_depth = 0

            metrics["dlq_depth"] = dlq_depth

            if dlq_depth == 0:
                return CheckResult(
                    name="DLQ Discipline",
                    status=CheckStatus.HEALTHY,
                    message="DLQ empty - all clear",
                    metrics=metrics,
                    duration_ms=(time.perf_counter() - start) * 1000,
                )

            # Alert: DLQ has messages
            alerts.append(
                Alert(
                    severity=AlertSeverity.WARNING,
                    category="DLQ",
                    message=f"📬 DLQ has {dlq_depth} failed job(s)",
                    details={"queue_name": DLQ_QUEUE_NAME, "depth": dlq_depth},
                )
            )

            # Peek top N messages for auto-triage
            try:
                cur.execute("SELECT * FROM pgmq.read(%s, 0, %s)", (DLQ_QUEUE_NAME, DLQ_PEEK_LIMIT))
                messages = cur.fetchall()
            except Exception:
                messages = []

            # Auto-triage each message
            for msg in messages:
                category, details = triage_dlq_message(msg)

                if category == "security":
                    # Insert security incident
                    metrics["security_incidents"] += 1
                    try:
                        cur.execute(
                            """
                            INSERT INTO security.incidents (
                                event_type, severity, metadata, ts
                            ) VALUES (
                                'dlq_security_alert', 'critical', %s, NOW()
                            )
                            RETURNING id
                            """,
                            (json.dumps(details),),
                        )
                        incident = cur.fetchone()
                        if incident:
                            log.info(f"  🚨 Created security incident: {incident['id']}")
                    except Exception as e:
                        log.warning(f"Failed to create security incident: {e}")

                elif category == "compliance":
                    # Insert remediation task
                    metrics["remediation_tasks"] += 1
                    try:
                        # Get default org_id
                        cur.execute(
                            "SELECT id FROM tenant.orgs WHERE slug = 'dragonfly-default-org' LIMIT 1"
                        )
                        org = cur.fetchone()
                        org_id = org["id"] if org else None

                        cur.execute(
                            """
                            INSERT INTO public.tasks (
                                title, description, status, priority, task_type, org_id, created_at
                            ) VALUES (
                                %s, %s, 'pending', 'high', 'remediation', %s, NOW()
                            )
                            ON CONFLICT DO NOTHING
                            RETURNING id
                            """,
                            (
                                f"DLQ Compliance Remediation: {details.get('pattern_matched', 'unknown')}",
                                json.dumps(details),
                                org_id,
                            ),
                        )
                        task = cur.fetchone()
                        if task:
                            log.info(f"Created remediation task: {task['id']}")
                    except Exception as e:
                        log.warning(f"Failed to create remediation task: {e}")

                else:
                    metrics["unclassified"] += 1

            # Note: autocommit=True, so no explicit commit needed

        # Determine status
        if metrics["security_incidents"] > 0:
            status = CheckStatus.UNHEALTHY
            message = f"DLQ: {dlq_depth} msgs, {metrics['security_incidents']} security incidents"
        elif dlq_depth > 10:
            status = CheckStatus.DEGRADED
            message = f"DLQ: {dlq_depth} msgs need attention"
        else:
            status = CheckStatus.DEGRADED
            message = (
                f"DLQ: {dlq_depth} msgs, {metrics['remediation_tasks']} remediation tasks created"
            )

        return CheckResult(
            name="DLQ Discipline",
            status=status,
            message=message,
            alerts=alerts,
            metrics=metrics,
            duration_ms=(time.perf_counter() - start) * 1000,
        )

    except Exception as e:
        return CheckResult(
            name="DLQ Discipline",
            status=CheckStatus.UNKNOWN,
            message=f"Error: {e}",
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 4: API HEALTH (Synthetic Probe)
# ═══════════════════════════════════════════════════════════════════════════════


async def check_api_health_async(api_base_url: str) -> CheckResult:
    """
    Perform synthetic health probe against API.

    SLO: Response time < 1000ms, status = 200
    """
    start = time.perf_counter()
    alerts: list[Alert] = []
    metrics: dict[str, Any] = {"latency_ms": 0, "status_code": 0, "endpoint": ""}

    health_endpoint = f"{api_base_url.rstrip('/')}/health"
    metrics["endpoint"] = health_endpoint

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT_SEC) as client:
            probe_start = time.perf_counter()
            response = await client.get(health_endpoint)
            latency_ms = (time.perf_counter() - probe_start) * 1000

            metrics["latency_ms"] = round(latency_ms, 1)
            metrics["status_code"] = response.status_code

            # Check status
            if response.status_code != 200:
                alerts.append(
                    Alert(
                        severity=AlertSeverity.CRITICAL,
                        category="API",
                        message=f"🔥 API Degraded: HTTP {response.status_code}",
                        details={
                            "endpoint": health_endpoint,
                            "status_code": response.status_code,
                            "latency_ms": latency_ms,
                        },
                    )
                )
                return CheckResult(
                    name="API Health",
                    status=CheckStatus.UNHEALTHY,
                    message=f"API returned HTTP {response.status_code}",
                    alerts=alerts,
                    metrics=metrics,
                    duration_ms=(time.perf_counter() - start) * 1000,
                )

            # Check latency SLO
            if latency_ms > API_LATENCY_THRESHOLD_MS:
                alerts.append(
                    Alert(
                        severity=AlertSeverity.WARNING,
                        category="API",
                        message=f"🐢 API Slow: {latency_ms:.0f}ms > {API_LATENCY_THRESHOLD_MS}ms SLO",
                        details={
                            "endpoint": health_endpoint,
                            "latency_ms": latency_ms,
                            "slo_threshold_ms": API_LATENCY_THRESHOLD_MS,
                        },
                    )
                )
                return CheckResult(
                    name="API Health",
                    status=CheckStatus.DEGRADED,
                    message=f"API slow ({latency_ms:.0f}ms > {API_LATENCY_THRESHOLD_MS}ms SLO)",
                    alerts=alerts,
                    metrics=metrics,
                    duration_ms=(time.perf_counter() - start) * 1000,
                )

            # All good
            return CheckResult(
                name="API Health",
                status=CheckStatus.HEALTHY,
                message=f"API healthy ({latency_ms:.0f}ms)",
                metrics=metrics,
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    except httpx.TimeoutException:
        alerts.append(
            Alert(
                severity=AlertSeverity.CRITICAL,
                category="API",
                message=f"🔥 API Timeout: No response in {API_TIMEOUT_SEC}s",
                details={"endpoint": health_endpoint, "timeout_sec": API_TIMEOUT_SEC},
            )
        )
        return CheckResult(
            name="API Health",
            status=CheckStatus.UNHEALTHY,
            message=f"API timeout ({API_TIMEOUT_SEC}s)",
            alerts=alerts,
            metrics=metrics,
            duration_ms=(time.perf_counter() - start) * 1000,
        )

    except httpx.ConnectError as e:
        # API not reachable - might be expected in dev
        return CheckResult(
            name="API Health",
            status=CheckStatus.UNKNOWN,
            message=f"API unreachable: {e}",
            metrics=metrics,
            duration_ms=(time.perf_counter() - start) * 1000,
        )

    except Exception as e:
        return CheckResult(
            name="API Health",
            status=CheckStatus.UNKNOWN,
            message=f"Error: {type(e).__name__}: {e}",
            duration_ms=(time.perf_counter() - start) * 1000,
        )


def check_api_health(api_base_url: str) -> CheckResult:
    """Sync wrapper for async API health check."""
    return asyncio.run(check_api_health_async(api_base_url))


# ═══════════════════════════════════════════════════════════════════════════════
# WATCHDOG MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════


def run_watchdog_iteration(env: str, iteration: int) -> WatchdogReport:
    """
    Run a single watchdog iteration.

    Executes all health checks and returns a comprehensive report.
    """
    start = time.perf_counter()
    checks: list[CheckResult] = []

    log.info(f"{'═' * 60}")
    log.info(f"WATCHDOG ITERATION #{iteration} ({env.upper()})")
    log.info(f"{'═' * 60}")

    # Get database connection
    try:
        db_url = get_db_url(env)
        conn = psycopg.connect(db_url, row_factory=dict_row, autocommit=True)
    except Exception as e:
        log.error(f"Failed to connect to database: {e}")
        return WatchdogReport(
            timestamp=datetime.now(timezone.utc),
            env=env,
            checks=[
                CheckResult(
                    name="Database",
                    status=CheckStatus.UNHEALTHY,
                    message=f"Connection failed: {e}",
                )
            ],
            overall_status=CheckStatus.UNHEALTHY,
            duration_ms=(time.perf_counter() - start) * 1000,
            iteration=iteration,
        )

    try:
        # Check 1: Worker Liveness
        log.info("[Check 1] Worker Liveness...")
        result = check_worker_liveness(conn)
        checks.append(result)
        log.info(
            f"  → {result.status.value.upper()}: {result.message} ({result.duration_ms:.0f}ms)"
        )
        for alert in result.alerts:
            log.warning(f"  {alert}")

        # Check 2: Queue Freshness
        log.info("[Check 2] Queue Freshness...")
        result = check_queue_freshness(conn)
        checks.append(result)
        log.info(
            f"  → {result.status.value.upper()}: {result.message} ({result.duration_ms:.0f}ms)"
        )
        for alert in result.alerts:
            log.warning(f"  {alert}")

        # Check 3: DLQ Discipline
        log.info("[Check 3] DLQ Discipline...")
        result = check_dlq_discipline(conn)
        checks.append(result)
        log.info(
            f"  → {result.status.value.upper()}: {result.message} ({result.duration_ms:.0f}ms)"
        )
        for alert in result.alerts:
            log.warning(f"  {alert}")

        # Check 4: API Health
        log.info("[Check 4] API Health...")
        api_base_url = get_api_base_url(env)
        result = check_api_health(api_base_url)
        checks.append(result)
        log.info(
            f"  → {result.status.value.upper()}: {result.message} ({result.duration_ms:.0f}ms)"
        )
        for alert in result.alerts:
            log.warning(f"  {alert}")

    finally:
        conn.close()

    # Determine overall status
    statuses = [c.status for c in checks]
    if CheckStatus.UNHEALTHY in statuses:
        overall_status = CheckStatus.UNHEALTHY
    elif CheckStatus.DEGRADED in statuses:
        overall_status = CheckStatus.DEGRADED
    elif CheckStatus.UNKNOWN in statuses:
        overall_status = CheckStatus.DEGRADED
    else:
        overall_status = CheckStatus.HEALTHY

    duration_ms = (time.perf_counter() - start) * 1000

    # Summary
    log.info(f"{'─' * 60}")
    status_icon = {"healthy": "✅", "degraded": "⚠️", "unhealthy": "❌", "unknown": "❓"}
    log.info(
        f"OVERALL: {status_icon.get(overall_status.value, '?')} {overall_status.value.upper()} ({duration_ms:.0f}ms)"
    )
    log.info(f"{'═' * 60}")

    return WatchdogReport(
        timestamp=datetime.now(timezone.utc),
        env=env,
        checks=checks,
        overall_status=overall_status,
        duration_ms=duration_ms,
        iteration=iteration,
    )


def run_watchdog_loop(env: str, once: bool = False) -> None:
    """
    Run the watchdog control loop.

    Args:
        env: Environment to monitor (dev/prod)
        once: If True, run only one iteration then exit
    """
    log.info(f"🐕 Watchdog starting for environment: {env.upper()}")
    log.info(f"   Loop interval: {LOOP_INTERVAL_SEC}s")
    log.info(
        f"   SLOs: queue={MAX_QUEUE_AGE_SEC}s, worker={MAX_WORKER_SILENCE_SEC}s, api={API_LATENCY_THRESHOLD_MS}ms"
    )

    iteration = 0
    while True:
        iteration += 1

        try:
            report = run_watchdog_iteration(env, iteration)

            # Could persist report to database or send to monitoring system here
            # For now, just log summary
            if report.overall_status == CheckStatus.UNHEALTHY:
                log.error("🚨 System UNHEALTHY - immediate attention required")
            elif report.overall_status == CheckStatus.DEGRADED:
                log.warning("⚠️ System DEGRADED - investigate soon")

        except KeyboardInterrupt:
            log.info("Watchdog stopped by user")
            break
        except Exception as e:
            log.exception(f"Watchdog iteration failed: {e}")

        if once:
            log.info("Single iteration complete (--once mode)")
            break

        # Wait for next iteration
        log.info(f"Next check in {LOOP_INTERVAL_SEC}s...")
        try:
            time.sleep(LOOP_INTERVAL_SEC)
        except KeyboardInterrupt:
            log.info("Watchdog stopped by user")
            break


# ═══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Dragonfly Civil Platform Watchdog - Health Monitor & SLO Enforcer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m backend.monitors.watchdog                    # Run continuous loop (dev)
  python -m backend.monitors.watchdog --env prod         # Run against production
  python -m backend.monitors.watchdog --once             # Single iteration
  python -m backend.monitors.watchdog --env prod --once  # Single prod check
        """,
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.getenv("SUPABASE_MODE", "dev"),
        help="Environment to monitor (default: SUPABASE_MODE or 'dev')",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run single iteration then exit",
    )

    args = parser.parse_args()

    try:
        run_watchdog_loop(env=args.env, once=args.once)
        return 0
    except Exception as e:
        log.exception(f"Watchdog failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
