"""
Dragonfly Engine - Sentinel Alerting

Sends Discord alerts when the system performs emergency failovers,
detects configuration mismatches, or encounters schema drift.

USAGE:
------
    from backend.utils.alerting import alert_incident, IncidentType, Severity

    # Alert on failover
    await alert_incident(
        incident_type=IncidentType.FAILOVER_ACTIVE,
        message="PostgREST returned PGRST002, switched to direct SQL",
        severity=Severity.WARNING,
    )

RATE LIMITING:
--------------
    - Max 1 alert per 5 minutes for the same incident type
    - Prevents Discord webhook spam during cascading failures
    - Rate limit state is per-process (resets on restart)

ENVIRONMENT:
------------
    DISCORD_WEBHOOK_URL: Discord webhook URL for alerts
    DRAGONFLY_ENV: Environment name (dev/prod) for context
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# =============================================================================
# Constants & Enums
# =============================================================================


class IncidentType(str, Enum):
    """Types of incidents that trigger alerts."""

    SCHEMA_DRIFT = "Schema Drift"
    CONFIG_ERROR = "Config Error"
    FAILOVER_ACTIVE = "Failover Active"
    PGRST_CACHE_STALE = "PostgREST Cache Stale"
    CROSS_ENV_MISMATCH = "Cross-Environment Mismatch"
    POOL_EXHAUSTED = "Connection Pool Exhausted"


class Severity(str, Enum):
    """Alert severity levels (maps to Discord embed colors)."""

    INFO = "info"  # Blue
    WARNING = "warning"  # Yellow
    ERROR = "error"  # Red
    CRITICAL = "critical"  # Dark Red


# Discord embed colors by severity
SEVERITY_COLORS = {
    Severity.INFO: 0x3498DB,  # Blue
    Severity.WARNING: 0xF1C40F,  # Yellow
    Severity.ERROR: 0xE74C3C,  # Red
    Severity.CRITICAL: 0x8B0000,  # Dark Red
}

# Emoji prefixes by severity
SEVERITY_EMOJI = {
    Severity.INFO: "ℹ️",
    Severity.WARNING: "⚠️",
    Severity.ERROR: "❌",
    Severity.CRITICAL: "🚨",
}

# Rate limit: seconds between alerts of the same type
RATE_LIMIT_SECONDS = 300  # 5 minutes


# =============================================================================
# Rate Limiter
# =============================================================================


@dataclass
class RateLimitState:
    """Tracks last alert time per incident type."""

    _last_alerts: dict[str, float] = field(default_factory=dict)
    _suppressed_counts: dict[str, int] = field(default_factory=dict)

    def should_alert(self, incident_type: str) -> bool:
        """Check if enough time has passed since last alert of this type."""
        now = time.monotonic()
        last_time = self._last_alerts.get(incident_type, 0)

        if now - last_time >= RATE_LIMIT_SECONDS:
            return True

        # Track suppressed alerts
        self._suppressed_counts[incident_type] = self._suppressed_counts.get(incident_type, 0) + 1
        return False

    def record_alert(self, incident_type: str) -> int:
        """Record that an alert was sent, return count of suppressed alerts."""
        now = time.monotonic()
        suppressed = self._suppressed_counts.pop(incident_type, 0)
        self._last_alerts[incident_type] = now
        return suppressed

    def get_suppressed_count(self, incident_type: str) -> int:
        """Get number of suppressed alerts for this type."""
        return self._suppressed_counts.get(incident_type, 0)


# Global rate limiter (per-process)
_rate_limiter = RateLimitState()


# =============================================================================
# Discord Webhook
# =============================================================================


def _get_webhook_url() -> str | None:
    """Get Discord webhook URL from environment."""
    return os.environ.get("DISCORD_WEBHOOK_URL")


def _get_environment() -> str:
    """Get current environment name."""
    return os.environ.get("DRAGONFLY_ENV", os.environ.get("SUPABASE_MODE", "unknown"))


def _build_discord_payload(
    incident_type: IncidentType,
    message: str,
    severity: Severity,
    suppressed_count: int = 0,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build Discord webhook payload with embed."""
    env = _get_environment()
    timestamp = datetime.now(timezone.utc).isoformat()
    emoji = SEVERITY_EMOJI[severity]
    color = SEVERITY_COLORS[severity]

    # Build fields
    fields = [
        {"name": "Environment", "value": f"`{env.upper()}`", "inline": True},
        {"name": "Severity", "value": f"`{severity.value.upper()}`", "inline": True},
        {"name": "Type", "value": f"`{incident_type.value}`", "inline": True},
    ]

    # Add suppressed count if any
    if suppressed_count > 0:
        fields.append(
            {
                "name": "Suppressed Alerts",
                "value": f"`{suppressed_count}` similar alerts in last 5 min",
                "inline": False,
            }
        )

    # Add context fields if provided
    if context:
        for key, value in context.items():
            fields.append(
                {
                    "name": key.replace("_", " ").title(),
                    "value": f"`{value}`" if len(str(value)) < 50 else f"```{value}```",
                    "inline": len(str(value)) < 30,
                }
            )

    return {
        "username": "Dragonfly Sentinel",
        "avatar_url": "https://em-content.zobj.net/source/twitter/376/dragon_1f409.png",
        "embeds": [
            {
                "title": f"{emoji} {incident_type.value}",
                "description": message,
                "color": color,
                "fields": fields,
                "footer": {"text": f"Dragonfly Civil • {env.upper()}"},
                "timestamp": timestamp,
            }
        ],
    }


