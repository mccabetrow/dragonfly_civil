"""
Dragonfly Engine - Intake Guardian Service

Self-healing subsystem that detects and recovers stuck CSV intake batches.
Runs on a scheduled interval (default: 60 seconds) to find batches that
have been in 'processing' status for too long and marks them as failed.

This prevents orphaned batches from blocking the intake pipeline and ensures
operators are alerted when something goes wrong.

Usage:
    from backend.services.intake_guardian import IntakeGuardian

    guardian = IntakeGuardian()
    result = await guardian.check_stuck_batches()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from ..db import get_connection
from .discord_service import DiscordService

logger = logging.getLogger(__name__)


@dataclass
class GuardianResult:
    """Result of a guardian check cycle."""

    checked: int = 0
    marked_failed: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "checked": self.checked,
            "marked_failed": self.marked_failed,
            "errors": self.errors,
        }


@dataclass
class IntakeGuardian:
    """
    Self-healing guardian for the intake pipeline.

    Detects batches stuck in 'processing' state and marks them as failed
    with appropriate logging and alerts.

    Attributes:
        stale_minutes: How long a batch can be in 'processing' before it's
                       considered stuck. Default: 5 minutes.
        max_retries: Maximum retry attempts before marking failed. Default: 1
                     (we fail immediately, no retries for now).
    """

    stale_minutes: int = 5
    max_retries: int = 1

    async def check_stuck_batches(self) -> GuardianResult:
        """
        Check for and recover stuck intake batches.

        Queries ops.intake_batches for batches that:
        - Have status = 'processing'
        - Have updated_at older than stale_minutes

        For each stuck batch, marks it as failed and sends a Discord alert.

        Returns:
            GuardianResult with counts of checked and failed batches.
        """
        result = GuardianResult()

        logger.info(
            f"🛡️ Intake Guardian: Checking for stuck batches (stale > {self.stale_minutes} minutes)"
        )

        try:
            async with get_connection() as conn:
                # Find stuck batches
                stuck_batches = await conn.fetch(
                    """
                    SELECT id, filename, source, created_at, updated_at
                    FROM ops.intake_batches
                    WHERE status = 'processing'
                      AND updated_at < NOW() - INTERVAL '%s minutes'
                    ORDER BY updated_at ASC
                    """,
                    self.stale_minutes,
                )

                result.checked = len(stuck_batches)

                if not stuck_batches:
                    logger.debug("🛡️ Intake Guardian: No stuck batches found")
                    return result

                logger.warning(f"🛡️ Intake Guardian: Found {len(stuck_batches)} stuck batch(es)")

                # Process each stuck batch
                for batch in stuck_batches:
                    batch_id = batch["id"]
                    filename = batch.get("filename", "unknown")

                    try:
                        await self._mark_batch_failed(
                            batch_id=batch_id,
                            reason=f"Guardian detected timeout (> {self.stale_minutes} minutes)",
                        )
                        result.marked_failed += 1

                        # Send Discord alert
                        await self._send_alert(
                            batch_id=batch_id,
                            filename=filename,
                        )

                    except Exception as e:
                        error_msg = f"Failed to recover batch {batch_id}: {e}"
                        logger.error(f"🛡️ Intake Guardian: {error_msg}")
                        result.errors.append(error_msg)

        except Exception as e:
            error_msg = f"Guardian check failed: {e}"
            logger.exception(f"🛡️ Intake Guardian: {error_msg}")
            result.errors.append(error_msg)

        logger.info(
            f"🛡️ Intake Guardian: Completed - checked={result.checked}, "
            f"marked_failed={result.marked_failed}, errors={len(result.errors)}"
        )

        return result

    async def _mark_batch_failed(
        self,
        batch_id: UUID,
        reason: str,
    ) -> None:
        """
        Mark a batch as failed in the database.

        Updates ops.intake_batches and inserts a log entry into ops.intake_logs.

        Args:
            batch_id: The batch ID to mark as failed.
            reason: The reason for failure (stored in error_summary).
        """
        logger.warning(f"🛡️ Intake Guardian: Marking batch {batch_id} as FAILED")

        async with get_connection() as conn:
            async with conn.transaction():
                # Update batch status
                await conn.execute(
                    """
                    UPDATE ops.intake_batches
                    SET status = 'failed',
                        error_summary = %s,
                        finished_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    reason,
                    batch_id,
                )

                # Insert log entry
                await conn.execute(
                    """
                    INSERT INTO ops.intake_logs (
                        batch_id,
                        row_index,
                        status,
                        judgment_id,
                        error_details
                    ) VALUES (
                        %s,
                        NULL,
                        'error',
                        NULL,
                        %s
                    )
                    """,
                    batch_id,
                    reason,
                )

        logger.info(f"🛡️ Intake Guardian: Batch {batch_id} marked as failed")

    async def _send_alert(
        self,
        batch_id: UUID,
        filename: str,
    ) -> None:
        """
        Send a Discord alert for a failed batch.

        Args:
            batch_id: The batch ID that was marked as failed.
            filename: The original filename of the batch.
        """
        message = (
            f"🚨 **Intake Guardian Alert**\n"
            f"Batch `{batch_id}` marked as **FAILED** due to inactivity "
            f"(> {self.stale_minutes} minutes).\n"
            f"Filename: `{filename}`"
        )

        try:
            async with DiscordService() as discord:
                sent = await discord.send_message(
                    content=message,
                    username="Intake Guardian",
                )
                if sent:
                    logger.debug(f"🛡️ Intake Guardian: Discord alert sent for {batch_id}")
                else:
                    logger.debug("🛡️ Intake Guardian: Discord not configured, alert skipped")
        except Exception as e:
            # Don't fail the whole operation if Discord alert fails
            logger.warning(f"🛡️ Intake Guardian: Failed to send Discord alert: {e}")


# ---------------------------------------------------------------------------
# Singleton instance for scheduler use
# ---------------------------------------------------------------------------

_guardian_instance: IntakeGuardian | None = None


def get_intake_guardian() -> IntakeGuardian:
    """
    Get or create the singleton IntakeGuardian instance.

    Returns:
        The shared IntakeGuardian instance.
    """
    global _guardian_instance

    if _guardian_instance is None:
        _guardian_instance = IntakeGuardian()

    return _guardian_instance
