"""
Dragonfly Engine - Discord Notification Utility

Simple utility for sending alerts to Discord webhooks with embeds.

USAGE:
------
    from backend.utils.discord import send_alert, AlertColor

    # Success alert
    send_alert(
        title="✅ Golden Path Passed",
        description="System ready for plaintiffs.",
        color=AlertColor.SUCCESS,
        fields={"Environment": "PROD", "Batch ID": "abc-123"},
    )

    # Failure alert
    send_alert(
        title="❌ Golden Path FAILED",
        description="Error: Connection timeout",
        color=AlertColor.FAILURE,
    )

ENVIRONMENT:
------------
    DISCORD_WEBHOOK_URL: Discord webhook URL for alerts (required)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class AlertColor(IntEnum):
    """Discord embed colors for common alert states."""

    SUCCESS = 0x00FF00  # Green
    FAILURE = 0xFF0000  # Red
    WARNING = 0xFFFF00  # Yellow
    INFO = 0x3498DB  # Blue


def send_alert(
    title: str,
    description: str,
    color: int | AlertColor = AlertColor.INFO,
    fields: dict[str, Any] | None = None,
    *,
    webhook_url: str | None = None,
    username: str = "Dragonfly",
    timeout: float = 10.0,
) -> bool:
    """
    Send a Discord alert with an embed.

    Args:
        title: Embed title (e.g., "✅ Golden Path Passed")
        description: Embed description/message body
        color: Embed color (use AlertColor enum or raw int)
        fields: Optional dict of key/value pairs to display as embed fields
        webhook_url: Override DISCORD_WEBHOOK_URL env var
        username: Bot username to display (default: "Dragonfly")
        timeout: HTTP timeout in seconds

    Returns:
        True if message sent successfully, False otherwise.

    Example:
        >>> send_alert(
        ...     title="✅ Deploy Complete",
        ...     description="Production deployment successful.",
        ...     color=AlertColor.SUCCESS,
        ...     fields={"Version": "v1.2.3", "Duration": "45s"},
        ... )
    """
    url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")

    if not url:
        logger.debug("DISCORD_WEBHOOK_URL not configured; skipping alert")
        return False

    # Build embed
    embed: dict[str, Any] = {
        "title": title,
        "description": description,
        "color": int(color),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Add fields if provided
    if fields:
        embed["fields"] = [
            {"name": str(key), "value": str(value), "inline": len(str(value)) < 30}
            for key, value in fields.items()
        ]

    payload = {
        "username": username,
        "embeds": [embed],
    }

    try:
        with httpx.Client() as client:
            response = client.post(url, json=payload, timeout=timeout)

        # Discord returns 204 No Content on success
        if response.status_code == 204:
            logger.debug("Discord alert sent: %s", title)
            return True
        else:
            logger.warning("Discord returned status %d for alert: %s", response.status_code, title)
            return False

    except httpx.TimeoutException:
        logger.warning("Discord alert timed out: %s", title)
        return False
    except Exception as e:
        logger.warning("Discord alert failed: %s - %s", title, e)
        return False


def send_success(
    title: str,
    description: str,
    fields: dict[str, Any] | None = None,
    **kwargs: Any,
) -> bool:
    """Send a green success alert."""
    return send_alert(title, description, AlertColor.SUCCESS, fields, **kwargs)


def send_failure(
    title: str,
    description: str,
    fields: dict[str, Any] | None = None,
    **kwargs: Any,
) -> bool:
    """Send a red failure alert."""
    return send_alert(title, description, AlertColor.FAILURE, fields, **kwargs)


def send_warning(
    title: str,
    description: str,
    fields: dict[str, Any] | None = None,
    **kwargs: Any,
) -> bool:
    """Send a yellow warning alert."""
    return send_alert(title, description, AlertColor.WARNING, fields, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# STRICT ALERT TYPE SYSTEM (Whitelist)
# ═══════════════════════════════════════════════════════════════════════════


class AlertType(IntEnum):
    """
    Strict whitelist of critical alert types.

    Only these events will fire Discord notifications.
    Each type has a predefined color for visual consistency.
    """

    FAILOVER_ACTIVE = 0xFFA500  # Amber - DataService switched to Direct DB
    PGRST_CACHE_STALE = 0xFF0000  # Red - PostgREST schema cache error
    CONFIG_ERROR = 0x8B0000  # Dark Red - Configuration/credential mismatch
    POOL_EXHAUSTED = 0x800080  # Purple - Database pool exhausted
    TEST = 0x00FF00  # Green - Verification/test alert

    @property
    def title_prefix(self) -> str:
        """Get emoji prefix for alert type."""
        return {
            AlertType.FAILOVER_ACTIVE: "🛡️",
            AlertType.PGRST_CACHE_STALE: "🔥",
            AlertType.CONFIG_ERROR: "⚠️",
            AlertType.POOL_EXHAUSTED: "💀",
            AlertType.TEST: "✅",
        }.get(self, "📢")

    @property
    def title_text(self) -> str:
        """Human-readable title for the alert type."""
        return {
            AlertType.FAILOVER_ACTIVE: "Failover Active",
            AlertType.PGRST_CACHE_STALE: "PostgREST Cache Stale",
            AlertType.CONFIG_ERROR: "Configuration Error",
            AlertType.POOL_EXHAUSTED: "Pool Exhausted",
            AlertType.TEST: "Test Alert",
        }.get(self, "System Alert")


class DiscordMessenger:
    """
    Strict Discord alerting with whitelist enforcement.

    Features:
    - Only sends alerts for predefined AlertType enum values
    - Fire-and-forget (never blocks the application)
    - Graceful degradation if webhook not configured
    - Rate limiting via singleton pattern

    Usage:
        from backend.utils.discord import DiscordMessenger, AlertType

        messenger = DiscordMessenger.get_instance()
        messenger.send_alert(
            AlertType.FAILOVER_ACTIVE,
            "Switched to Direct DB mode",
            {"Environment": "PROD", "View": "v_plaintiffs_overview"}
        )
    """

    _instance: "DiscordMessenger | None" = None

    def __init__(self, webhook_url: str | None = None):
        self._webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
        self._last_alert_time: dict[AlertType, float] = {}
        self._min_interval_seconds = 60  # Rate limit per alert type

    @classmethod
    def get_instance(cls) -> "DiscordMessenger":
        """Get singleton instance of DiscordMessenger."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def is_configured(self) -> bool:
        """Check if Discord webhook is configured."""
        return self._webhook_url is not None

    def _should_send(self, alert_type: AlertType) -> bool:
        """Check rate limiting for this alert type."""
        import time

        now = time.time()
        last_time = self._last_alert_time.get(alert_type, 0)

        if now - last_time < self._min_interval_seconds:
            logger.debug(f"Rate limiting {alert_type.name}: last sent {now - last_time:.0f}s ago")
            return False

        self._last_alert_time[alert_type] = now
        return True

    def send_alert(
        self,
        alert_type: AlertType,
        message: str,
        details: dict[str, Any] | None = None,
        *,
        force: bool = False,
    ) -> bool:
        """
        Send a Discord alert with strict type enforcement.

        Args:
            alert_type: Must be a valid AlertType enum value
            message: Alert description
            details: Optional key-value pairs for embed fields
            force: Skip rate limiting (for critical alerts)

        Returns:
            True if alert was sent, False if skipped or failed
        """
        # ─────────────────────────────────────────────────────────────────
        # Validation: Strict whitelist
        # ─────────────────────────────────────────────────────────────────
        if not isinstance(alert_type, AlertType):
            logger.warning(
                f"❌ Rejected alert: {alert_type} is not a valid AlertType. "
                "Only whitelisted alert types are allowed."
            )
            return False

        # ─────────────────────────────────────────────────────────────────
        # Configuration check
        # ─────────────────────────────────────────────────────────────────
        if not self.is_configured:
            logger.warning(f"⚠️ DISCORD_WEBHOOK_URL not set - {alert_type.name} alert logged only")
            logger.info(f"[{alert_type.name}] {message}")
            if details:
                for k, v in details.items():
                    logger.info(f"  {k}: {v}")
            return False

        # ─────────────────────────────────────────────────────────────────
        # Rate limiting (skip for TEST alerts or forced)
        # ─────────────────────────────────────────────────────────────────
        if not force and alert_type != AlertType.TEST and not self._should_send(alert_type):
            return False

        # ─────────────────────────────────────────────────────────────────
        # Build Discord payload
        # ─────────────────────────────────────────────────────────────────
        title = f"{alert_type.title_prefix} {alert_type.title_text}"

        embed: dict[str, Any] = {
            "title": title,
            "description": message,
            "color": int(alert_type),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": f"Dragonfly Engine | {alert_type.name}"},
        }

        if details:
            embed["fields"] = [
                {
                    "name": str(key),
                    "value": str(value)[:1024],  # Discord field limit
                    "inline": len(str(value)) < 30,
                }
                for key, value in details.items()
            ]

        payload = {
            "username": "Dragonfly Alerts",
            "embeds": [embed],
        }

        # ─────────────────────────────────────────────────────────────────
        # Fire and forget HTTP request
        # ─────────────────────────────────────────────────────────────────
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.post(self._webhook_url, json=payload)

            if response.status_code == 204:
                logger.info(f"✅ Discord alert sent: {alert_type.name}")
                return True
            else:
                logger.warning(f"Discord returned {response.status_code} for {alert_type.name}")
                return False

        except httpx.TimeoutException:
            logger.warning(f"Discord timeout for {alert_type.name} - continuing")
            return False
        except Exception as e:
            logger.warning(f"Discord error for {alert_type.name}: {e} - continuing")
            return False


