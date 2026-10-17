from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    vault_root: Path = Path("/srv/obsidian/vault")
    inbox_dir: Path = Path("/opt/session-distill/inbox")
    processed_dir: Path = Path("/opt/session-distill/processed")
    quarantine_dir: Path = Path("/opt/session-distill/quarantine")
    failed_dir: Path = Path("/opt/session-distill/failed")

    hindsight_base_url: str = "http://127.0.0.1:8888"
    hindsight_mcp_url: str = "http://127.0.0.1:8888/mcp/wanwan/"
    hindsight_api_key: str | None = None

    hinddian_host: str = "127.0.0.1"
    hinddian_port: int = 8787
    auth_token: str | None = None

    status_db: Path = Path("./data/hinddian.db")
    use_demo_data: bool = True

    agent_tips_relpath: str = "00-系统/agent使用技巧.md"
    projects_dirname: str = "项目"


@lru_cache
def get_settings() -> Settings:
    return Settings()
