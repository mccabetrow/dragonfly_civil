from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_URL_PROD: str | None = None
    SUPABASE_SERVICE_ROLE_KEY_PROD: str | None = None
    SUPABASE_DB_URL: str | None = None
    SUPABASE_DB_PASSWORD: str | None = None
    SUPABASE_DB_PASSWORD_PROD: str | None = None
    SUPABASE_DB_URL_PROD: str | None = None
    SUPABASE_DB_URL_DIRECT_PROD: str | None = None
    OPENAI_API_KEY: str | None = None
    SUPABASE_MODE: str = "demo"
    ENVIRONMENT: str = "dev"
    LOG_LEVEL: str = "INFO"
    N8N_API_KEY: str | None = None

    SESSION_PATH: str = str(Path("state") / "session.json")
    ENCRYPT_SESSIONS: bool = True
    SESSION_KMS_KEY: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )

    def _clean(self, value: str) -> str:
        return value.strip().strip('"').strip("'") if isinstance(value, str) else value

    def model_post_init(self, __context: dict[str, object]) -> None:
        for name, value in list(self.__dict__.items()):
            if isinstance(value, str):
                setattr(self, name, self._clean(value))

    @property
    def supabase_url(self) -> str:
        return self.SUPABASE_URL

    @property
    def supabase_service_role_key(self) -> str:
        return self.SUPABASE_SERVICE_ROLE_KEY

    @property
    def supabase_mode(self) -> Literal["demo", "prod"]:
        normalized = (self.SUPABASE_MODE or "demo").strip().lower()
        if normalized in {"prod", "production"}:
            return "prod"
        return "demo"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def ensure_parent_dir(path_str: str) -> None:
    path = Path(path_str).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)


def is_demo_env() -> bool:
    value = os.getenv("DEMO_ENV", "local")
    return value.lower() in {"local", "demo"}
