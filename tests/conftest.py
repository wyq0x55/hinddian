from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Isolate all note pipeline paths from the user's files."""
    v = tmp_path / "vault"
    v.mkdir()
    monkeypatch.setenv("HINDDIAN_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("HINDDIAN_VAULT", str(v))
    monkeypatch.setenv("HINDDIAN_DRAFTS_DIR", str(tmp_path / "drafts"))
    monkeypatch.setenv("HINDDIAN_PROCESSED_DIR", str(tmp_path / "processed"))
    monkeypatch.setenv("HINDDIAN_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HINDDIAN_VAULT_LOCK", str(tmp_path / "vault.lock"))
    return v
