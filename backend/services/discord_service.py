"""
Dragonfly Engine - Discord Notification Service

Helper functions to post messages to Discord via webhook.
Used for alerting, daily summaries, and error notifications.
"""

import logging
from typing import Any

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)


class DiscordService:
    """
    Discord webhook client for sending notifications.

    Usage:
        async with DiscordService() as discord:
            await discord.send_message("Hello from Dragonfly!")
    """

    def __init__(self, webhook_url: str | None = None):
        """
        Initialize Discord service.

        Args:
            webhook_url: Discord webhook URL. If not provided, uses env var.
        """
        if webhook_url is None:
            settings = get_settings()
            webhook_url = (
                str(settings.discord_webhook_url)
                if settings.discord_webhook_url
                else None
            )

        self.webhook_url = webhook_url
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        """Check if Discord webhook is configured."""
        return self.webhook_url is not None

    async def __aenter__(self) -> "DiscordService":
        self._client = httpx.AsyncClient(timeout=10.0)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def send_message(
        self,
        content: str,
        username: str = "Dragonfly Engine",
        avatar_url: str | None = None,
    ) -> bool:
        """
        Send a simple text message to Discord.

        Args:
            content: Message content (supports Markdown)
            username: Bot username to display
            avatar_url: Optional avatar URL

        Returns:
            True if message was sent successfully
        """
        if not self.is_configured:
            logger.debug("Discord webhook not configured, skipping message")
            return False

        if self._client is None:
            raise RuntimeError("DiscordService not initialized. Use async with.")

        payload: dict[str, Any] = {
            "content": content,
            "username": username,
        }

        if avatar_url:
            payload["avatar_url"] = avatar_url

        try:
            response = await self._client.post(self.webhook_url, json=payload)
            response.raise_for_status()
            logger.debug(f"Discord message sent: {content[:50]}...")
            return True
        except httpx.HTTPError as e:
            logger.error(f"Failed to send Discord message: {e}")
            return False

    async def send_embed(
        self,
        title: str,
        description: str,
        color: int = 0x5865F2,  # Discord blurple
        fields: list[dict[str, Any]] | None = None,
        footer: str | None = None,
        username: str = "Dragonfly Engine",
    ) -> bool:
        """
        Send a rich embed message to Discord.

        Args:
            title: Embed title
            description: Embed description
            color: Embed color (hex)
            fields: Optional list of field dicts with name, value, inline
            footer: Optional footer text
            username: Bot username

        Returns:
            True if message was sent successfully
        """
        if not self.is_configured:
            logger.debug("Discord webhook not configured, skipping embed")
            return False

        if self._client is None:
            raise RuntimeError("DiscordService not initialized. Use async with.")

        embed: dict[str, Any] = {
            "title": title,
            "description": description,
            "color": color,
        }

        if fields:
            embed["fields"] = fields

        if footer:
            embed["footer"] = {"text": footer}

        payload = {
            "username": username,
            "embeds": [embed],
        }

        try:
            response = await self._client.post(self.webhook_url, json=payload)
            response.raise_for_status()
            logger.debug(f"Discord embed sent: {title}")
            return True
        except httpx.HTTPError as e:
            logger.error(f"Failed to send Discord embed: {e}")
            return False

    async def send_error(
        self,
        error_title: str,
        error_message: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """
        Send an error notification to Discord.

        Args:
            error_title: Short error title
            error_message: Detailed error message
            context: Optional context dict for debugging

        Returns:
            True if message was sent successfully
        """
        fields = []
        if context:
            for key, value in context.items():
                fields.append(
                    {
                        "name": key,
                        "value": (
                            f"```{value}```" if isinstance(value, str) else str(value)
                        ),
                        "inline": True,
                    }
                )

        return await self.send_embed(
            title=f"🚨 {error_title}",
            description=error_message,
            color=0xED4245,  # Discord red
            fields=fields,
            footer="Dragonfly Engine Error Alert",
        )


# =============================================================================
# Convenience Functions
# =============================================================================


async def send_discord_message(
    content: str,
    username: str = "Dragonfly Engine",
) -> bool:
    """
    Quick helper to send a Discord message.

    Args:
        content: Message content
        username: Bot username

    Returns:
        True if sent successfully
    """
    async with DiscordService() as discord:
        return await discord.send_message(content, username)


async def send_discord_error(
    error_title: str,
    error_message: str,
    context: dict[str, Any] | None = None,
) -> bool:
    """
    Quick helper to send a Discord error alert.

    Args:
        error_title: Short error title
        error_message: Detailed error message
        context: Optional context for debugging

    Returns:
        True if sent successfully
    """
    async with DiscordService() as discord:
        return await discord.send_error(error_title, error_message, context)


async def send_discord_embed(
    title: str,
    description: str,
    color: int = 0x5865F2,
    fields: list[dict[str, Any]] | None = None,
) -> bool:
    """
    Quick helper to send a Discord embed.

    Args:
        title: Embed title
        description: Embed description
        color: Embed color
        fields: Optional fields

    Returns:
        True if sent successfully
    """
    async with DiscordService() as discord:
        return await discord.send_embed(title, description, color, fields)
