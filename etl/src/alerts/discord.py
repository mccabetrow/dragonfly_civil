"""Discord alert helpers."""

from __future__ import annotations

from typing import Optional

import requests  # type: ignore[import-not-found]

from ..settings import get_settings
from ..utils.log import get_logger

_LOG = get_logger(__name__)

_DEFAULT_TIMEOUT = 3


def post_simple(message: str, level: str = "INFO") -> None:
	"""Send a best-effort Discord webhook alert."""

	settings = get_settings()
	webhook_url: Optional[str] = settings.discord_webhook_url
	if not webhook_url:
		_LOG.debug("Discord webhook URL not configured; skipping alert")
		return

	content = f"[{level.upper()}] {message}"
	try:
		response = requests.post(webhook_url, json={"content": content}, timeout=_DEFAULT_TIMEOUT)
		response.raise_for_status()
	except Exception as exc:  # pragma: no cover - alerting is best effort
		_LOG.warning("Discord alert failed: %s", exc)
