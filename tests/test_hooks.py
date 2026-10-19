"""Host-hook runtime, tested from the generated plugin copy (what users actually run)."""
from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/hinddian/scripts"


@pytest.fixture
def hooks(tmp_path, monkeypatch):
    monkeypatch.setenv("HINDDIAN_HOOK_DIR", str(tmp_path / "hooks"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("HINDDIAN_MEMORY_URL", "https://memory.example/hinddian")
    monkeypatch.setenv("HINDDIAN_CONFIG", str(tmp_path / "cfg" / "hinddian" / "config.json"))
    for k in ("HINDDIAN_MCP_TOKEN", "HINDDIAN_CA_FILE", "HINDDIAN_ALLOW_INSECURE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    names = ("hookcfg", "session_buf", "finalize", "extract", "jev", "mcp_bridge", "setup", "turn_end")
    for m in names:
        sys.modules.pop(m, None)
    mods = {m: importlib.import_module(m) for m in ("hookcfg", "session_buf", "finalize", "mcp_bridge")}
    yield mods
    for m in names:
        sys.modules.pop(m, None)


def test_transport_rules(hooks, monkeypatch):
    t = hooks["hookcfg"].transport_problem
    assert t("https://h/x") is None
    assert t("http://127.0.0.1:8787") is None
    assert "refusing" in t("http://203.0.113.10/hinddian")
    assert "not configured" in t("")
    monkeypatch.setenv("HINDDIAN_ALLOW_INSECURE", "1")
    assert t("http://10.0.0.1/x") is None


def test_clip_keeps_head_and_tail(hooks):
    clip = hooks["session_buf"].clip
    text = "ASK" + "x" * 50000 + "CONCLUSION"
    out = clip(text)
    assert out.startswith("ASK") and out.endswith("CONCLUSION") and len(out) < 12100


def test_jev_down_keeps_buffer_then_gives_up(hooks, monkeypatch):
    sb, fin = hooks["session_buf"], hooks["finalize"]
    monkeypatch.setattr(fin, "projects_list", lambda: [])

    def down(*a, **k):
        raise RuntimeError("jev down")

    monkeypatch.setattr(fin, "_classify", down)
    buf = sb.append_turn(session_id="s1", turn_text="用户: hi\n助手: done")
    r = fin.finalize_buffer(buf, reason="idle")
    assert r["deferred"] is True
    b = sb.load("s1")
    assert not b["finalized"] and b["next_try_at"] > time.time()
    assert not sb.due(b)
    assert fin.finalize_idle_and_others() == []  # backoff respected
    for _ in range(sb.MAX_ATTEMPTS):
        fin.finalize_buffer(sb.load("s1"), reason="idle")
    b = sb.load("s1")
    assert b["finalized"] and b["outcome"].startswith("gave_up")


def test_successful_finalize_pushes_once(hooks, monkeypatch):
    sb, fin = hooks["session_buf"], hooks["finalize"]
    monkeypatch.setattr(fin, "projects_list", lambda: ["P"])
    monkeypatch.setattr(fin, "_classify", lambda c, p: {"ok": True, "source": "jev:local", "confidence": 0.9,
                                                         "value": {"keep": True, "title": "T", "type": "lesson", "project": "P"}})
    sent = []
    monkeypatch.setattr(fin, "req", lambda m, path, body=None, timeout=0: sent.append((path, body)) or {"ok": True})
    sb.append_turn(session_id="old", turn_text="用户: a\n助手: b")
    res = fin.finalize_idle_and_others(current_sid="new")
    assert [r.get("pushed") for r in res] == [{"ok": True}]
    assert sent[0][0] == "/api/memory/push_draft" and sent[0][1]["session_id"] == "old"
    assert fin.finalize_idle_and_others(current_sid="new") == []


def test_claim_is_exclusive(hooks):
    sb = hooks["session_buf"]
    with sb.claim("s") as a:
        with sb.claim("s") as b:
            assert a is True and b is False


def test_prune_deletes_old_finalized(hooks):
    sb = hooks["session_buf"]
    sb.append_turn(session_id="s", turn_text="x")
    sb.mark_finalized("s")
    assert sb.prune(now=time.time() + sb.RETAIN_SEC + 1) == 1
    assert sb.load("s") is None


def test_legacy_buffers_are_migrated(hooks, tmp_path, monkeypatch):
    monkeypatch.delenv("HINDDIAN_HOOK_DIR")
    legacy = tmp_path / "cfg/magpie/hinddian-hooks/sessions"
    legacy.mkdir(parents=True)
    (legacy / "old.json").write_text('{"session_id": "old", "turns": [{"text": "t"}]}', encoding="utf-8")
    assert [b["session_id"] for b in hooks["session_buf"].list_open()] == ["old"]
    assert (tmp_path / "cfg/hinddian/hooks/sessions/old.json").is_file()


def test_turn_end_refuses_without_server(hooks, monkeypatch, capsys):
    monkeypatch.setenv("HINDDIAN_MEMORY_URL", "http://203.0.113.5/hinddian")
    sys.modules.pop("turn_end", None)
    te = importlib.import_module("turn_end")
    te.main()
    assert '"buffered": false' in capsys.readouterr().out
    assert hooks["session_buf"].list_open() == []


def test_config_file_and_precedence(hooks, monkeypatch):
    cfg = hooks["hookcfg"]
    monkeypatch.delenv("HINDDIAN_MEMORY_URL")
    assert cfg.memory_url() == ""
    p = cfg.save_config({"url": "https://from-file/hinddian/", "token": "file-tok"})
    assert p.stat().st_mode & 0o777 == 0o600
    assert cfg.memory_url() == "https://from-file/hinddian" and cfg.token() == "file-tok"
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HINDDIAN_MCP_TOKEN", "opt-tok")
    assert cfg.token() == "opt-tok"
    monkeypatch.setenv("HINDDIAN_MCP_TOKEN", "env-tok")
    assert cfg.token() == "env-tok"


def test_setup_writes_config_and_strips_mcp_suffix(hooks, monkeypatch, capsys):
    import setup

    monkeypatch.setattr(setup, "check", lambda: True)
    assert setup.main(["--url", "https://h:8444/hinddian/mcp", "--token", "t"]) == 0
    assert hooks["hookcfg"].load_config() == {"url": "https://h:8444/hinddian", "token": "t"}


def test_bridge_answers_when_unconfigured(hooks, monkeypatch):
    import json

    monkeypatch.delenv("HINDDIAN_MEMORY_URL")
    b = hooks["mcp_bridge"]
    init = json.loads(b.handle('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'))
    assert "setup.py" in init["result"]["instructions"]
    assert b.handle('{"jsonrpc":"2.0","method":"notifications/initialized"}') is None
    assert json.loads(b.handle('{"jsonrpc":"2.0","id":2,"method":"tools/list"}'))["result"]["tools"] == []
    call = json.loads(b.handle('{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"recall"}}'))
    assert call["result"]["isError"] and "setup.py" in call["result"]["content"][0]["text"]


def test_bridge_forwards_and_degrades(hooks, monkeypatch):
    import json

    b = hooks["mcp_bridge"]
    sent = []
    monkeypatch.setattr(b, "_forward", lambda raw: sent.append(raw) or b'{"jsonrpc":"2.0","id":1,"result":{"tools":[1]}}')
    assert json.loads(b.handle('{"jsonrpc":"2.0","id":1,"method":"tools/list"}'))["result"]["tools"] == [1]
    assert json.loads(sent[0])["method"] == "tools/list"

    def down(raw):
        raise OSError("refused")

    monkeypatch.setattr(b, "_forward", down)
    assert json.loads(b.handle('{"jsonrpc":"2.0","id":2,"method":"tools/list"}'))["result"]["tools"] == []
