"""
Dragonfly Engine - FOIL Service

Handles FOIL (Freedom of Information Law) request automation.
Manages follow-up scheduling and tracking for pending FOIL requests.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection
from .discord_service import DiscordService

logger = logging.getLogger(__name__)

# Template for FOIL follow-up emails
FOIL_FOLLOWUP_TEMPLATE = """Subject: FOIL Follow-up for case {case_number}

Dear {agency_name},

This is a follow-up regarding our Freedom of Information Law (FOIL) request
submitted on {sent_date} concerning case {case_number}.

We have not yet received a response to our request. Under FOIL regulations,
agencies are required to respond within five business days of receipt of a
request, with the possibility of a reasonable extension.

We kindly request an update on the status of our request and an estimated
timeline for receiving the requested records.

Thank you for your attention to this matter.

Best regards,
Dragonfly Civil Enforcement
"""


async def build_followup_message(
    case_number: str,
    agency_name: str,
    sent_at: datetime | None,
) -> str:
    """
    Build a FOIL follow-up email message.

    Args:
        case_number: The case number for the FOIL request
        agency_name: Name of the agency being contacted
        sent_at: When the original request was sent

    Returns:
        Formatted email message string
    """
    sent_date = sent_at.strftime("%B %d, %Y") if sent_at else "a previous date"

    return FOIL_FOLLOWUP_TEMPLATE.format(
        case_number=case_number,
        agency_name=agency_name,
        sent_date=sent_date,
    )


async def process_foil_followups() -> int:
    """
    Process pending FOIL requests that need follow-up.

    Selects requests where:
    - status = 'pending'
    - created_at <= NOW() - INTERVAL '20 days'

    For each request:
    - Builds a follow-up email message
    - Logs the follow-up attempt to foil_followup_log
    - Updates the request status to 'followup_sent'

    Returns:
        Number of requests processed
    """
    logger.info("Processing FOIL follow-ups...")

    processed = 0

    try:
        async with get_connection() as conn:
            # Find pending requests older than 20 days
            rows = await conn.fetch(
                """
                SELECT id, case_number, agency_name, agency_email, sent_at, created_at
                FROM public.foil_requests
                WHERE status = 'pending'
                  AND created_at <= NOW() - INTERVAL '20 days'
                ORDER BY created_at ASC
                """
            )

            if not rows:
                logger.info("No FOIL requests require follow-up")
                return 0

            logger.info(f"Found {len(rows)} FOIL requests requiring follow-up")

            # Process each request in a transaction
            async with conn.transaction():
                for row in rows:
                    try:
                        foil_id = row["id"]
                        case_number = row["case_number"]
                        agency_name = row["agency_name"]
                        sent_at = row["sent_at"] or row["created_at"]

                        # Build the follow-up message
                        message = await build_followup_message(
                            case_number=case_number,
                            agency_name=agency_name,
                            sent_at=sent_at,
                        )

                        # Preview is first 500 chars
                        message_preview = message[:500]

                        # Log the follow-up attempt
                        await conn.execute(
                            """
                            INSERT INTO public.foil_followup_log
                                (foil_request_id, attempted_at, message_preview, success)
                            VALUES ($1, $2, $3, $4)
                            """,
                            foil_id,
                            datetime.now(timezone.utc),
                            message_preview,
                            True,
                        )

                        # Update the request status
                        await conn.execute(
                            """
                            UPDATE public.foil_requests
                            SET status = 'followup_sent'
                            WHERE id = $1
                            """,
                            foil_id,
                        )

                        processed += 1
                        logger.debug(
                            f"Processed FOIL follow-up for request {foil_id} (case: {case_number})"
                        )

                    except Exception as e:
                        logger.error(f"Failed to process FOIL request {row['id']}: {e}")
                        # Log the failure
                        await conn.execute(
                            """
                            INSERT INTO public.foil_followup_log
                                (foil_request_id, attempted_at, success, error_message)
                            VALUES ($1, $2, $3, $4)
                            """,
                            row["id"],
                            datetime.now(timezone.utc),
                            False,
                            str(e)[:500],
                        )

            logger.info(f"FOIL follow-up processing complete: {processed} processed")

    except Exception as e:
        logger.exception(f"FOIL follow-up processing failed: {e}")
        raise

    return processed


async def broadcast_foil_followup_result(processed: int) -> None:
    """
    Send a Discord notification about FOIL follow-up results.

    Args:
        processed: Number of requests processed
    """
    if processed == 0:
        message = "📋 FOIL follow-up job: No pending requests required follow-up today."
    else:
        message = f"📋 FOIL follow-up job processed **{processed}** requests today."

    try:
        async with DiscordService() as discord:
            await discord.send_message(message, username="Dragonfly FOIL")
    except Exception as e:
        logger.error(f"Failed to send FOIL Discord notification: {e}")


async def get_foil_stats() -> dict[str, Any]:
    """
    Get statistics about FOIL requests.

    Returns:
        Dict with FOIL request statistics
    """
    async with get_connection() as conn:
        stats = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'pending') AS pending_count,
                COUNT(*) FILTER (WHERE status = 'followup_sent') AS followup_sent_count,
                COUNT(*) FILTER (WHERE status = 'responded') AS responded_count,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed_count,
                COUNT(*) AS total_count,
                COUNT(*) FILTER (
                    WHERE status = 'pending'
                    AND created_at <= NOW() - INTERVAL '20 days'
                ) AS needs_followup_count
            FROM public.foil_requests
            """
        )

        return dict(stats) if stats else {}
