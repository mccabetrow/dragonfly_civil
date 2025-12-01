from __future__ import annotations

from functools import lru_cache
from typing import Tuple

from src.settings import get_settings as get_app_settings


class WorkerSettings:
    """Thin wrapper around shared application settings for worker processes."""

    def __init__(self) -> None:
        base = get_app_settings()
        self.supabase_url = base.supabase_url
        self.supabase_service_role_key = base.supabase_service_role_key

    def supabase_credentials(self) -> Tuple[str, str]:
        return self.supabase_url, self.supabase_service_role_key


@lru_cache(maxsize=1)
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
