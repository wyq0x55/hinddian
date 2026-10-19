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
    names = ("hookcfg", "session_buf", "finalize", "extract", "jev", "mcp_bridge", "setup", "turn_end",
             "prompt_recall", "session_start")
    for m in names:
        sys.modules.pop(m, None)
    mods = {m: importlib.import_module(m) for m in ("hookcfg", "session_buf", "finalize", "mcp_bridge", "prompt_recall", "session_start")}
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
    monkeypatch.delenv("HINDDIAN_MEMORY_URL")  # the fixture's env URL would override the written config
    assert setup.main(["--url", "https://h:8444/hinddian/mcp", "--token", "t"]) == 0
    assert hooks["hookcfg"].load_config() == {"url": "https://h:8444/hinddian", "token": "t"}


def test_setup_fails_when_env_overrides_written_url(hooks, monkeypatch, capsys):
    import setup

    monkeypatch.setattr(setup, "check", lambda: True)
    assert setup.main(["--url", "https://h:8444/hinddian", "--token", "t"]) == 1
    assert "HINDDIAN_MEMORY_URL" in capsys.readouterr().out


def test_bridge_answers_when_unconfigured(hooks, monkeypatch):
    import json

    monkeypatch.delenv("HINDDIAN_MEMORY_URL")
    b = hooks["mcp_bridge"]
    init = json.loads(b.handle('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'))
    assert "setup.py" in init["result"]["instructions"]
    assert b.handle('{"jsonrpc":"2.0","method":"notifications/initialized"}') is None
    assert [t["name"] for t in json.loads(b.handle('{"jsonrpc":"2.0","id":2,"method":"tools/list"}'))["result"]["tools"]] == ["doctor"]
    call = json.loads(b.handle('{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"recall"}}'))
    assert call["result"]["isError"] and "setup.py" in call["result"]["content"][0]["text"]


def test_bridge_forwards_and_degrades(hooks, monkeypatch):
    import json

    b = hooks["mcp_bridge"]
    sent = []
    monkeypatch.setattr(b, "_forward", lambda raw: sent.append(raw) or b'{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"recall"}]}}')
    names = [t["name"] for t in json.loads(b.handle('{"jsonrpc":"2.0","id":1,"method":"tools/list"}'))["result"]["tools"]]
    assert names == ["recall", "doctor"]
    assert json.loads(sent[0])["method"] == "tools/list"

    def down(raw):
        raise OSError("refused")

    monkeypatch.setattr(b, "_forward", down)
    assert [t["name"] for t in json.loads(b.handle('{"jsonrpc":"2.0","id":2,"method":"tools/list"}'))["result"]["tools"]] == ["doctor"]


def test_bridge_doctor_runs_locally(hooks, monkeypatch):
    import json

    b = hooks["mcp_bridge"]
    monkeypatch.setattr(b, "_forward", lambda raw: (_ for _ in ()).throw(AssertionError("doctor must not be forwarded")))
    out = json.loads(b.handle('{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"doctor","arguments":{}}}'))
    assert "hinddian" in out["result"]["content"][0]["text"]


# ------------------------------------------------------------------ auto recall
def test_recall_skips_cheap_prompts(hooks):
    w = hooks["prompt_recall"].worth_recalling
    for p in ("好的", "继续", "ok", "Thanks!", "/hinddian:doctor", "<task-notification>x</task-notification>", "短"):
        assert not w(p), p
    assert w("部署到 API 主机之前要检查什么")


def test_recall_query_drops_pastes(hooks):
    pr = hooks["prompt_recall"]
    q = pr.clean_query("部署又失败了，看下\n```\nTraceback (most recent call last):\n  File x\n```\n是不是门禁的问题")
    assert q == "部署又失败了，看下 是不是门禁的问题"
    assert pr.clean_query("x" * 400) == ""
    assert not pr.worth_recalling(pr.clean_query("```\nonly a log\n```"))


def test_recall_filters_and_dedupes(hooks):
    pr = hooks["prompt_recall"]
    results = [
        {"document_id": "a", "text": "---\nid: a\n---\n# A\n\n## 做法\n先跑门禁", "metadata": {"title": "A"}, "scores": {"reranker": 0.9}},
        {"document_id": "b", "text": "无关", "metadata": {"title": "B"}, "scores": {"reranker": 0.1}},
        {"id": "c", "title": "C", "practice": "p", "score": 0.6},
        {"id": "d", "title": "D", "practice": "p", "score": 0.1},
    ]
    items = pr.normalize(results)
    assert [i["id"] for i in items] == ["a", "c"]
    assert items[0]["snippet"] == "先跑门禁"
    assert [i["id"] for i in pr.pick_new("s1", items)] == ["a", "c"]
    assert pr.pick_new("s1", items) == []          # already injected this session
    assert [i["id"] for i in pr.pick_new("s2", items)] == ["a", "c"]


def test_recall_scopes_to_session_project_and_dedupes(hooks, monkeypatch, capsys):
    import io
    import json

    pr, sb = hooks["prompt_recall"], hooks["session_buf"]
    sb.side_file("s9", "project").write_text("my-app", encoding="utf-8")
    sent = []

    def req(method, path, body=None, **kw):
        sent.append(body)
        return {"results": [{"document_id": "a", "text": "x", "metadata": {"title": "A"}}] * 3}

    monkeypatch.setattr(pr.hookcfg, "req", req)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s9", "prompt": "上次部署门禁怎么定的"})))
    pr.main()
    assert sent[0]["project"] == "my-app"
    assert capsys.readouterr().out.count("[a]") == 1


def test_prune_handles_side_files(hooks):
    sb = hooks["session_buf"]
    seen = sb.side_file("old", "recalled.json")
    seen.write_text('["a"]', encoding="utf-8")
    sb.side_file("new", "project").write_text("p", encoding="utf-8")
    import os

    os.utime(seen, (1, 1))
    assert sb.prune() == 1
    assert not seen.exists() and sb.side_file("new", "project").exists()


def test_recall_emits_structured_context(hooks, monkeypatch, capsys):
    import io
    import json

    pr = hooks["prompt_recall"]
    monkeypatch.setattr(pr.hookcfg, "req", lambda *a, **k: {"results": [{"document_id": "a", "text": "t", "metadata": {"title": "A"}}]})
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "上次部署门禁怎么定的"})))
    pr.main()
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]
    assert ctx["hookEventName"] == "UserPromptSubmit" and "<hinddian_recall>" in ctx["additionalContext"]


def test_recall_off_switch_and_failure_are_silent(hooks, monkeypatch, capsys):
    import io

    pr = hooks["prompt_recall"]
    monkeypatch.setenv("HINDDIAN_AUTO_RECALL", "0")
    monkeypatch.setattr("sys.stdin", io.StringIO('{"prompt": "上次部署门禁怎么定的"}'))
    pr.main()
    monkeypatch.setenv("HINDDIAN_AUTO_RECALL", "1")

    def boom(*a, **k):
        raise TimeoutError

    monkeypatch.setattr(pr.hookcfg, "req", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"prompt": "上次部署门禁怎么定的"}'))
    pr.main()
    assert capsys.readouterr().out == ""


# ------------------------------------------------------------------ session start
def test_routing_block_is_cache_stable(hooks):
    ss = hooks["session_start"]
    a = ss.routing_block(sorted(["b", "a"]), "a")
    assert a == ss.routing_block(["a", "b"], "a")
    assert not any(ch.isdigit() for ch in a.replace("hinddian", ""))  # no counts / dates in the prefix
    assert ss.match_project("/home/me/work/my-app-api", ["my-app", "my-app-api"]) == "my-app-api"
