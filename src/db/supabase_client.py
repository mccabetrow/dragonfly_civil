"""Utilities for connecting to Supabase using the service role."""

from __future__ import annotations

from typing import Optional

import httpx

from src.config.api_surface import BASE_URL, SCHEMA_PROFILE, SERVICE_KEY

try:  # pragma: no cover - optional dependency
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover - python-dotenv not installed
    load_dotenv = None
else:  # pragma: no cover - executed in normal runtime
    load_dotenv()

_REST_PATH = "/rest/v1"


def _require(value: str, name: str) -> str:
    if not value:
        raise RuntimeError(
            f"Environment variable {name} is required for Supabase connectivity."
        )
    return value


_BASE_URL = _require(BASE_URL.rstrip("/"), "SUPABASE_PROJECT_REF")
_SERVICE_KEY = _require(SERVICE_KEY, "SUPABASE_SERVICE_ROLE_KEY")


def _base_headers(api_key: str) -> dict[str, str]:
    return {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Profile": SCHEMA_PROFILE,
        "Accept-Profile": SCHEMA_PROFILE,
    }


def _path(unqualified: str) -> str:
    # Never schema-qualify when using the public surface.
    # Callers should pass unqualified paths like "/v_cases" or "/rpc/insert_case".
    if not unqualified.startswith("/"):
        return f"/{unqualified}"
    return unqualified


COMMON = _base_headers(_SERVICE_KEY)


class _SupabaseClient(httpx.Client):
    def request(self, method: str, url: str, *args, **kwargs):  # type: ignore[override]
        if isinstance(url, str):
            url = _path(url)
        headers = kwargs.get("headers")
        if headers is None:
            kwargs["headers"] = COMMON
        else:
            merged = {**COMMON, **headers}
            kwargs["headers"] = merged
        return super().request(method, url, *args, **kwargs)


def get_supabase_url() -> str:
    """Return the configured Supabase base URL."""

    return _BASE_URL


def get_service_key() -> str:
    """Return the configured Supabase service role key."""

    return _SERVICE_KEY


def postgrest(timeout: Optional[float] = 10.0) -> httpx.Client:
    """Return a configured :class:`httpx.Client` for the Supabase PostgREST API."""

    base_url = f"{_BASE_URL}{_REST_PATH}"
    return _SupabaseClient(base_url=base_url, headers=COMMON, timeout=timeout)


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    import json

    try:
        with postgrest() as client:
            endpoint = "/v_cases" if SCHEMA_PROFILE == "public" else "/cases"
            response = client.get(
                endpoint,
                params={
                    "select": "case_id,index_no,court,county,status,created_at",
                    "status": "eq.new",
                    "order": "created_at.asc",
                    "limit": 3,
                },
            )
            response.raise_for_status()
            print(json.dumps(response.json(), indent=2))
    except Exception as exc:  # noqa: BLE001 - simple demonstration
        print("Supabase example request failed:", exc)
        print(
            "Ensure Supabase environment variables are configured before running this module."
        )