async def _send_discord_alert(payload: dict[str, Any]) -> bool:
    """Send alert to Discord webhook."""
    webhook_url = _get_webhook_url()

    if not webhook_url:
        logger.debug("DISCORD_WEBHOOK_URL not configured, skipping alert")
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )

            if response.status_code in (200, 204):
                logger.info(f"✅ Discord alert sent: {payload['embeds'][0]['title']}")
                return True

            logger.warning(
                f"Discord webhook returned {response.status_code}: {response.text[:100]}"
            )
            return False

    except httpx.TimeoutException:
        logger.warning("Discord webhook timeout")
        return False
    except Exception as e:
        logger.warning(f"Discord webhook error: {type(e).__name__}: {e}")
        return False


# =============================================================================
# Public API
# =============================================================================


async def alert_incident(
    incident_type: IncidentType | str,
    message: str,
    severity: Severity = Severity.WARNING,
    context: dict[str, Any] | None = None,
    force: bool = False,
) -> bool:
    """
    Send an incident alert to Discord.

    Args:
        incident_type: Type of incident (IncidentType enum or string)
        message: Human-readable description of what happened
        severity: Alert severity level
        context: Optional dict of additional context fields
        force: If True, bypass rate limiting

    Returns:
        True if alert was sent, False if rate-limited or failed

    Example:
        await alert_incident(
            incident_type=IncidentType.FAILOVER_ACTIVE,
            message="PostgREST returned PGRST002, switched to direct SQL",
            severity=Severity.WARNING,
            context={"endpoint": "/v1/enforcement/radar", "latency_ms": 450},
        )
    """
    # Normalize incident type
    if isinstance(incident_type, str):
        type_key = incident_type
        try:
            incident_type = IncidentType(incident_type)
        except ValueError:
            # Use string as-is for custom types
            pass
    else:
        type_key = incident_type.value

    # Check rate limit
    if not force and not _rate_limiter.should_alert(type_key):
        logger.debug(f"Rate-limited alert: {type_key} (max 1 per {RATE_LIMIT_SECONDS}s)")
        return False

    # Get suppressed count before recording
    suppressed_count = _rate_limiter.get_suppressed_count(type_key)

    # Record this alert
    _rate_limiter.record_alert(type_key)

    # Build and send payload
    payload = _build_discord_payload(
        incident_type=(
            incident_type if isinstance(incident_type, IncidentType) else IncidentType.CONFIG_ERROR
        ),
        message=message,
        severity=severity,
        suppressed_count=suppressed_count,
        context=context,
    )

    # For custom string types, update the title
    if isinstance(incident_type, str):
        payload["embeds"][0]["title"] = f"{SEVERITY_EMOJI[severity]} {incident_type}"

    return await _send_discord_alert(payload)


def alert_incident_sync(
    incident_type: IncidentType | str,
    message: str,
    severity: Severity = Severity.WARNING,
    context: dict[str, Any] | None = None,
    force: bool = False,
) -> bool:
    """
    Synchronous wrapper for alert_incident.

    Use this from synchronous code paths. Creates a new event loop if needed.
    """
    try:
        asyncio.get_running_loop()
        # We're in an async context, schedule as task
        asyncio.create_task(alert_incident(incident_type, message, severity, context, force))
        return True  # Assume success, fire-and-forget
    except RuntimeError:
        # No running loop, create one
        return asyncio.run(alert_incident(incident_type, message, severity, context, force))


# =============================================================================
# Convenience Functions
# =============================================================================


async def alert_failover(
    endpoint: str,
    reason: str,
    latency_ms: float | None = None,
) -> bool:
    """Alert when system falls back to direct SQL."""
    context = {"endpoint": endpoint}
    if latency_ms is not None:
        context["latency_ms"] = f"{latency_ms:.0f}ms"

    return await alert_incident(
        incident_type=IncidentType.FAILOVER_ACTIVE,
        message=f"PostgREST unavailable, using direct SQL fallback.\n**Reason:** {reason}",
        severity=Severity.WARNING,
        context=context,
    )


async def alert_schema_drift(
    expected: str,
    actual: str,
    location: str | None = None,
) -> bool:
    """Alert when schema doesn't match expectations."""
    context = {"expected": expected, "actual": actual}
    if location:
        context["location"] = location

    return await alert_incident(
        incident_type=IncidentType.SCHEMA_DRIFT,
        message="Database schema does not match expected state. Manual intervention may be required.",
        severity=Severity.ERROR,
        context=context,
    )


async def alert_config_error(
    config_key: str,
    error: str,
) -> bool:
    """Alert on configuration errors."""
    return await alert_incident(
        incident_type=IncidentType.CONFIG_ERROR,
        message=f"Configuration error detected: `{config_key}`\n**Error:** {error}",
        severity=Severity.ERROR,
        context={"config_key": config_key},
    )


async def alert_cross_env_mismatch(
    expected_env: str,
    actual_host: str,
) -> bool:
    """Alert when environment and database host don't match."""
    return await alert_incident(
        incident_type=IncidentType.CROSS_ENV_MISMATCH,
        message="**CRITICAL:** Environment configuration points to wrong database!",
        severity=Severity.CRITICAL,
        context={
            "expected_env": expected_env,
            "actual_db_host": actual_host,
        },
        force=True,  # Always send critical alerts
    )


async def alert_pgrst_cache_stale(
    error_code: str = "PGRST002",
    reload_triggered: bool = False,
) -> bool:
    """Alert when PostgREST schema cache is stale."""
    message = f"PostgREST returned `{error_code}` - schema cache is stale."
    if reload_triggered:
        message += "\n**Action:** Automatic cache reload triggered via `NOTIFY pgrst`."

    return await alert_incident(
        incident_type=IncidentType.PGRST_CACHE_STALE,
        message=message,
        severity=Severity.WARNING,
        context={"error_code": error_code, "auto_reload": str(reload_triggered)},
    )
