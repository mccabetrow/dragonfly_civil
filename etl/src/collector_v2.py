"""Collector v2 workflow that validates sessions and pushes Supabase composites."""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List, Tuple
from uuid import UUID, uuid4

from dotenv import load_dotenv
import requests  # type: ignore[import-not-found]
from requests import Response  # type: ignore[import-not-found]

from playwright.sync_api import (  # type: ignore[import-not-found]
    Error as PlaywrightError,
    TimeoutError,
    sync_playwright,
)

from .auth.session_manager import (
    attach_cookies_to_playwright,
    ensure_session,
    get_requests_session_with_cookies,
)
from .settings import get_settings
from .telemetry.auth import AuthEventKind, record_auth_event
from .utils.log import get_logger

load_dotenv()

_LOG = get_logger(__name__)

AUTHENTICATED_SELECTOR = "#searchForm"
PLAYWRIGHT_TIMEOUT_MS = 6_000
DEMO_CASE_NUMBER = "SMOKE-DEMO-0001"
LOGIN_INDICATORS = ("login", "userid", "password")
SUPABASE_RPC = "insert_or_get_case_with_entities"
SUPABASE_TIMEOUT = 20


def _truncate(text: str, length: int = 160) -> str:
    snippet = text.strip()
    if len(snippet) <= length:
        return snippet
    return snippet[: length - 3] + "..."


def _navigate_authenticated_page(cookies: List[dict], *, run_id: UUID) -> List[dict]:
    settings = get_settings()
    auth_url = settings.authenticated_url
    attempt_cookies = cookies
    for attempt in (1, 2):
        with sync_playwright() as playwright:  # type: ignore[attr-defined]
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(timezone_id=settings.timezone)
            try:
                attach_cookies_to_playwright(context, attempt_cookies)
                page = context.new_page()
                _LOG.info(
                    "Navigating to authenticated page %s (attempt=%d)",
                    auth_url,
                    attempt,
                )
                page.goto(
                    auth_url,
                    wait_until="domcontentloaded",
                    timeout=PLAYWRIGHT_TIMEOUT_MS,
                )
                marker = page.query_selector(AUTHENTICATED_SELECTOR)
                if marker is None:
                    _LOG.warning(
                        "Authenticated selector %s missing; refreshing session",
                        AUTHENTICATED_SELECTOR,
                    )
                    if attempt == 2:
                        raise RuntimeError(
                            "Authenticated selector missing after session refresh"
                        )
                    attempt_cookies = ensure_session(refresh_if_invalid=True, run_id=run_id)
                    continue

                snippet = _truncate(marker.inner_text() or "")
                _LOG.info(
                    "Authenticated selector located; text preview=%s",
                    snippet,
                )
                return attempt_cookies
            except (TimeoutError, PlaywrightError) as exc:
                _LOG.warning("Playwright navigation failed: %s", exc)
                if attempt == 2:
                    raise RuntimeError("Playwright navigation failed") from exc
                attempt_cookies = ensure_session(refresh_if_invalid=True, run_id=run_id)
            finally:
                context.close()
                browser.close()
    return attempt_cookies


def _looks_like_login_response(response: Response) -> bool:
    if response.status_code in {401, 403}:
        return True
    url_lower = response.url.lower()
    if any(token in url_lower for token in LOGIN_INDICATORS):
        return True
    text_lower = response.text.lower()[:2_048]
    return any(token in text_lower for token in LOGIN_INDICATORS)


def _fetch_authenticated_page(
    session: requests.Session,
    url: str,
    *,
    run_id: UUID,
) -> Tuple[requests.Session, Response]:
    refreshed = False
    while True:
        response = session.get(url, timeout=10, allow_redirects=True)
        if _looks_like_login_response(response):
            if refreshed:
                raise RuntimeError("Received login response after session refresh")
            _LOG.info("WebCivil response indicates login; refreshing session")
            refreshed_cookies = ensure_session(refresh_if_invalid=True, run_id=run_id)
            session = get_requests_session_with_cookies(refreshed_cookies)
            refreshed = True
            continue
        response.raise_for_status()
        return session, response


def _scrape_metadata(response: Response) -> Dict[str, Any]:
    return {
        "status_code": response.status_code,
        "url": response.url,
        "preview": _truncate(response.text, 200),
    }


def _demo_payload(case_number: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "case": {
            "case_number": case_number,
            "source": "demo",
            "title": "Dragonfly Demo Collections v. Sample Defendant",
            "court": "NYC Civil Court",
            "amount_awarded": 12500.00,
            "metadata": metadata,
        },
        "entities": [
            {
                "role": "plaintiff",
                "name_full": "Dragonfly Demo Collections",
                "emails": ["demo-plaintiff@example.com"],
            },
            {
                "role": "defendant",
                "name_full": "Sample Defendant",
                "phones": ["+12125551234"],
                "address": {
                    "line1": "123 Demo Street",
                    "city": "Queens",
                    "state": "NY",
                    "postal_code": "11368",
                },
            },
        ],
    }


