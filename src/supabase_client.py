from __future__ import annotations

import base64
import json

from supabase import Client, create_client

from .settings import get_settings


def _verify_service_role(jwt_token: str) -> None:
    try:
        segments = jwt_token.split(".")
        if len(segments) < 2:
            raise ValueError("missing JWT payload")
        payload_segment = segments[1]
        padding = "=" * (-len(payload_segment) % 4)
        decoded = base64.urlsafe_b64decode(payload_segment + padding)
        claims = json.loads(decoded)
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Invalid SUPABASE_SERVICE_ROLE_KEY JWT") from exc

    role = claims.get("role")
    if role != "service_role":
        raise RuntimeError(f"Service role key has unexpected role: {role}")


def create_supabase_client() -> Client:
    settings = get_settings()
    _verify_service_role(settings.supabase_service_role_key)
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
