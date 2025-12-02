"""Trigger a PostgREST schema cache reload for Supabase.

This module provides a thin CLI wrapper that calls the
``pgrst_reload`` RPC exposed by Supabase. It mirrors the style of the
other utilities in the ``tools`` package so it can be launched via
``python -m tools.pgrst_reload``.
"""

from __future__ import annotations

import sys
from typing import Final

import requests

from src.supabase_client import get_settings

RELOAD_PATH: Final[str] = "/rest/v1/rpc/pgrst_reload"


def _resolve_endpoint(base_url: str) -> str:
    if base_url.endswith("/"):
        return f"{base_url.rstrip('/')}{RELOAD_PATH}"
    return f"{base_url}{RELOAD_PATH}"


def _request_headers(api_key: str) -> dict[str, str]:
    return {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _reload_schema(url: str, api_key: str) -> None:
    endpoint = _resolve_endpoint(url)
    response = requests.post(endpoint, headers=_request_headers(api_key), json={})
    if 200 <= response.status_code < 300:
        print("[pgrst_reload] Schema cache reload triggered successfully.")
        return

    try:
        detail = response.json()
    except ValueError:
        detail = response.text

    print(
        "[pgrst_reload] Failed to reload schema cache:",
        f"status={response.status_code}",
        f"body={detail}",
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> None:
    settings = get_settings()
    base_url = settings.supabase_url
    api_key = settings.supabase_service_role_key

    if not base_url or not api_key:
        print(
            "[pgrst_reload] Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in environment.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        _reload_schema(base_url, api_key)
    except requests.RequestException as exc:
        print(f"[pgrst_reload] Network failure: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
