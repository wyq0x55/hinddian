from pathlib import Path

import pytest

from hinddian import draft_store, note_format as nf, notes, paths


def test_project_traversal_stays_in_vault(vault, tmp_path):
    assert nf.safe_project("../outside") == "outside"
    with pytest.raises(nf.UnsafePath):
        nf.write_note_file(vault, "../outside", "must never be written")
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(nf.UnsafePath):
        nf.write_note_file(vault, "escape/note", "also unsafe")
    assert list(outside.iterdir()) == []


def test_push_draft_keeps_provenance_and_safe_paths(vault, tmp_path):
    result = draft_store.save_payload({"project": "../../outside", "title": "试验内容",
                                       "body": "全文",
                                       "session_id": "original/id"})
    path = Path(result["path"])
    assert path.is_relative_to(tmp_path / "drafts")
    assert not path.is_relative_to(vault)
    text = path.read_text()
    assert "session_id: original/id" in text and "全文" in text
    second = draft_store.save_payload({"project": result["project"], "session_id": "original_id"})
    assert second["path"] != result["path"]


def test_list_and_get_drafts(vault, tmp_path):
    payload = {"project": "P", "title": "有来源的草稿", "body": "## LESSONS\n- 内容",
               "session_id": "abc-123", "jev_source": "jev:local", "origin": "test"}
    result = draft_store.save_payload(payload)
    path = Path(result["path"])
    assert draft_store.save_payload(payload)["path"] == str(path)
    row, = notes.list_drafts()
    assert row["session_id"] == payload["session_id"] and row["jev_source"] == "jev:local"
    assert row["title"] == payload["title"] and row["status"] == "pending"
    assert notes.get_draft("P/session-abc-123")["body"].endswith("- 内容")
    assert notes.get_draft("../session-abc-123.md") is None
    assert notes.get_draft("P/../session-abc-123.md") is None
    outside = tmp_path / "secret.md"
    outside.write_text("do not read")
    (path.parent / "linked.md").symlink_to(outside)
    assert notes.get_draft("P/linked.md") is None
    assert len(notes.list_drafts()) == 1
    archived = tmp_path / "processed/P" / path.name
    archived.parent.mkdir(parents=True)
    path.rename(archived)
    assert notes.list_drafts() == []
    assert notes.get_draft(row["id"])["status"] == "processed"
    assert notes.list_drafts(project="P", status="all")[0]["id"] == row["id"]


def test_drafts_must_be_outside_vault(vault, monkeypatch):
    monkeypatch.setenv("HINDDIAN_DRAFTS_DIR", str(vault / "drafts"))
    with pytest.raises(ValueError, match="outside the vault"):
        draft_store.save_payload({"project": "P", "session_id": "s"})
    assert not (vault / "drafts").exists()


def test_path_defaults_and_file_env_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config = tmp_path / "config.json"
    monkeypatch.setenv("HINDDIAN_CONFIG", str(config))
    for name in ("HINDDIAN_VAULT", "VAULT_ROOT", "HC_VAULT", "HINDDIAN_DRAFTS_DIR", "HB_DRAFTS", "HB_BASE",
                 "HINDDIAN_PROCESSED_DIR", "HB_PROCESSED", "HINDDIAN_STATE_DIR", "XDG_STATE_HOME"):
        monkeypatch.delenv(name, raising=False)
    assert paths.vault_dir() == tmp_path / "Obsidian/vault"
    assert paths.drafts_dir() == tmp_path / "Obsidian/drafts"
    assert paths.processed_dir() == tmp_path / "Obsidian/processed"
    assert paths.state_dir() == tmp_path / ".local/state/hinddian"
    config.write_text('{"vault":"~/notes","drafts_dir":"~/pending","processed_dir":"~/done","state_dir":"~/state"}')
    assert paths.vault_dir() == tmp_path / "notes"
    assert paths.drafts_dir() == tmp_path / "pending"
    assert paths.processed_dir() == tmp_path / "done"
    assert paths.state_dir() == tmp_path / "state"
    monkeypatch.setenv("VAULT_ROOT", "~/mounted")
    monkeypatch.setenv("HC_VAULT", "~/legacy")
    monkeypatch.setenv("HB_DRAFTS", "~/legacy-drafts")
    monkeypatch.setenv("HB_PROCESSED", "~/legacy-processed")
    monkeypatch.setenv("HB_BASE", "~/legacy-state")
    assert paths.vault_dir() == tmp_path / "mounted"
    assert paths.drafts_dir() == tmp_path / "legacy-drafts"
    assert paths.processed_dir() == tmp_path / "legacy-processed"
    assert paths.state_dir() == tmp_path / "legacy-state"
    monkeypatch.setenv("HINDDIAN_VAULT", "~/primary")
    assert paths.vault_dir() == tmp_path / "primary"
