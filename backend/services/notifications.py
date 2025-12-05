"""
Dragonfly Engine - Notifications Service

Unified notification service for sending alerts via Discord, Email, and SMS.
Wraps the Discord service with higher-level business-event notifications.
"""

import logging
from uuid import UUID

from .discord_service import DiscordService

logger = logging.getLogger(__name__)


async def send_discord_message(content: str) -> bool:
    """
    Send a simple message to Discord.

    Convenience wrapper for use in jobs and services.

    Args:
        content: Message content (supports Markdown)

    Returns:
        True if message was sent successfully
    """
    async with DiscordService() as discord:
        return await discord.send_message(content)


async def notify_batch_completed(
    batch_id: UUID,
    source: str,
    row_count_valid: int,
    row_count_invalid: int,
) -> bool:
    """
    Send notification when a batch completes successfully.

    Sends to both Discord and OPS_EMAIL if configured.

    Args:
        batch_id: The batch UUID
        source: Source system (e.g., 'simplicity')
        row_count_valid: Number of valid rows
        row_count_invalid: Number of invalid rows

    Returns:
        True if notification was sent
    """
    total = row_count_valid + row_count_invalid
    success_rate = (row_count_valid / total * 100) if total > 0 else 0

    message = (
        f"✅ **{source.title()} Ingest Batch Completed**\n"
        f"• Batch ID: `{batch_id}`\n"
        f"• Valid rows: **{row_count_valid}**\n"
        f"• Invalid rows: **{row_count_invalid}**\n"
        f"• Success rate: **{success_rate:.1f}%**"
    )

    logger.info(f"Sending batch completion notification for {batch_id}")

    # Send to Discord
    discord_sent = await send_discord_message(message)

    # Also send email to Ops team
    try:
        from .notification_service import send_ops_alert

        await send_ops_alert(
            subject=f"Batch Complete: {source.title()} - {row_count_valid} rows",
            body=(
                f"Batch ID: {batch_id}\n"
                f"Source: {source}\n"
                f"Valid rows: {row_count_valid}\n"
                f"Invalid rows: {row_count_invalid}\n"
                f"Success rate: {success_rate:.1f}%"
            ),
        )
    except Exception as e:
        logger.warning(f"Failed to send batch email notification: {e}")

    return discord_sent


async def notify_batch_failed(
    batch_id: UUID,
    source: str,
    error_summary: str,
) -> bool:
    """
    Send notification when a batch fails.

    Sends to both Discord and OPS_EMAIL (with SMS for critical failures).

    Args:
        batch_id: The batch UUID
        source: Source system (e.g., 'simplicity')
        error_summary: Error message summary

    Returns:
        True if notification was sent
    """
    # Truncate error for Discord
    error_preview = error_summary[:500] if error_summary else "Unknown error"

    message = (
        f"🚨 **{source.title()} Ingest Batch FAILED**\n"
        f"• Batch ID: `{batch_id}`\n"
        f"• Error: ```{error_preview}```"
    )

    logger.error(f"Sending batch failure notification for {batch_id}: {error_preview}")

    # Send to Discord
    discord_sent = await send_discord_message(message)

    # Also send email (and SMS) to Ops team for failures
    try:
        from .notification_service import send_ops_alert

        await send_ops_alert(
            subject=f"⚠️ BATCH FAILED: {source.title()}",
            body=(
                f"Batch ID: {batch_id}\n"
                f"Source: {source}\n\n"
                f"Error:\n{error_summary}"
            ),
            include_sms=True,  # SMS for failures
        )
    except Exception as e:
        logger.warning(f"Failed to send batch failure email: {e}")

    return discord_sent


async def notify_pending_batches_processed(
    processed_count: int,
    success_count: int,
    failure_count: int,
) -> bool:
    """
    Send notification after scheduler processes pending batches.

    Args:
        processed_count: Total batches processed
        success_count: Successful batches
        failure_count: Failed batches

    Returns:
        True if notification was sent
    """
    if processed_count == 0:
        # Don't notify if nothing was processed
        return True

    emoji = "✅" if failure_count == 0 else "⚠️"

    message = (
        f"{emoji} **Batch Processing Complete**\n"
        f"• Processed: **{processed_count}** batches\n"
        f"• Succeeded: **{success_count}**\n"
        f"• Failed: **{failure_count}**"
    )

    logger.info(f"Processed {processed_count} pending batches")
    return await send_discord_message(message)