def _generic_payload(case_number: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "case": {
            "case_number": case_number,
            "source": "webcivil",
            "title": f"Auto scrape {case_number}",
            "court": "NYC Civil Court",
            "metadata": metadata,
        },
        "entities": [
            {
                "role": "plaintiff",
                "name_full": "Automation Plaintiff",
                "emails": ["plaintiff@example.com"],
            },
            {
                "role": "defendant",
                "name_full": f"Defendant {case_number}",
                "phones": ["+12125559876"],
            },
        ],
    }


def _build_composite_payload(case_number: str, response: Response) -> Dict[str, Any]:
    metadata = _scrape_metadata(response)
    if case_number.upper() == DEMO_CASE_NUMBER:
        return _demo_payload(case_number.upper(), metadata)
    return _generic_payload(case_number.upper(), metadata)


def _supabase_credentials() -> Tuple[str, str]:
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    if not base:
        raise RuntimeError("SUPABASE_URL environment variable is required")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not key:
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY must be configured for Supabase RPC access"
        )
    return base, key


def _call_supabase_composite(payload: Dict[str, Any]) -> Dict[str, Any]:
    base, key = _supabase_credentials()
    rpc_url = f"{base}/rest/v1/rpc/{SUPABASE_RPC}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": "return=representation",
    }
    response = requests.post(rpc_url, headers=headers, json={"payload": payload}, timeout=SUPABASE_TIMEOUT)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:  # pragma: no cover - network guard
        raise RuntimeError(f"Supabase RPC {SUPABASE_RPC} failed: {response.text}") from exc
    data: Any = response.json()
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return first
    if isinstance(data, dict):
        return data
    raise RuntimeError(f"Unexpected Supabase RPC payload: {data!r}")


def _emit_scrape_event(
    kind: AuthEventKind,
    *,
    case_number: str,
    run_id: UUID,
    started_at: float,
    reason: str | None,
    ok: bool,
) -> None:
    latency_ms = 0 if kind == "scrape_start" else int((time.perf_counter() - started_at) * 1_000)
    reason_payload = f"case={case_number}" + (f" {reason}" if reason else "")
    record_auth_event(kind, ok=ok, latency_ms=latency_ms, reason=reason_payload, run_id=run_id)


def _run(case_number: str, *, run_id: UUID, dry_run: bool) -> Dict[str, Any]:
    started = time.perf_counter()
    _emit_scrape_event("scrape_start", case_number=case_number, run_id=run_id, started_at=started, reason=None, ok=True)

    try:
        cookies = ensure_session(run_id=run_id)
        cookies = _navigate_authenticated_page(cookies, run_id=run_id)
        session = get_requests_session_with_cookies(cookies)
        session, response = _fetch_authenticated_page(session, get_settings().authenticated_url, run_id=run_id)
        payload = _build_composite_payload(case_number, response)
        if dry_run:
            _LOG.info("Dry-run mode: skipping Supabase RPC for case_number=%s", case_number)
            _LOG.debug("Dry-run payload preview: %s", payload)
            result = {"case_id": None, "entity_ids": []}
        else:
            result = _call_supabase_composite(payload)
    except Exception as exc:
        _emit_scrape_event(
            "scrape_error",
            case_number=case_number,
            run_id=run_id,
            started_at=started,
            reason=str(exc),
            ok=False,
        )
        raise

    entity_ids = result.get("entity_ids") or []
    if dry_run:
        _LOG.info("Dry-run complete for case_number=%s (payload not persisted)", case_number)
    else:
        _LOG.info(
            "Supabase %s succeeded (case_number=%s case_id=%s entities=%d)",
            SUPABASE_RPC,
            case_number,
            result.get("case_id"),
            len(entity_ids),
        )

    _emit_scrape_event("scrape_ok", case_number=case_number, run_id=run_id, started_at=started, reason=None, ok=True)
    return result


def main(args: argparse.Namespace) -> int:
    case_number = (args.case_number or DEMO_CASE_NUMBER).strip().upper()
    run_id = uuid4()
    try:
        result = _run(case_number, run_id=run_id, dry_run=args.dry_run)
        if args.dry_run:
            _LOG.debug("Dry-run result payload: %s", result)
        return 0
    except Exception as exc:  # pragma: no cover - CLI entry point
        _LOG.error("collector_v2 execution failed: %s", exc, exc_info=True)
        return 1


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collector v2 WebCivil scraper")
    parser.add_argument("--composite", action="store_true", help="Retained for CLI compatibility (unused)")
    parser.add_argument("--entity", action="store_true", help="Retained for CLI compatibility (unused)")
    parser.add_argument("--force-insert", action="store_true", help="Retained for CLI compatibility (unused)")
    parser.add_argument("--case-id", dest="case_id", help="Existing case_id reference (unused)")
    parser.add_argument(
        "--case-number",
        dest="case_number",
        default=DEMO_CASE_NUMBER,
        help=f"Case number to scrape (default: {DEMO_CASE_NUMBER}). Use {DEMO_CASE_NUMBER} for demo payload.",
    )
    parser.add_argument(
        "--use-idempotent-composite",
        action="store_true",
        dest="use_idempotent_composite",
        help="Deprecated; insert_or_get_case_with_entities is always used.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip interpreting Supabase response beyond logging",
    )
    return parser


if __name__ == "__main__":
    parser = _build_arg_parser()
    namespace = parser.parse_args()
    sys.exit(main(namespace))
