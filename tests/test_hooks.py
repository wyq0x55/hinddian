"""Host-hook runtime, tested from the generated plugin copy (what users actually run)."""
from __future__ import annotations

import importlib
import json
import shlex
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/hinddian/scripts"


@pytest.fixture
def hooks(tmp_path, monkeypatch):
    monkeypatch.setenv("HINDDIAN_HOOK_DIR", str(tmp_path / "hooks"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("HINDDIAN_MEMORY_URL", "https://memory.example/hinddian")
    monkeypatch.setenv("HINDDIAN_CONFIG", str(tmp_path / "cfg" / "hinddian" / "config.json"))
    monkeypatch.setenv("HINDDIAN_REPORT_JEV", "0")  # tests opt in explicitly
    for k in ("HINDDIAN_MCP_TOKEN", "HINDDIAN_CA_FILE", "HINDDIAN_ALLOW_INSECURE"):
        monkeypatch.delenv(k, raising=False)
        monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_" + k, raising=False)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    names = ("hookcfg", "session_buf", "finalize", "extract", "jev", "mcp_bridge", "setup", "turn_end", "session_start")
    for m in names:
        sys.modules.pop(m, None)
    mods = {m: importlib.import_module(m) for m in ("hookcfg", "session_buf", "finalize", "mcp_bridge", "session_start")}
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


def test_server_down_keeps_buffer_then_gives_up(hooks, monkeypatch):
    sb, fin = hooks["session_buf"], hooks["finalize"]

    def down(*a, **k):
        raise OSError("server down")

    monkeypatch.setattr(fin, "req", down)
    buf = sb.append_turn(session_id="s1", turn_text="用户: hi\n助手: done")
    r = fin.finalize_buffer(buf, reason="idle")
    assert r["deferred"] is True and "server_unreachable" in r["error"]
    b = sb.load("s1")
    assert not b["finalized"] and b["next_try_at"] > time.time()
    assert not sb.due(b)
    assert fin.finalize_idle_and_others() == []  # backoff respected
    for _ in range(sb.MAX_ATTEMPTS):
        fin.finalize_buffer(sb.load("s1"), reason="idle")
    b = sb.load("s1")
    assert b["finalized"] and b["outcome"].startswith("gave_up")


def test_server_retry_flag_defers(hooks, monkeypatch):
    sb, fin = hooks["session_buf"], hooks["finalize"]
    monkeypatch.setattr(fin, "req", lambda *a, **k: {"ok": False, "retry": True, "outcome": "jev_unavailable",
                                                     "error": "jev_unavailable: x", "source": "none"})
    r = fin.finalize_buffer(sb.append_turn(session_id="s2", turn_text="用户: a\n助手: b"), reason="idle")
    assert r["deferred"] is True and not sb.load("s2")["finalized"]


def test_finalize_posts_buffer_to_server_once(hooks, monkeypatch, tmp_path):
    sb, fin = hooks["session_buf"], hooks["finalize"]
    sent = []
    monkeypatch.setattr(fin, "req", lambda m, path, body=None, timeout=0: sent.append((path, body)) or
                        {"ok": True, "outcome": "pushed", "pushed": True, "source": "jev:local", "keep": True})
    repo = tmp_path / "work" / "my-repo"
    (repo / ".git").mkdir(parents=True)
    sb.append_turn(session_id="old", turn_text="用户: a\n助手: b", cwd=str(repo / "src"))
    res = fin.finalize_idle_and_others(current_sid="new")
    assert [r.get("pushed") for r in res] == [True]
    assert [p for p, _ in sent] == ["/api/memory/finalize"]  # no client-side Jev, no separate report
    body = sent[0][1]
    assert body["session_id"] == "old" and body["finalize_reason"] == "session-start"
    assert body["cwd"] == "src" and body["repo"] == "my-repo" and str(tmp_path) not in json.dumps(body)
    assert body["turns"] == [{"text": "用户: a\n助手: b"}] and body["client_id"]
    assert fin.finalize_idle_and_others(current_sid="new") == []
    assert not hasattr(fin, "jev")


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


def test_private_blocks_never_buffered(hooks):
    sb = hooks["session_buf"]
    buf = sb.append_turn(session_id="p1", turn_text="部署 <private>token=abc 密码</private> 完成 <PRIVATE>尾巴")
    assert buf["turns"][0]["text"] == "部署 [private] 完成 [private]"


def test_prune_handles_side_files(hooks):
    sb = hooks["session_buf"]
    seen = sb.side_file("old", "recalled.json")
    seen.write_text('["a"]', encoding="utf-8")
    sb.side_file("new", "project").write_text("p", encoding="utf-8")
    import os

    os.utime(seen, (1, 1))
    assert sb.prune() == 1
    assert not seen.exists() and sb.side_file("new", "project").exists()


def test_unconfigured_session_start_is_silent(hooks, monkeypatch, capsys):
    monkeypatch.setenv("HINDDIAN_MEMORY_URL", "http://203.0.113.5/hinddian")
    hooks["session_start"].main()
    assert capsys.readouterr() == ("", "")
    assert hooks["session_buf"].list_open() == []


@pytest.mark.parametrize("host", ["claude", "codex", "magpie"])
def test_host_buffers_turns_and_finalizes_silently(host, hooks, vault, monkeypatch, tmp_path):
    from hinddian import jev, memory_mcp, notes, session_finalize
    from hinddian.api import app
    from hinddian.config import Settings

    requests = []
    allow_finalize = Event()
    settings = Settings(_env_file=None, vault_root=vault, hinddian_mcp_token=None,
                        hinddian_public_url=None, hinddian_allow_no_auth=True, hindsight_api_key=None)
    monkeypatch.setattr(memory_mcp, "get_settings", lambda: settings)
    monkeypatch.setenv("HINDDIAN_JEV_LOG", str(tmp_path / "jev.jsonl"))
    gate = jev.GateResult(True, {"keep": True, "type": "lesson", "title": "降低并发后重试成功",
                                "lesson": ["降低并发后复测通过"], "open_question": ["并发上限受连接池限制吗？"]},
                          0.9, "jev:local", {})
    monkeypatch.setattr(session_finalize.jev, "classify_turn", lambda *args: gate)
    assert notes.upsert_note({"action": "add", "type": "lesson", "project": "my-app", "title": "旧笔记",
                              "scene": "排障", "practice": "先看日志", "reason": "确认超时原因"})["ok"]
    old_note = next(vault.rglob("*.md"))
    original_note = old_note.read_bytes()

    class MemoryServer(BaseHTTPRequestHandler):
        def forward(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"]))) if self.command == "POST" else None
            requests.append((self.command, self.path, body))
            if self.path == "/api/memory/finalize":
                allow_finalize.wait(timeout=10)
            response = client.request(self.command, self.path, json=body)
            self.send_response(response.status_code)
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = do_POST = forward

    with TestClient(app) as client, ThreadingHTTPServer(("127.0.0.1", 0), MemoryServer) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            monkeypatch.setenv("HINDDIAN_MEMORY_URL", f"http://127.0.0.1:{server.server_port}")
            monkeypatch.setenv("no_proxy", "127.0.0.1")
            monkeypatch.delenv("HINDDIAN_HOOK_SYNC", raising=False)
            monkeypatch.setenv("HINDDIAN_AUTO_RECALL", "1")
            monkeypatch.setenv("HINDDIAN_SESSION_IDLE_SEC", "1800")
            plugin = SCRIPTS.parent
            if host == "magpie":
                skill = plugin.parents[1] / "adapters/magpie/skills/hinddian-hooks"
                library = tmp_path / "library.json"
                library.write_text('{"hooks":[{"name":"hinddian-session-start","command":"old"}]}')
                monkeypatch.setenv("HINDDIAN_MCP_URL", f"http://127.0.0.1:{server.server_port}/mcp")
                monkeypatch.setenv("MAGPIE_LIBRARY", str(library))
                monkeypatch.setenv("HINDDIAN_MAGPIE_HOOK_DIR", str(tmp_path / "magpie-hooks"))
                monkeypatch.setenv("HINDDIAN_PYTHON", sys.executable)
                subprocess.run([sys.executable, str(skill / "install.py")], capture_output=True, check=True, timeout=5)
                commands = {hook["event"]: hook["command"] for hook in json.loads(library.read_text())["hooks"]}
                start, stop = "session-start", "turn-end"
            else:
                manifest = plugin / ("hooks/hooks.json" if host == "claude" else ".codex-plugin/hooks.json")
                config = json.loads(manifest.read_text())["hooks"]
                commands = {event: Template(entries[0]["hooks"][0]["command"]).substitute(
                    CLAUDE_PLUGIN_ROOT=plugin, PLUGIN_ROOT=plugin) for event, entries in config.items()}
                start, stop = "SessionStart", "Stop"
            assert set(commands) == {start, stop}

            def run(event, sid, **data):
                payload = {"session_id": sid, "cwd": "/work/my-app", **data}
                if host != "magpie":
                    payload["hook_event_name"] = event
                return subprocess.run(shlex.split(commands[event]), input=json.dumps(payload), text=True,
                                      capture_output=True, check=True, timeout=5).stdout

            buffer = hooks["session_buf"]
            buffer.append_turn(session_id="old", cwd="/work/my-app", turn_text="ASSISTANT:\nPrevious closing")
            buffer.side_file("old", "recalled.json").write_text('["stored-note"]', encoding="utf-8")
            assert run(start, "new", source="startup") == ""
            allow_finalize.set()
            deadline = time.monotonic() + 5
            while not buffer.load("old")["finalized"] and time.monotonic() < deadline:
                time.sleep(0.02)
            assert buffer.load("old")["outcome"] == "pushed"
            draft = (tmp_path / "drafts/my-app/session-old.md").read_text(encoding="utf-8")
            assert "# 降低并发后重试成功" in draft and "## OPEN QUESTIONS\n- 并发上限受连接池限制吗？" in draft
            assert old_note.read_bytes() == original_note
            assert json.loads(run(stop, "new", prompt="排查超时", last_assistant_message="调低并发后复测通过"))["buffered"]
            assert "调低并发后复测通过" in buffer.load("new")["turns"][0]["text"]
            assert [(method, path) for method, path, _ in requests] == [("POST", "/api/memory/finalize")]
            assert requests[0][2]["turns"] == [{"text": "ASSISTANT:\nPrevious closing"}]
        finally:
            allow_finalize.set()
            server.shutdown()
            worker.join()


def test_injected_recent_context_is_not_rebuffered(hooks):
    import extract

    text = "USER:\nask\n<hinddian_recent>\nold memory\n</hinddian_recent>\nASSISTANT:\nanswer"
    out = extract.extract_turn_text(text)
    assert "old memory" not in out and "answer" in out and "ask" in out
