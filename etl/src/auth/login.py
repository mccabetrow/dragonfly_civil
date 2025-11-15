"""Playwright workflow for establishing a WebCivil session."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import List

from playwright.sync_api import (  # type: ignore[import-not-found]
    BrowserContext,
    Error,
    TimeoutError,
    sync_playwright,
)

from ..settings import get_settings
from ..utils.log import get_logger
from .playwright_utils import (
    create_browser_and_context,
    prepare_page,
    stealth_delay,
)

__all__ = ["run_login"]

_LOG = get_logger(__name__)

LOGIN_URL = "https://iapps.courts.state.ny.us/webcivilLocal/LCIndex"


def _get_credentials() -> tuple[str, str]:
    settings = get_settings()
    username = settings.web_civil_user
    password = settings.web_civil_pass
    if not username or not password:
        raise ValueError("WEB_CIVIL_USER and WEB_CIVIL_PASS must be configured")
    return username, password


def _capture_failure_screenshot(context: BrowserContext, suffix: str = "failure") -> Path:
    timestamp = int(time.time())
    target = Path(tempfile.gettempdir()) / f"webcivil_login_{suffix}_{timestamp}.png"
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.screenshot(path=str(target), full_page=True)
        _LOG.info("Saved login failure screenshot to %s", target)
    except Error as exc:  # pragma: no cover - defensive
        _LOG.warning("Unable to capture login screenshot: %s", exc)
    return target


def run_login() -> List[dict]:
    """Authenticate against WebCivil and return cookies suitable for persistence."""

    username, password = _get_credentials()
    settings = get_settings()
    start = time.perf_counter()
    _LOG.info("Starting WebCivil login flow against %s", LOGIN_URL)

    with sync_playwright() as p:
        browser, context, cfg = create_browser_and_context(p)
        page = context.new_page()
        prepare_page(context, page, stealth=cfg.stealth)
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            stealth_delay(cfg.stealth)
            page.fill(settings.user_selector, username)
            stealth_delay(cfg.stealth)
            page.fill(settings.pass_selector, password)
            stealth_delay(cfg.stealth)
            page.click(settings.submit_selector)
            try:
                page.wait_for_selector(settings.post_login_selector, timeout=5_000)
            except (TimeoutError, Error) as exc:
                screenshot_path = _capture_failure_screenshot(context)
                elapsed = time.perf_counter() - start
                _LOG.error(
                    "Login failed after %.2fs; selector %s not found (screenshot: %s)",
                    elapsed,
                    settings.post_login_selector,
                    screenshot_path,
                )
                raise RuntimeError("Login failed") from exc

            cookies = context.cookies()
            elapsed = time.perf_counter() - start
            _LOG.info("Login succeeded; captured %d cookies in %.2fs", len(cookies), elapsed)
            return cookies
        finally:
            context.close()
            browser.close()
