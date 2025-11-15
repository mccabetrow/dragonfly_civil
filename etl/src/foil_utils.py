"""Helpers for recording FOIL responses in Supabase."""

from __future__ import annotations

import os
from datetime import date
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Json

try:  # Prefer python-dotenv when available.
    from dotenv import load_dotenv  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    load_dotenv = None


_DB_URL_CACHE: str | None = None


def _load_env() -> None:
    if load_dotenv is not None:
        load_dotenv()


def _project_ref_from_url(url: str | None) -> str:
    if not url:
        return ""
    url = url.strip()
    if not url:
        return ""
    prefix = "https://"
    if url.startswith(prefix):
        url = url[len(prefix) :]
    return url.split(".")[0]


def _resolve_db_url() -> str:
    global _DB_URL_CACHE
    if _DB_URL_CACHE:
        return _DB_URL_CACHE

    _load_env()

    explicit = os.environ.get("SUPABASE_DB_URL")
    if explicit:
        _DB_URL_CACHE = explicit
        return explicit

    password = os.environ.get("SUPABASE_DB_PASSWORD")
    project_ref = os.environ.get("SUPABASE_PROJECT_REF")

    if not project_ref:
        project_ref = _project_ref_from_url(os.environ.get("SUPABASE_URL"))

    if not password or not project_ref:
        raise RuntimeError(
            "Missing Supabase database configuration. Set SUPABASE_DB_URL or "
            "SUPABASE_DB_PASSWORD and SUPABASE_PROJECT_REF/SUPABASE_URL."
        )

    db_url = (
        "postgresql://postgres:{password}@"
        "aws-1-us-east-2.pooler.supabase.com:5432/postgres"
        "?user=postgres.{project_ref}&sslmode=require"
    ).format(password=password, project_ref=project_ref)

    _DB_URL_CACHE = db_url
    return db_url


def _coerce_payload(payload: Mapping[str, Any] | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, Mapping):
        return dict(payload)
    raise TypeError("FOIL payload must be a mapping")


def record_foil_response(
    case_id: UUID,
    source_agency: str | None = None,
    payload: Mapping[str, Any] | dict[str, Any] | None = None,
    *,
    agency: str | None = None,
    request_id: str | None = None,
    response_date: date | None = None,
    received_date: date | None = None,
) -> None:
    """Insert a FOIL response row for the given case."""

    if payload is None:
        raise ValueError("payload is required")

    agency_value = agency or source_agency
    if agency_value is None:
        raise ValueError("agency is required")

    agency_value = agency_value.strip()
    if not agency_value:
        raise ValueError("agency is required and cannot be empty")

    received = received_date or response_date

    db_url = _resolve_db_url()
    payload_dict = _coerce_payload(payload)

    if request_id and "request_id" not in payload_dict:
        payload_dict = {**payload_dict, "request_id": request_id}

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into judgments.foil_responses (
                    case_id,
                    received_date,
                    agency,
                    payload
                )
                values (%s, %s, %s, %s)
                """,
                (
                    str(case_id),
                    received,
                    agency_value,
                    Json(payload_dict),
                ),
            )
