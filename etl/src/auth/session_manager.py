import asyncio
import json
import logging
import os
import socket
import stat
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

try:  # pragma: no cover - optional dependency handled at runtime
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover
    Fernet = None  # type: ignore[assignment]

    class InvalidToken(Exception):
        """Fallback InvalidToken definition when cryptography is unavailable."""

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from etl.src.alerts.discord import post_simple as post_to_discord
from etl.src.auth.login import run_login
from etl.src.telemetry.auth import record_auth_event
from etl.src.settings import get_settings as get_etl_settings
from src.settings import ensure_parent_dir, get_settings as get_app_settings


log = logging.getLogger(__name__)
logger = log


def _cookie_list_to_map(cookies: Any) -> Dict[str, str]:
    if not isinstance(cookies, list):
        return {}
    simple: Dict[str, str] = {}
    for item in cookies:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if not name or value is None:
            continue
        simple[str(name)] = str(value)
    return simple


def _cookie_map_to_list(cookie_map: Any) -> List[Dict[str, Any]]:
    if isinstance(cookie_map, list):
        return [c for c in cookie_map if isinstance(c, dict)]
    if not isinstance(cookie_map, dict):
        return []
    result: List[Dict[str, Any]] = []
    for name, value in cookie_map.items():
        if value is None:
            continue
        result.append({"name": str(name), "value": str(value), "url": "https://example.com"})
    return result


def _normalise_session_payload(raw: Any) -> Dict[str, Any]:
    payload: Dict[str, Any]
    if isinstance(raw, dict):
        payload = dict(raw)
    elif isinstance(raw, list):
        payload = {"playwright_cookies": [c for c in raw if isinstance(c, dict)]}
    else:
        return {}

    # Extract canonical cookie list and map representations
    cookie_list: List[Dict[str, Any]] = []

    if isinstance(payload.get("playwright_cookies"), list):
        cookie_list = [c for c in payload["playwright_cookies"] if isinstance(c, dict)]
    elif isinstance(payload.get("cookies"), list):
        cookie_list = [c for c in payload["cookies"] if isinstance(c, dict)]

    cookie_map: Dict[str, str]
    if isinstance(payload.get("cookies"), dict):
        cookie_map = {str(k): str(v) for k, v in payload["cookies"].items() if v is not None}
    else:
        cookie_map = {}

    if not cookie_list and cookie_map:
        cookie_list = _cookie_map_to_list(cookie_map)

    if not cookie_map and cookie_list:
        cookie_map = _cookie_list_to_map(cookie_list)

    payload["playwright_cookies"] = cookie_list
    payload["cookies"] = cookie_map

    meta = payload.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    meta.setdefault("saved_at", int(time.time()))
    payload["meta"] = meta
    return payload

CB_MAX_FAILURES = 3
CB_WINDOW_SEC = 600


def _app_settings():
    return get_app_settings()


def _session_path(path_override: Optional[os.PathLike[str] | str | None] = None) -> Path:
    if path_override is not None:
        candidate = Path(path_override).expanduser()
        try:
            ensure_parent_dir(str(candidate))
        except Exception as exc:  # pragma: no cover - defensive guard
            log.warning("Unable to ensure session directory for %s: %s", candidate, exc)
        return candidate

    settings = _app_settings()
    try:
        ensure_parent_dir(settings.SESSION_PATH)
    except Exception as exc:  # pragma: no cover - defensive guard
        log.warning("Unable to ensure session directory for %s: %s", settings.SESSION_PATH, exc)
    return Path(settings.SESSION_PATH).expanduser()


def _circuit_breaker_file() -> Path:
    return _session_path().parent / ".cb_fail_count"


def _should_encrypt() -> bool:
    try:
        return bool(_app_settings().ENCRYPT_SESSIONS)
    except Exception:  # pragma: no cover - defensive
        return False


