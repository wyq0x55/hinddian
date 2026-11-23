"""Credentials and listener settings for the optional HTTP service."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    hinddian_host: str = "127.0.0.1"
    hinddian_port: int = 8787
    hinddian_mcp_token: str | None = None
    auth_token: str | None = None
    hinddian_allow_no_auth: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
