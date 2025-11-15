from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    ENVIRONMENT: str = "dev"
    LOG_LEVEL: str = "INFO"

    SESSION_PATH: str = str(Path("state") / "session.json")
    ENCRYPT_SESSIONS: bool = True
    SESSION_KMS_KEY: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def ensure_parent_dir(path_str: str) -> None:
    path = Path(path_str).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
