"""Central configuration for ETL runtime settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    web_civil_user: str = Field("", alias="WEB_CIVIL_USER")
    web_civil_pass: str = Field("", alias="WEB_CIVIL_PASS")
    authenticated_url: str = Field(
        "https://iapps.courts.state.ny.us/webcivilLocal/LCIndex", alias="WEB_CIVIL_AUTH_URL"
    )
    user_selector: str = Field("#userid1", alias="WEB_CIVIL_USER_SELECTOR")
    pass_selector: str = Field("#password1", alias="WEB_CIVIL_PASS_SELECTOR")
    submit_selector: str = Field("#loginButton", alias="WEB_CIVIL_SUBMIT_SELECTOR")
    post_login_selector: str = Field("#searchForm", alias="WEB_CIVIL_POST_LOGIN_SELECTOR")

    headless: bool = Field(True, alias="HEADLESS")
    stealth: bool = Field(True, alias="STEALTH")
    proxy_url: Optional[str] = Field(None, alias="PROXY_URL")
    timezone: str = Field("America/New_York", alias="TZ")
    locale: str = Field("en-US", alias="LOCALE")
    viewport: str = Field("1280x800", alias="VIEWPORT")
    user_agent_override: Optional[str] = Field(None, alias="USER_AGENT_OVERRIDE")

    encrypt_sessions: bool = Field(True, alias="ENCRYPT_SESSIONS")
    session_kms_key: Optional[str] = Field(None, alias="SESSION_KMS_KEY")

    discord_webhook_url: Optional[str] = Field(None, alias="DISCORD_WEBHOOK_URL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached ETL settings instance."""

    return Settings()
