"""
Dragonfly Engine - Health Service

Daily health check and broadcast functionality.
Fetches system health metrics and broadcasts to Discord.
"""

import logging
from datetime import date
from typing import Any

from ..db import get_connection
from .discord_service import DiscordService

logger = logging.getLogger(__name__)


async def fetch_daily_health_summary() -> dict[str, Any]:
    """
    Fetch daily health metrics from v_daily_health view.

    Returns:
        Dict with keys: run_date, tier_a_count, stalled_cases,
        today_collections_amount, pending_signatures, budget_approvals_today

    Raises:
        RuntimeError: If view is not available or query fails
    """
    logger.info("Fetching daily health summary...")

    try:
        async with get_connection() as conn:
            row = await conn.fetchrow("SELECT * FROM public.v_daily_health LIMIT 1")

            if row is None:
                logger.warning("v_daily_health returned no rows")
                # Return default values if no data
                return {
                    "run_date": date.today().isoformat(),
                    "tier_a_count": 0,
                    "stalled_cases": 0,
                    "today_collections_amount": 0.0,
                    "pending_signatures": 0,
                    "budget_approvals_today": 0,
                }

            # Convert asyncpg Record to dict
            result = dict(row)

            # Ensure run_date is a string
            if "run_date" in result and hasattr(result["run_date"], "isoformat"):
                result["run_date"] = result["run_date"].isoformat()

            logger.info(f"Daily health summary: {result}")
            return result

    except Exception as e:
        logger.error(f"Failed to fetch daily health summary: {e}")
        raise RuntimeError(f"Failed to fetch daily health: {e}") from e


async def broadcast_daily_health() -> dict[str, Any]:
    """
    Fetch daily health summary and broadcast to Discord.

    Returns:
        Dict with broadcast status and health data

    This function handles its own exceptions and logs failures
    instead of raising, making it safe for scheduled job execution.
    """
    logger.info("Broadcasting daily health check...")

    try:
        # Fetch health data
        health = await fetch_daily_health_summary()

        # Format collections amount
        collections = health.get("today_collections_amount", 0) or 0
        if isinstance(collections, (int, float)):
            collections_str = f"${collections:,.2f}"
        else:
            collections_str = f"${float(collections):,.2f}"

        # Build Discord message
        message = (
            f"🩺 **Dragonfly Daily Health** — {health.get('run_date', 'Unknown')}\n"
            f"Tier A: **{health.get('tier_a_count', 0)}** | "
            f"Stalled: **{health.get('stalled_cases', 0)}**\n"
            f"Collected Today: **{collections_str}**\n"
            f"Pending signatures: **{health.get('pending_signatures', 0)}**\n"
            f"Budget approvals: **{health.get('budget_approvals_today', 0)}**"
        )

        # Send to Discord
        async with DiscordService() as discord:
            sent = await discord.send_message(message, username="Dragonfly Health")

            if sent:
                logger.info("Daily health broadcast sent to Discord")
            else:
                logger.warning("Discord message not sent (webhook not configured?)")

        return {
            "status": "success",
            "message_sent": sent,
            "health": health,
        }

    except Exception as e:
        logger.exception(f"Failed to broadcast daily health: {e}")
        return {
            "status": "error",
            "error": str(e),
            "health": None,
        }
