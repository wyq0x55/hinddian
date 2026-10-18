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
    monkeypatch.syspath_prepend(str(SCRIPTS))
    for m in ("hookcfg", "session_buf", "finalize", "extract", "jev"):
        sys.modules.pop(m, None)
    mods = {m: importlib.import_module(m) for m in ("hookcfg", "session_buf", "finalize")}
    yield mods
    for m in ("hookcfg", "session_buf", "finalize", "extract", "jev"):
        sys.modules.pop(m, None)


def test_transport_rules(hooks, monkeypatch):
    t = hooks["hookcfg"].transport_problem
    assert t("https://h/x") is None
    assert t("http://127.0.0.1:8787") is None
    assert "refusing" in t("http://124.70.90.224/hinddian")
    assert t("") == "HINDDIAN_MEMORY_URL not set"
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
