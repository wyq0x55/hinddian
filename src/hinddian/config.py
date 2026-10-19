from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Single source of server configuration (env / .env). Read via get_settings()."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Optional on the API host (vault lives on the vault host). Empty / missing = vault ops go over SSH.
    vault_root: Path | None = None
    inbox_dir: Path = Path("/opt/session-distill/inbox")
    processed_dir: Path = Path("/opt/session-distill/processed")
    quarantine_dir: Path = Path("/opt/session-distill/quarantine")
    failed_dir: Path = Path("/opt/session-distill/failed")

    hindsight_base_url: str = "http://127.0.0.1:8888"
    hindsight_api_key: str | None = None
    hindsight_bank: str = "hinddian"
    # Does the distill worker retain filtered sessions into Hindsight? (branch c)
    hindsight_retain_enabled: bool = False

    # Vault host (vault + classify stage), reached via a root SSH alias.
    classify_ssh_host: str = "vault-host"
    classify_enabled: bool = True
    ssh_control_path: str = "/run/hinddian-ssh-%C"

    hinddian_host: str = "127.0.0.1"
    hinddian_port: int = 8787
    # Agent channel (MCP + /api/memory/*): hooks and agents hold this token.
    hinddian_mcp_token: str | None = None
    # Human channel (dashboard + approvals). Must differ from the MCP token, or an agent could
    # approve its own suggestions.
    auth_token: str | None = None
    # Local development only: run without tokens.
    hinddian_allow_no_auth: bool = False

    status_db: Path = Path("./data/hinddian.db")

    agent_tips_relpath: str = "00-系统/agent使用技巧.md"
    projects_dirname: str = "项目"

    @field_validator("vault_root", mode="before")
    @classmethod
    def _empty_vault_to_none(cls, v):  # noqa: ANN001
        if v is None or v == "" or v == "None":
            return None
        return v

    @property
    def vault_local(self) -> bool:
        return bool(self.vault_root and self.vault_root.is_dir())


@lru_cache
def get_settings() -> Settings:
    return Settings()
