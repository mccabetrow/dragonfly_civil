"""Shared Playwright helpers for WebCivil automation."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from ..settings import get_settings
from ..utils.log import get_logger

_LOG = get_logger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from playwright.sync_api import Browser  # type: ignore[import-not-found]
    from playwright.sync_api import BrowserContext, Page, Playwright

__all__ = [
    "PlaywrightConfig",
    "create_browser_and_context",
    "prepare_page",
    "resolve_playwright_config",
    "stealth_delay",
]

_USER_AGENT_DEFAULT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _parse_viewport(raw: Optional[str]) -> Dict[str, int]:
    candidate = (raw or "1280x800").strip()
    try:
        width_str, height_str = candidate.lower().split("x", 1)
        width = int(width_str.strip())
        height = int(height_str.strip())
        return {"width": width, "height": height}
    except Exception:  # pragma: no cover - defensive parsing
        _LOG.warning("Invalid VIEWPORT value '%s'; falling back to 1280x800", raw)
        return {"width": 1280, "height": 800}


@dataclass(frozen=True)
class PlaywrightConfig:
    headless: bool
    stealth: bool
    proxy_url: Optional[str]
    locale: str
    timezone: str
    viewport: Dict[str, int]
    user_agent: Optional[str]


def resolve_playwright_config() -> PlaywrightConfig:
    settings = get_settings()
    headless = settings.headless
    stealth = settings.stealth
    proxy_url = settings.proxy_url
    if proxy_url:
        proxy_url = proxy_url.strip() or None
    locale = settings.locale
    timezone = settings.timezone
    viewport = _parse_viewport(settings.viewport)
    user_agent = settings.user_agent_override
    if not user_agent and stealth:
        user_agent = _USER_AGENT_DEFAULT
    return PlaywrightConfig(
        headless=headless,
        stealth=stealth,
        proxy_url=proxy_url,
        locale=locale,
        timezone=timezone,
        viewport=viewport,
        user_agent=user_agent,
    )


def _launch_options(cfg: PlaywrightConfig) -> Dict[str, Any]:
    options: Dict[str, Any] = {"headless": cfg.headless}
    args = []
    if cfg.stealth:
        args.extend(["--disable-blink-features=AutomationControlled", "--disable-infobars"])
    if cfg.proxy_url:
        options["proxy"] = {"server": cfg.proxy_url}
    if args:
        options["args"] = args
    return options


def _context_options(cfg: PlaywrightConfig) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "locale": cfg.locale,
        "timezone_id": cfg.timezone,
        "viewport": cfg.viewport,
    }
    if cfg.user_agent:
        options["user_agent"] = cfg.user_agent
    return options


_STEALTH_SCRIPT = """
(() => {
  Object.defineProperty(navigator, 'webdriver', {get: () => false});
  Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
  Object.defineProperty(navigator, 'language', {get: () => 'en-US'});
  Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
  Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
  const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
  if (originalQuery) {
    window.navigator.permissions.query = (parameters) => (
      parameters && parameters.name === 'notifications'
        ? Promise.resolve({ state: 'denied' })
        : originalQuery(parameters)
    );
  }
  const patch = (proto) => {
    if (!proto || !proto.prototype) return;
    const originalGetParameter = proto.prototype.getParameter;
    if (originalGetParameter) {
      Object.defineProperty(proto.prototype, 'getParameter', {
        value(parameter) {
          if (parameter === 37445) { return 'Intel Inc.'; }
          if (parameter === 37446) { return 'Intel Iris OpenGL Engine'; }
          return originalGetParameter.call(this, parameter);
        }
      });
    }
  };
  patch(window.WebGLRenderingContext);
  patch(window.WebGL2RenderingContext);
})();
"""


def apply_stealth(context: "BrowserContext") -> None:
    """Apply baseline stealth mitigations to the provided context."""

    context.add_init_script(_STEALTH_SCRIPT)

    def _on_page(page: "Page") -> None:
        try:
            session = context.new_cdp_session(page)
            session.send("Page.addScriptToEvaluateOnNewDocument", {"source": _STEALTH_SCRIPT})
        except Exception as exc:  # pragma: no cover - best effort
            _LOG.debug("Unable to attach stealth CDP session: %s", exc)

    context.on("page", _on_page)


def prepare_page(context: "BrowserContext", page: "Page", *, stealth: bool) -> None:
    if stealth:
        try:
            session = context.new_cdp_session(page)
            session.send("Page.addScriptToEvaluateOnNewDocument", {"source": _STEALTH_SCRIPT})
        except Exception as exc:  # pragma: no cover - best effort
            _LOG.debug("Unable to add stealth script to page: %s", exc)


def stealth_delay(enabled: bool) -> None:
    if not enabled:
        return
    time.sleep(random.uniform(0.05, 0.25))


def create_browser_and_context(
    playwright: "Playwright",
) -> Tuple["Browser", "BrowserContext", PlaywrightConfig]:
    cfg = resolve_playwright_config()
    browser = playwright.chromium.launch(**_launch_options(cfg))
    context = browser.new_context(**_context_options(cfg))
    if cfg.stealth:
        apply_stealth(context)
    return browser, context, cfg
