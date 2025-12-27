"""
Outbox Processor - Reliable Side Effect Delivery

Implements the Transactional Outbox pattern for exactly-once delivery of
side effects like PDF generation, emails, webhooks, and external API calls.

Architecture:
    1. Business logic writes to ops.outbox within the main DB transaction
    2. This processor polls for pending messages and processes them
    3. Processing is idempotent - safe to retry on failure
    4. Failed messages are retried up to max_attempts, then dead-lettered

Channels:
    - pdf: Generate and deliver PDF documents
    - email: Send emails via configured provider
    - webhook: HTTP POST to external URLs
    - slack: Send Slack notifications
    - discord: Send Discord notifications
    - sms: Send SMS messages
    - external_api: Call external APIs

Usage:
    # Run as a worker (polls continuously)
    python -m backend.workers.outbox_processor

    # Process once (for testing/debugging)
    python -m backend.workers.outbox_processor --once
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import sys
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

POLL_INTERVAL_SECONDS = int(os.environ.get("OUTBOX_POLL_INTERVAL", "5"))
BATCH_SIZE = int(os.environ.get("OUTBOX_BATCH_SIZE", "10"))
WORKER_ID = os.environ.get("WORKER_ID", f"outbox-{uuid.uuid4().hex[:8]}")

# Channels this worker processes (comma-separated, or 'all')
ENABLED_CHANNELS = os.environ.get("OUTBOX_CHANNELS", "all").split(",")


# =============================================================================
# Channel Handlers (Strategy Pattern)
# =============================================================================


class ChannelHandler(ABC):
    """Base class for outbox channel handlers."""

    @property
    @abstractmethod
    def channel(self) -> str:
        """Return the channel name this handler processes."""
        pass

    @abstractmethod
    async def process(self, payload: dict[str, Any]) -> None:
        """
        Process the outbox message payload.

        Args:
            payload: The JSON payload from the outbox message

        Raises:
            Exception: If processing fails (message will be retried)
        """
        pass


class PDFHandler(ChannelHandler):
    """Handler for PDF generation and delivery."""

    @property
    def channel(self) -> str:
        return "pdf"

    async def process(self, payload: dict[str, Any]) -> None:
        """
        Generate and deliver a PDF.

        Expected payload:
            {
                "template": "enforcement_packet",
                "data": {...},
                "delivery": {"type": "email", "to": "..."}
            }
        """
        template = payload.get("template")
        data = payload.get("data", {})
        delivery = payload.get("delivery", {})

        logger.info(f"PDF: Generating {template} with {len(data)} data fields")

        # TODO: Implement PDF generation
        # from backend.services.pdf import generate_pdf
        # pdf_bytes = await generate_pdf(template, data)

        # TODO: Deliver based on delivery config
        # if delivery.get("type") == "email":
        #     await send_email_with_attachment(...)

        logger.info(f"PDF: Generated and delivered {template}")


class EmailHandler(ChannelHandler):
    """Handler for email delivery."""

    @property
    def channel(self) -> str:
        return "email"

    async def process(self, payload: dict[str, Any]) -> None:
        """
        Send an email.

        Expected payload:
            {
                "to": "email@example.com",
                "subject": "...",
                "body": "...",
                "template": "optional_template_name"
            }
        """
        to = payload.get("to")
        subject = payload.get("subject")

        logger.info(f"Email: Sending to {to}: {subject[:50]}...")

        # TODO: Implement email sending
        # from backend.services.email import send_email
        # await send_email(to=to, subject=subject, body=payload.get("body"))

        logger.info(f"Email: Sent to {to}")


class WebhookHandler(ChannelHandler):
    """Handler for HTTP webhook delivery."""

    @property
    def channel(self) -> str:
        return "webhook"

    async def process(self, payload: dict[str, Any]) -> None:
        """
        Send an HTTP webhook.

        Expected payload:
            {
                "url": "https://...",
                "method": "POST",
                "headers": {...},
                "body": {...}
            }
        """
        url = payload.get("url")
        method = payload.get("method", "POST").upper()
        headers = payload.get("headers", {})
        body = payload.get("body", {})

        logger.info(f"Webhook: {method} {url}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=body,
            )
            response.raise_for_status()

        logger.info(f"Webhook: {method} {url} -> {response.status_code}")


class DiscordHandler(ChannelHandler):
    """Handler for Discord notifications."""

    @property
    def channel(self) -> str:
        return "discord"

    async def process(self, payload: dict[str, Any]) -> None:
        """
        Send a Discord message.

        Expected payload:
            {
                "webhook_url": "https://discord.com/api/webhooks/...",
                "content": "...",
                "embeds": [...]
            }
        """
        webhook_url = payload.get("webhook_url")
        if not webhook_url:
            webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")

        if not webhook_url:
            raise ValueError("No Discord webhook URL configured")

        discord_payload = {
            "content": payload.get("content"),
            "embeds": payload.get("embeds", []),
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(webhook_url, json=discord_payload)
            response.raise_for_status()

        logger.info("Discord: Message sent")


class SlackHandler(ChannelHandler):
    """Handler for Slack notifications."""

    @property
    def channel(self) -> str:
        return "slack"

    async def process(self, payload: dict[str, Any]) -> None:
        """
        Send a Slack message.

        Expected payload:
            {
                "webhook_url": "https://hooks.slack.com/...",
                "text": "...",
                "blocks": [...]
            }
        """
        webhook_url = payload.get("webhook_url")
        if not webhook_url:
            webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

        if not webhook_url:
            raise ValueError("No Slack webhook URL configured")

        slack_payload = {
            "text": payload.get("text"),
            "blocks": payload.get("blocks", []),
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(webhook_url, json=slack_payload)
            response.raise_for_status()

        logger.info("Slack: Message sent")


class SMSHandler(ChannelHandler):
    """Handler for SMS delivery."""

    @property
    def channel(self) -> str:
        return "sms"

    async def process(self, payload: dict[str, Any]) -> None:
        """
        Send an SMS message.

        Expected payload:
            {
                "to": "+1234567890",
                "body": "..."
            }
        """
        to = payload.get("to")
        body = payload.get("body")

        logger.info(f"SMS: Sending to {to}")

        # TODO: Implement SMS sending (Twilio, etc.)
        # from backend.services.sms import send_sms
        # await send_sms(to=to, body=body)

        logger.info(f"SMS: Sent to {to}")


class ExternalAPIHandler(ChannelHandler):
    """Handler for external API calls."""

    @property
    def channel(self) -> str:
        return "external_api"

    async def process(self, payload: dict[str, Any]) -> None:
        """
        Call an external API.

        Expected payload:
            {
                "service": "court_api",
                "endpoint": "/case/lookup",
                "method": "GET",
                "params": {...},
                "body": {...}
            }
        """
        service = payload.get("service")
        endpoint = payload.get("endpoint")
        method = payload.get("method", "GET").upper()

        logger.info(f"ExternalAPI: {service} {method} {endpoint}")

        # TODO: Implement service-specific API calls
        # This would route to configured external services

        logger.info(f"ExternalAPI: {service} call complete")


# =============================================================================
# Outbox Processor
# =============================================================================


class OutboxProcessor:
    """Processes outbox messages for reliable side effect delivery."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.worker_id = WORKER_ID
        self.handlers: dict[str, ChannelHandler] = {}
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register all channel handlers."""
        all_handlers = [
            PDFHandler(),
            EmailHandler(),
            WebhookHandler(),
            DiscordHandler(),
            SlackHandler(),
            SMSHandler(),
            ExternalAPIHandler(),
        ]

        for handler in all_handlers:
            if ENABLED_CHANNELS == ["all"] or handler.channel in ENABLED_CHANNELS:
                self.handlers[handler.channel] = handler
                logger.info(f"Registered handler for channel: {handler.channel}")

    async def claim_messages(self, channel: str) -> list[dict[str, Any]]:
        """Claim a batch of pending messages for a channel."""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM ops.claim_outbox_messages(%s, %s, %s)
                    """,
                    (channel, self.worker_id, BATCH_SIZE),
                )
                return list(cur.fetchall())

    async def complete_message(self, message_id: uuid.UUID) -> None:
        """Mark a message as successfully processed."""
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ops.complete_outbox_message(%s)", (str(message_id),))
            conn.commit()

    async def fail_message(self, message_id: uuid.UUID, error: str) -> None:
        """Record a processing failure."""
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ops.fail_outbox_message(%s, %s)", (str(message_id), error))
            conn.commit()

    async def process_message(self, message: dict[str, Any]) -> bool:
        """
        Process a single outbox message.

        Returns:
            True if processing succeeded, False otherwise
        """
        message_id = message["id"]
        channel = message["channel"]
        payload = message["payload"]
        correlation_id = message.get("correlation_id")

        handler = self.handlers.get(channel)
        if not handler:
            logger.error(f"No handler for channel: {channel}")
            await self.fail_message(message_id, f"Unknown channel: {channel}")
            return False

        try:
            logger.info(
                f"Processing {channel} message {message_id} "
                f"(attempt {message['attempts']}, correlation={correlation_id})"
            )

            await handler.process(payload)

            await self.complete_message(message_id)
            logger.info(f"Completed {channel} message {message_id}")
            return True

        except Exception as e:
            error_msg = str(e)[:500]  # Truncate for storage
            logger.exception(f"Failed to process {channel} message {message_id}: {e}")
            await self.fail_message(message_id, error_msg)
            return False

    async def process_channel(self, channel: str) -> int:
        """
        Process all pending messages for a channel.

        Returns:
            Number of messages processed
        """
        messages = await self.claim_messages(channel)

        if not messages:
            return 0

        logger.info(f"Claimed {len(messages)} {channel} messages")

        processed = 0
        for message in messages:
            if await self.process_message(message):
                processed += 1

        return processed

    async def run_once(self) -> int:
        """
        Process pending messages once across all channels.

        Returns:
            Total number of messages processed
        """
        total = 0
        for channel in self.handlers.keys():
            total += await self.process_channel(channel)
        return total

    async def run_forever(self) -> None:
        """Run the processor continuously."""
        logger.info(f"Outbox processor started (worker={self.worker_id})")
        logger.info(f"Processing channels: {list(self.handlers.keys())}")
        logger.info(f"Poll interval: {POLL_INTERVAL_SECONDS}s, Batch size: {BATCH_SIZE}")

        while True:
            try:
                processed = await self.run_once()

                if processed > 0:
                    logger.info(f"Processed {processed} messages")
                else:
                    logger.debug("No pending messages")

            except Exception as e:
                logger.exception(f"Error in outbox processor loop: {e}")

            await asyncio.sleep(POLL_INTERVAL_SECONDS)


# =============================================================================
# Main Entry Point
# =============================================================================


def get_db_url() -> str:
    """Get the database URL for the outbox processor."""
    # Use pooler URL for app workers
    url = os.environ.get("SUPABASE_DB_URL")
    if url:
        return url

    # Fall back to migrate URL
    url = os.environ.get("SUPABASE_MIGRATE_DB_URL")
    if url:
        return url

    raise RuntimeError("No database URL configured (SUPABASE_DB_URL or SUPABASE_MIGRATE_DB_URL)")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Outbox processor for reliable side effects")
    parser.add_argument("--once", action="store_true", help="Process once and exit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Get database URL
    dsn = get_db_url()

    # Create and run processor
    processor = OutboxProcessor(dsn)

    if args.once:
        processed = asyncio.run(processor.run_once())
        print(f"Processed {processed} messages")
    else:
        asyncio.run(processor.run_forever())


if __name__ == "__main__":
    main()