def _kms_key() -> Optional[str]:
    try:
        key = _app_settings().SESSION_KMS_KEY
        return key.strip() if isinstance(key, str) else key
    except Exception:  # pragma: no cover
        return None


def _dpapi_protect(data: bytes) -> bytes:
    import ctypes
    from ctypes import POINTER, Structure, byref, c_char, c_uint, create_string_buffer

    class DATA_BLOB(Structure):
        _fields_ = [("cbData", c_uint), ("pbData", POINTER(c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buffer = create_string_buffer(data)
    blob_in = DATA_BLOB(len(data), ctypes.cast(buffer, POINTER(c_char)))
    blob_out = DATA_BLOB()
    if not crypt32.CryptProtectData(byref(blob_in), None, None, None, None, 0, byref(blob_out)):
        raise OSError(ctypes.GetLastError(), "CryptProtectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    import ctypes
    from ctypes import POINTER, Structure, byref, c_char, c_uint, create_string_buffer

    class DATA_BLOB(Structure):
        _fields_ = [("cbData", c_uint), ("pbData", POINTER(c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buffer = create_string_buffer(data)
    blob_in = DATA_BLOB(len(data), ctypes.cast(buffer, POINTER(c_char)))
    blob_out = DATA_BLOB()
    if not crypt32.CryptUnprotectData(byref(blob_in), None, None, None, None, 0, byref(blob_out)):
        raise OSError(ctypes.GetLastError(), "CryptUnprotectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _encrypt_bytes(data: bytes) -> bytes:
    if not _should_encrypt():
        return data

    key = _kms_key()
    if key:
        if Fernet is None:
            log.error("SESSION_KMS_KEY provided but cryptography is not installed; storing plaintext")
            return data
        try:
            return Fernet(key.encode("utf-8")).encrypt(data)
        except Exception as exc:
            log.error("Fernet encryption failed; storing plaintext: %s", exc)
            return data

    if os.name == "nt":
        try:
            return _dpapi_protect(data)
        except Exception as exc:
            log.warning("DPAPI encryption failed; storing plaintext: %s", exc)

    return data


def _decrypt_bytes(data: bytes) -> bytes:
    if not data:
        return data

    if not _should_encrypt():
        return data

    key = _kms_key()
    if key:
        if Fernet is None:
            log.error("SESSION_KMS_KEY provided but cryptography is not installed; returning raw bytes")
            return data
        try:
            return Fernet(key.encode("utf-8")).decrypt(data)
        except InvalidToken:
            log.warning("Fernet decrypt failed due to invalid token; returning raw bytes")
            return data
        except Exception as exc:
            log.warning("Fernet decrypt failed (%s); returning raw bytes", exc)
            return data

    if os.name == "nt":
        try:
            return _dpapi_unprotect(data)
        except Exception as exc:
            log.warning("DPAPI decrypt failed; returning raw bytes: %s", exc)
            return data

    return data


class CircuitOpenError(Exception):
    """Raised when the auth refresh circuit breaker is open."""


class SessionValidationError(Exception):
    """Raised when a session fails validation."""


class ScrapeAuthError(Exception):
    """Raised when auth fails mid-scrape (for example, a login redirect)."""


def _check_session_file_permissions(path: Path) -> None:
    """Ensure the cached session file is not world-readable."""
    if not path.exists():
        return
    if os.name == "posix":
        mode = path.stat().st_mode
        if (mode & stat.S_IRWXG) or (mode & stat.S_IRWXO):
            perms = oct(mode & 0o777)
            raise RuntimeError(
                f"Session file {path} has insecure permissions ({perms}). "
                f"Run 'chmod 600 {path}' before proceeding."
            )
    elif os.name == "nt":
        log.debug("Skipping session file permission check on Windows hosts.")


def load_session(path_override: Optional[os.PathLike[str] | str] = None) -> Optional[Dict[str, Any]]:
    """Load and decrypt cached session payload, returning None when unavailable."""
    path = _session_path(path_override)
    _check_session_file_permissions(path)
    if not path.exists():
        log.debug("No cached session data at %s", path)
        return None
    try:
        payload = path.read_bytes()
    except OSError as exc:
        log.error("Unable to read session file %s: %s", path, exc)
        return None
    if not payload:
        log.warning("Session file %s is empty; ignoring", path)
        return None
    try:
        decrypted = _decrypt_bytes(payload)
        raw_payload = json.loads(decrypted.decode("utf-8"))
    except Exception as exc:
        log.error("Failed to decode cached session; removing file (%s)", exc)
        path.unlink(missing_ok=True)
        return None

    normalised = _normalise_session_payload(raw_payload)
    cookie_count = len(normalised.get("playwright_cookies", []))
    log.info("Loaded %d cookies from %s", cookie_count, path)
    return normalised


def save_session(
    payload: List[Dict[str, Any]] | Dict[str, Any],
    path_override: Optional[os.PathLike[str] | str] = None,
) -> None:
    """Encrypt and persist session payload to disk with secure permissions."""
    if isinstance(payload, dict):
        raw_payload = dict(payload)  # shallow copy to avoid mutating caller data
    elif isinstance(payload, list):
        raw_payload = {"playwright_cookies": [c for c in payload if isinstance(c, dict)]}
    else:
        log.error("Unsupported payload type for save_session: %s", type(payload))
        return

    normalised = _normalise_session_payload(raw_payload)

    try:
        encoded = json.dumps(normalised).encode("utf-8")
        encrypted = _encrypt_bytes(encoded)
    except Exception as exc:
        log.error("Failed to encrypt session payload: %s", exc)
        return

    path = _session_path(path_override)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(encrypted)
    except OSError as exc:
        log.error("Unable to write session file %s: %s", path, exc)
        return

    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except OSError as exc:
            log.warning("Failed to chmod session file %s: %s", path, exc)

    log.info("Saved encrypted session payload to %s", path)


async def _get_new_playwright_context(playwright: Playwright) -> tuple[Browser, BrowserContext]:
    """Launch a fresh browser and context using configured settings."""
    settings = get_etl_settings()
    launch_options: Dict[str, Any] = {"headless": getattr(settings, "headless", True)}
    if getattr(settings, "proxy_url", None):
        launch_options["proxy"] = {"server": settings.proxy_url}

    browser = await playwright.chromium.launch(**launch_options)

    try:
        viewport_raw = str(getattr(settings, "viewport", "1280x800"))
        width, height = map(int, viewport_raw.replace("x", ",").split(","))
    except Exception:
        width, height = 1280, 800

    context_args: Dict[str, Any] = {
        "locale": getattr(settings, "locale", "en-US"),
        "timezone_id": getattr(settings, "timezone", getattr(settings, "tz", "UTC")),
        "viewport": {"width": width, "height": height},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    context = await browser.new_context(**context_args)

    if getattr(settings, "stealth", getattr(settings, "STEALTH", False)):
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => false});"
        )

    return browser, context


async def _close_browser_context(browser: Browser, context: BrowserContext) -> None:
    """Best-effort shutdown of a browser context and the owning browser."""
    try:
        await context.close()
    except Exception:
        log.debug("Context close raised an exception", exc_info=True)
    try:
        if browser.is_connected():
            await browser.close()
    except Exception:
        log.debug("Browser close raised an exception", exc_info=True)


async def validate_session(
    context: BrowserContext,
    *,
    run_id: Optional[uuid.UUID] = None,
) -> bool:
    """Validate that the provided context still represents an authenticated session."""
    log.debug("Validating cached session via Playwright")
    start = time.monotonic()
    page: Optional[Any] = None
    is_valid = False
    reason = "validation_failed"
    settings = get_etl_settings()

    try:
        page = await context.new_page()
        response = await page.goto(
            getattr(settings, "authenticated_url", getattr(settings, "AUTHENTICATED_URL")),
            wait_until="domcontentloaded",
            timeout=15_000,
        )
        status = response.status if response else 0
        current_url = page.url
        title = await page.title()

        if status >= 400 or (status in {301, 302, 307} and "login" in current_url.lower()):
            reason = f"redirect_or_status_{status}"
            raise SessionValidationError(reason)

        selector = getattr(settings, "post_login_selector", getattr(settings, "POST_LOGIN_SELECTOR", None))
        selector_present = False
        if selector:
            try:
                selector_present = await page.is_visible(selector)
            except Exception:
                selector_present = False

        if selector_present:
            is_valid = True
            reason = "ok_selector_present"
        elif "search" in title.lower() and "login" not in current_url.lower():
            is_valid = True
            reason = "ok_title_match"
        else:
            reason = "selector_missing"
            raise SessionValidationError(reason)

        return is_valid
    except SessionValidationError:
        raise
    except Exception as exc:
        reason = f"validation_error_{type(exc).__name__}"
        raise SessionValidationError(reason) from exc
    finally:
        latency_ms = int((time.monotonic() - start) * 1000)
        record_auth_event("validate", ok=is_valid, latency_ms=latency_ms, reason=reason, run_id=run_id)
        if page is not None:
            try:
                await page.close()
            except Exception:
                log.debug("Failed to close validation page", exc_info=True)


def _check_circuit_breaker() -> None:
    """Raise CircuitOpenError when too many refresh failures happened recently."""
    cb_path = _circuit_breaker_file()
    if not cb_path.exists():
        return
    try:
        now = time.time()
        timestamps = [
            float(line.strip())
            for line in cb_path.read_text().splitlines()
            if line.strip()
        ]
        recent = [stamp for stamp in timestamps if now - stamp < CB_WINDOW_SEC]
        if len(recent) >= CB_MAX_FAILURES:
            raise CircuitOpenError(
                f"Auth refresh failed {len(recent)} times within {CB_WINDOW_SEC} seconds"
            )
        cb_path.write_text("\n".join(str(stamp) for stamp in recent) + ("\n" if recent else ""))
    except CircuitOpenError:
        raise
    except Exception as exc:
        log.warning("Unable to evaluate circuit breaker state: %s", exc)


def _record_circuit_breaker_failure() -> None:
    try:
        cb_path = _circuit_breaker_file()
        cb_path.parent.mkdir(parents=True, exist_ok=True)
        with cb_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.time()}\n")
    except Exception as exc:
        log.warning("Failed to record circuit breaker failure: %s", exc)


def _reset_circuit_breaker() -> None:
    _circuit_breaker_file().unlink(missing_ok=True)


async def ensure_session_async(
    playwright: Playwright,
    *,
    refresh_if_invalid: bool = True,
    run_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Return a dictionary containing a valid browser context, refreshing if required."""
    log.debug("Ensuring cached session is valid")
    start = time.monotonic()
    browser, context = await _get_new_playwright_context(playwright)
    session_payload = load_session()

    cookie_list: List[Dict[str, Any]] = []
    if session_payload:
        raw_cookie_list = session_payload.get("playwright_cookies")
        if isinstance(raw_cookie_list, list):
            cookie_list = [c for c in raw_cookie_list if isinstance(c, dict)]
        if not cookie_list:
            cookie_list = _cookie_map_to_list(session_payload.get("cookies"))

    if cookie_list:
        await context.add_cookies(cookie_list)  # type: ignore[arg-type]
        try:
            if await validate_session(context, run_id=run_id):
                log.info("Cached session validated successfully")
                return {
                    "ok": True,
                    "refreshed": False,
                    "context": context,
                    "browser": browser,
                }
        except SessionValidationError as exc:
            log.info("Cached session validation failed: %s", exc)

    if not refresh_if_invalid:
        log.warning("Session invalid but refresh_if_invalid is False")
        await _close_browser_context(browser, context)
        return {
            "ok": False,
            "refreshed": False,
            "reason": "invalid_no_refresh",
        }

    log.info("Attempting to refresh session via login flow")

    try:
        _check_circuit_breaker()
        new_cookies = await asyncio.to_thread(run_login)
        save_session(new_cookies)
        await context.add_cookies(new_cookies)  # type: ignore[arg-type]
        latency_ms = int((time.monotonic() - start) * 1000)
        record_auth_event("refresh", ok=True, latency_ms=latency_ms, reason=None, run_id=run_id)
        _reset_circuit_breaker()
        return {
            "ok": True,
            "refreshed": True,
            "context": context,
            "browser": browser,
        }
    except CircuitOpenError as exc:
        log.error("Circuit breaker open: %s", exc)
        hostname = os.environ.get("HOSTNAME", socket.gethostname())
        post_to_discord(
            f"AUTH circuit breaker open on host {hostname}; refresh aborted.",
            level="ERROR",
        )
        await _close_browser_context(browser, context)
        return {
            "ok": False,
            "refreshed": False,
            "reason": f"circuit_open: {exc}",
        }
    except Exception as exc:
        log.error("Session refresh failed: %s", exc, exc_info=True)
        _record_circuit_breaker_failure()
        latency_ms = int((time.monotonic() - start) * 1000)
        record_auth_event("refresh", ok=False, latency_ms=latency_ms, reason=str(exc), run_id=run_id)
        hostname = os.environ.get("HOSTNAME", socket.gethostname())
        post_to_discord(
            f"AUTH refresh failed on host {hostname}: {exc}",
            level="ERROR",
        )
        await _close_browser_context(browser, context)
        return {
            "ok": False,
            "refreshed": False,
            "reason": str(exc),
        }


ensure_session_playwright = ensure_session_async


def get_requests_session_with_cookies(
    session_data: Optional[Dict[str, Any]] = None,
) -> requests.Session:
    """Create a requests.Session populated with cached cookies."""
    data = session_data or load_session() or {}
    cookies: Dict[str, str] = {}
    raw_cookies = data.get("cookies")
    if isinstance(raw_cookies, dict):
        cookies = {str(k): str(v) for k, v in raw_cookies.items() if v is not None}
    elif isinstance(raw_cookies, list):  # backwards compatibility
        cookies = _cookie_list_to_map(raw_cookies)

    sess = requests.Session()
    for name, value in cookies.items():
        try:
            sess.cookies.set(name, value)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.debug("cookie set failed for %s: %s", name, exc)
    return sess


def ensure_session() -> requests.Session:
    """Synchronous helper to obtain a requests session populated with cached cookies."""
    return get_requests_session_with_cookies()


def attach_cookies_to_playwright(
    context: BrowserContext,
    session_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Attach cached cookies to a Playwright context when available."""
    data = session_data or load_session() or {}
    cookie_list = data.get("playwright_cookies")
    if not isinstance(cookie_list, list) or not cookie_list:
        cookie_list = _cookie_map_to_list(data.get("cookies"))
    cookies = [c for c in cookie_list if isinstance(c, dict)]
    if not cookies:
        return
    try:
        context.add_cookies(cookies)  # type: ignore[arg-type]
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.debug("attach_cookies_to_playwright failed: %s", exc)


async def main_cli() -> None:
    """Command-line entry point for manual session validation."""
    logging.basicConfig(level=logging.INFO)
    # Reuse the existing module logger for CLI runs
    log.info("Running manual session check")

    try:
        async with async_playwright() as playwright:
            result = await ensure_session_playwright(playwright, refresh_if_invalid=True)
            if result.get("ok") and result.get("context"):
                print(f"Session OK. Refreshed: {result['refreshed']}")
                context = result["context"]
                browser = result.get("browser")
                if isinstance(context, BrowserContext) and isinstance(browser, Browser):
                    await _close_browser_context(browser, context)
            else:
                print(f"Session failed: {result.get('reason')}")
    except Exception as exc:
        print(f"CLI tool failed: {exc}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main_cli())
