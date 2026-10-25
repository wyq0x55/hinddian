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

    hindsight_base_url: str = "http://127.0.0.1:8888"
    hindsight_api_key: str | None = None
    hindsight_bank: str = "hinddian"

    # Vault host (vault + batch engine), reached via a root SSH alias.
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

    # ---- MCP OAuth (MCP auth spec 2025-06-18). Off unless public URL + GitHub app are set.
    # Public base of the agent channel as clients see it, e.g. https://124.70.90.224:8444/hinddian
    hinddian_public_url: str | None = None
    # GitHub OAuth App used as upstream identity. Its callback URL must be
    # {hinddian_public_url}/oauth/github/callback.
    hinddian_gh_client_id: str | None = None
    hinddian_gh_client_secret: str | None = None
    # Comma-separated GitHub logins allowed to authorize MCP clients.
    hinddian_gh_allowed_users: str = ""
    # Proxy for GitHub egress (e.g. socks5://127.0.0.1:1088 on hosts that cannot reach github.com).
    hinddian_gh_proxy: str | None = None
    hinddian_oauth_db: Path = Path("data/oauth.sqlite3")
    hinddian_oauth_access_ttl: int = 3600
    hinddian_oauth_refresh_ttl: int = 60 * 60 * 24 * 30


    @field_validator("vault_root", mode="before")
    @classmethod
    def _empty_vault_to_none(cls, v):  # noqa: ANN001
        if v is None or v == "" or v == "None":
            return None
        return v

    @property
    def oauth_enabled(self) -> bool:
        return bool(
            self.hinddian_public_url
            and self.hinddian_gh_client_id
            and self.hinddian_gh_client_secret
            and self.allowed_gh_users
        )

    @property
    def allowed_gh_users(self) -> set[str]:
        return {u.strip().lower() for u in self.hinddian_gh_allowed_users.split(",") if u.strip()}

    @property
    def vault_local(self) -> bool:
        return bool(self.vault_root and self.vault_root.is_dir())


@lru_cache
def get_settings() -> Settings:
    return Settings()
