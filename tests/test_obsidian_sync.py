from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from hinddian import index_sync, memory_mcp

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sync(tmp_path, monkeypatch):
    secrets = tmp_path / "secrets.env"
    secrets.write_text("HINDSIGHT_API_TENANT_API_KEY=test-only\n")
    monkeypatch.setenv("HS_SECRETS", str(secrets))
    monkeypatch.setenv("HS_STATE", str(tmp_path / "state" / "sync.json"))
    spec = importlib.util.spec_from_file_location("obsidian_sync", ROOT / "deploy/api-host/obsidian_hindsight_sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.sys, "argv", ["sync"])
    return module


def test_sync_removes_deleted_and_all_non_active_before_retaining(sync, monkeypatch):
    sync.STATE.parent.mkdir()
    sync.STATE.write_text(json.dumps({k: "old" for k in ("deleted", "obsolete", "superseded", "archived", "active")}))
    exported = [{"id": name, "status": name if name != "active" else "active", "sha": "new"}
                for name in ("obsolete", "superseded", "archived", "active")]
    seen = []
    monkeypatch.setattr(sync.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps(exported), stderr=""))
    monkeypatch.setattr(sync, "forget", lambda nid: seen.append(("forget", nid)))
    monkeypatch.setattr(sync, "retain", lambda n: seen.append(("retain", n["id"])))
    sync.main()
    assert seen == [("forget", nid) for nid in ("deleted", "obsolete", "superseded", "archived")] + [("retain", "active")]
    assert json.loads(sync.STATE.read_text()) == {"active": "new"}
    assert json.loads(sync.STATUS.read_text())["pending"] == 0


def test_sync_initial_run_creates_state_directory_and_retries_failure(sync, monkeypatch):
    exported = [{"id": "a", "status": "active", "sha": "new"}]
    monkeypatch.setattr(sync.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps(exported), stderr=""))
    monkeypatch.setattr(sync, "retain", lambda n: (_ for _ in ()).throw(OSError("offline")))
    sync.main()
    assert json.loads(sync.STATE.read_text()) == {}
    assert json.loads(sync.STATUS.read_text())["pending"] == 1
    seen = []
    monkeypatch.setattr(sync, "retain", lambda n: seen.append(n["id"]))
    sync.main()
    assert seen == ["a"] and json.loads(sync.STATE.read_text()) == {"a": "new"}


def test_timer_and_api_service_enable_two_minute_sync():
    timer = (ROOT / "deploy/api-host/hinddian-hindsight-sync.timer").read_text()
    assert "OnCalendar=*:0/2\n" in timer and "AccuracySec=1s\n" in timer
    assert "RandomizedDelaySec" not in timer
    assert "Environment=HINDDIAN_SYNC_KICK=1\n" in (ROOT / "deploy/api-host/hinddian.service").read_text()


def test_kick_runs_in_background_and_uses_fixed_nonblocking_unit(monkeypatch, caplog):
    calls = []
    monkeypatch.delenv("HINDDIAN_SYNC_KICK", raising=False)
    monkeypatch.setattr(index_sync.threading, "Thread", lambda **kw: calls.append(kw) or SimpleNamespace(start=lambda: None))
    index_sync.kick()
    assert calls == []
    monkeypatch.setenv("HINDDIAN_SYNC_KICK", "1")
    index_sync.kick()
    assert len(calls) == 1 and calls[0]["daemon"] is True and calls[0]["target"] is index_sync._start
    commands = []
    monkeypatch.setattr(index_sync.subprocess, "run", lambda cmd, **kw: commands.append((cmd, kw)))
    calls[0]["target"]()
    assert commands[0][0] == ["systemctl", "--no-block", "start", "hinddian-hindsight-sync.service"]
    assert commands[0][1]["timeout"] == 2 and commands[0][1]["check"] is True
    monkeypatch.setattr(index_sync.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    index_sync._start()
    assert "timer will retry" in caplog.text


@pytest.mark.parametrize("local", [True, False])
def test_vault_kicks_only_after_successful_mutations(monkeypatch, local):
    result = {"ok": True, "action": "add"}
    calls = []
    monkeypatch.setattr(memory_mcp, "get_settings", lambda: SimpleNamespace(vault_local=local))
    monkeypatch.setattr(memory_mcp, "_notes_mod", lambda: SimpleNamespace(
        upsert_note=lambda p: result, suggest_correction=lambda p: result))
    monkeypatch.setattr(memory_mcp, "_ssh_cli", lambda *a, **k: result)
    monkeypatch.setattr(index_sync, "kick", lambda: calls.append("kick"))
    for op in ("upsert_note", "suggest_correction"):
        assert memory_mcp.vault(op, payload={}) is result
    assert calls == ["kick", "kick"]
    result.update(ok=False)
    memory_mcp.vault("upsert_note", payload={})
    result.update(ok=True, action="noop")
    memory_mcp.vault("upsert_note", payload={})
    assert calls == ["kick", "kick"]


def test_vault_cli_suggest_and_upsert_share_direct_write_contract(vault, monkeypatch):
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("HC_OWNER", "")
    payload = {"type": "decision", "project": "P", "title": "只走 TLS",
               "scene": "部署", "practice": "TLS", "reason": "安全"}
    cli = str(ROOT / "deploy/vault-host/hinddian-memory-cli")
    def call(op, data):
        out = subprocess.run([str(ROOT / ".venv/bin/python"), cli, op], input=json.dumps(data),
                             text=True, capture_output=True, check=True)
        return json.loads(out.stdout)
    added = call("suggest_correction", payload)
    assert added["ok"] and added["action"] == "add"
    assert call("upsert_note", {"action": "obsolete", "id": added["id"]})["action"] == "obsolete"
    assert call("suggest_correction", {"action": "hard_delete", "id": added["id"]})["error"] == "hard_delete_forbidden"