# ═══════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS FOR COMMON ALERTS
# ═══════════════════════════════════════════════════════════════════════════


def alert_failover_active(
    environment: str,
    view_name: str,
    rest_error: str | None = None,
) -> bool:
    """Alert when DataService switches to Direct DB fallback."""
    return DiscordMessenger.get_instance().send_alert(
        AlertType.FAILOVER_ACTIVE,
        f"DataService switched to Direct DB for `{view_name}`",
        {
            "Environment": environment.upper(),
            "View": view_name,
            "REST Error": rest_error or "Unknown",
            "Status": "Auto-failover successful",
        },
    )


def alert_pgrst_cache_stale(
    environment: str,
    recovery_attempted: bool = False,
    recovery_success: bool = False,
) -> bool:
    """Alert when PostgREST schema cache is stale."""
    status = (
        "Recovery successful"
        if recovery_success
        else (
            "Recovery failed - manual intervention needed"
            if recovery_attempted
            else "Detected - attempting recovery"
        )
    )
    return DiscordMessenger.get_instance().send_alert(
        AlertType.PGRST_CACHE_STALE,
        "PostgREST schema cache is stale (PGRST002)",
        {
            "Environment": environment.upper(),
            "Recovery Attempted": str(recovery_attempted),
            "Status": status,
        },
        force=not recovery_success,  # Force if recovery failed
    )


def alert_config_error(
    environment: str,
    error_message: str,
    component: str = "bootstrap",
) -> bool:
    """Alert when configuration verification fails."""
    return DiscordMessenger.get_instance().send_alert(
        AlertType.CONFIG_ERROR,
        f"Configuration error in {component}",
        {
            "Environment": environment.upper(),
            "Component": component,
            "Error": error_message[:500],
        },
        force=True,  # Config errors are always critical
    )


def alert_pool_exhausted(
    environment: str,
    pool_size: int,
    active_connections: int,
) -> bool:
    """Alert when database connection pool is exhausted."""
    return DiscordMessenger.get_instance().send_alert(
        AlertType.POOL_EXHAUSTED,
        "Database connection pool exhausted",
        {
            "Environment": environment.upper(),
            "Pool Size": str(pool_size),
            "Active Connections": str(active_connections),
            "Status": "New connections will block or fail",
        },
        force=True,  # Pool exhaustion is always critical
    )


def alert_test(message: str = "Test alert from Dragonfly") -> bool:
    """Send a test alert to verify Discord webhook configuration."""
    return DiscordMessenger.get_instance().send_alert(
        AlertType.TEST,
        message,
        {"Timestamp": datetime.now(timezone.utc).isoformat()},
    )
