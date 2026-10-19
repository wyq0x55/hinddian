from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Point hinddian.notes at an empty temp vault / queue / drafts dir."""
    from hinddian import notes

    v = tmp_path / "vault"
    v.mkdir()
    monkeypatch.setattr(notes, "VAULT", v)
    monkeypatch.setattr(notes, "CORRECTIONS", tmp_path / "corrections")
    monkeypatch.setattr(notes, "DRAFTS", tmp_path / "drafts")
    monkeypatch.setattr(notes, "OWNER", "")
    monkeypatch.setenv("HINDDIAN_VAULT_LOCK", str(tmp_path / "vault.lock"))
    return v
