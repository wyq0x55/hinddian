"""Exercise the distributed hook entry points and their local draft store."""
from __future__ import annotations

import datetime as dt
import errno
import importlib
import json
import os
import shlex
import subprocess
import sys
from io import StringIO
from pathlib import Path
from string import Template

import pytest

from hinddian import note_format as nf

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/hinddian"
SCRIPTS = PLUGIN / "scripts"
REPLY = "导语不采集\n**原行为**　旧流程\n### 改进：先备份\n**取舍：** 推断，放弃覆盖，因为无法回滚。\n## **验证**\n通过\n"


@pytest.fixture
def hooks(vault, tmp_path, monkeypatch):
    monkeypatch.setenv("HINDDIAN_HOOK_DIR", str(tmp_path / "hooks"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    for key in ("HINDDIAN_MEMORY_URL", "CLAUDE_PLUGIN_OPTION_HINDDIAN_MEMORY_URL", "HINDDIAN_CAPTURE_MODE",
                "HINDDIAN_NO_CLOSING", "HINDDIAN_SUMMARY_CHARS", "HINDDIAN_MAGPIE_HOOK_DIR", "MAGPIE_TURN_TEXT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    names = ("capture", "extract", "hook_runtime", "draft_store", "note_format", "paths", "setup", "turn_end")
    for name in names:
        sys.modules.pop(name, None)
    yield importlib.import_module("capture")
    for name in names:
        sys.modules.pop(name, None)


def commands(manifest):
    config = json.loads((PLUGIN / manifest).read_text())["hooks"]
    return {event: Template(entries[0]["hooks"][0]["command"]).substitute(
        CLAUDE_PLUGIN_ROOT=PLUGIN, PLUGIN_ROOT=PLUGIN) for event, entries in config.items()}


def run(command, *, timeout=3, **payload):
    result = subprocess.run(shlex.split(command), input=json.dumps(payload), capture_output=True, text=True, timeout=timeout)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def make_repo(repo):
    repo.mkdir()
    git(repo, "init", "-q", "-b", "test-branch")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "baseline")
    return git(repo, "rev-parse", "--short", "HEAD")


@pytest.mark.parametrize("manifest", ["hooks/hooks.json", ".codex-plugin/hooks.json"])
@pytest.mark.parametrize("failure", ["lock", "directory", "config", "mode", "url", "number", "fifo", "slow-config"])
def test_plugin_entry_failures_are_silent(manifest, failure, hooks, monkeypatch, tmp_path):
    if failure == "directory":
        (tmp_path / "drafts").write_text("not a directory")
    if failure == "config":
        hooks.paths.config_path().write_text("{")
    if failure == "fifo":
        os.mkfifo(hooks.paths.config_path())
    if failure == "slow-config":
        config = hooks.paths.config_path()
        config.write_text("{}")
        (tmp_path / "sitecustomize.py").write_text(
            "import os, time\n"
            "open_file = os.open\n"
            "def slow_open(path, *args, **kwargs):\n"
            "    if os.fspath(path) == os.environ['HINDDIAN_CONFIG']:\n"
            "        time.sleep(30)\n"
            "    return open_file(path, *args, **kwargs)\n"
            "os.open = slow_open\n"
        )
        monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    if failure == "mode":
        monkeypatch.setenv("HINDDIAN_CAPTURE_MODE", "invalid")
    if failure == "url":
        monkeypatch.setenv("HINDDIAN_MEMORY_URL", "https://[invalid")
    if failure == "number":
        monkeypatch.setenv("HINDDIAN_SUMMARY_CHARS", "invalid")
    events = commands(manifest)
    lock = nf.vault_lock(timeout=0) if failure == "lock" else nf.contextlib.nullcontext()
    with lock:
        run(events["Stop"], session_id="test", last_assistant_message=REPLY)
        if failure not in {"directory", "lock"}:
            run(events["SessionStart"])
    logs = list(tmp_path.rglob("capture.log"))
    assert logs and all("旧流程" not in log.read_text() for log in logs)
    assert not list(tmp_path.rglob("drafts/**/*.md"))
    if failure == "slow-config":
        assert "TimeoutError" in logs[0].read_text()


def test_enospc_is_silent_and_log_is_bounded(hooks, monkeypatch, capsys, tmp_path):
    import hook_runtime
    from turn_end import main

    def full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "exception detail")

    monkeypatch.setattr(hooks.draft_store.nf, "write_atomic", full)
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps({"session_id": "s", "last_assistant_message": REPLY})))
    main()
    assert capsys.readouterr() == ("", "")
    log = tmp_path / "hooks/capture.log"
    assert "OSError" in log.read_text() and "exception detail" not in log.read_text()
    monkeypatch.setattr(hooks.draft_store.nf, "write_atomic", nf.write_atomic)
    monkeypatch.setattr(hook_runtime, "LOG_LIMIT", 300)
    for _ in range(10):
        hook_runtime.record("test")
        assert log.stat().st_size <= 300


@pytest.mark.parametrize("manifest", ["hooks/hooks.json", ".codex-plugin/hooks.json"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory"])
def test_stop_bypasses_unsafe_capture_log(manifest, kind, hooks, vault, tmp_path):
    protected = vault / "00-系统/手写.md"
    protected.parent.mkdir()
    protected.write_text("保留手写正文\n")
    log = tmp_path / "hooks/capture.log"
    log.parent.mkdir()
    if kind == "symlink":
        log.symlink_to(protected)
    elif kind == "hardlink":
        log.hardlink_to(protected)
    elif kind == "fifo":
        os.mkfifo(log)
    else:
        log.mkdir()

    run(commands(manifest)["Stop"], timeout=1.5, session_id="test", last_assistant_message="短答")

    assert protected.read_text() == "保留手写正文\n"
    fallback = tmp_path / "cfg/hinddian/hooks/capture.log"
    assert json.loads(fallback.read_text())["event"] == "skip"
    assert not (tmp_path / "drafts").exists()


@pytest.mark.parametrize("manifest", ["hooks/hooks.json", ".codex-plugin/hooks.json"])
@pytest.mark.parametrize("kind", ["dangling-symlink", "fifo"])
def test_stop_bypasses_unsafe_capture_log_lock(manifest, kind, hooks, vault, tmp_path):
    protected = vault / "00-系统/未存在.md"
    protected.parent.mkdir()
    lock = tmp_path / "hooks/hook-log.lock"
    lock.parent.mkdir()
    if kind == "dangling-symlink":
        lock.symlink_to(protected)
    else:
        os.mkfifo(lock)

    run(commands(manifest)["Stop"], timeout=1.5, session_id="test", last_assistant_message="短答")

    assert not protected.exists()
    assert not (lock.parent / "capture.log").exists()
    fallback = tmp_path / "cfg/hinddian/hooks/capture.log"
    assert json.loads(fallback.read_text())["event"] == "skip"


def test_closing_headings_ignore_fenced_examples_and_unrelated_headings(hooks):
    result = hooks.extract.closing("```md\n**改进** fence\n```\n" + REPLY + "## 其他\n不能采集\n")
    assert result == "## 原行为\n旧流程\n\n## 改进\n先备份\n\n## 取舍\n推断，放弃覆盖，因为无法回滚。\n\n## 验证\n通过"
    assert hooks.extract.closing(REPLY.replace("**取舍：**", "**其他**")) == ""
    assert hooks.extract.closing("**原行为** x\n**改进** y\n**取舍** z\n**验证**") == ""
    assert hooks.extract.closing(REPLY.replace("**原行为**", "原行为：").replace("### 改进：", "### 改进 ###\n"))


@pytest.mark.parametrize("manifest", ["hooks/hooks.json", ".codex-plugin/hooks.json"])
@pytest.mark.parametrize("shape", ["transcript", "text_and_transcript", "object_and_transcript",
                                   "text_and_messages", "object_with_id", "crlf_and_messages",
                                   "crlf_and_transcript"])
def test_stop_keeps_distinct_message_ids(manifest, shape, hooks, tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    stop = commands(manifest)["Stop"]
    for message_id in ("one", "one", "two"):
        msg = {"type": "message", "role": "assistant", "id": message_id, "content": REPLY}
        transcript_msg = {**msg, "id": "other"} if shape == "object_with_id" else msg
        if manifest == "hooks/hooks.json":
            event = {"type": "assistant", "message": transcript_msg}
        else:
            event = {"type": "response_item", "payload": {**transcript_msg, "phase": "final_answer"}}
        transcript.write_text(json.dumps(event) + "\n")
        payload = {"session_id": "s", "project": "P"}
        if shape in ("text_and_messages", "crlf_and_messages"):
            payload["messages"] = [msg]
        else:
            payload["transcript_path"] = str(transcript)
        if shape != "transcript":
            payload["last_assistant_message"] = {
                "object_and_transcript": {"content": REPLY},
                "object_with_id": {"content": REPLY, "id": message_id},
                "crlf_and_messages": REPLY.replace("\n", "\r\n"),
                "crlf_and_transcript": REPLY.replace("\n", "\r\n"),
            }.get(shape, REPLY)
        run(stop, **payload)
    draft, = (tmp_path / "drafts/P").glob("*.md")
    assert draft.read_text().count("<!-- hinddian:turn ") == 2


@pytest.mark.parametrize("heading", ["**其他**\n", "**其他**　"])
def test_stop_excludes_bold_appendix(hooks, tmp_path, heading):
    stop = commands(".codex-plugin/hooks.json")["Stop"]
    run(stop, session_id="s", project="P", last_assistant_message=REPLY + heading + "无关附录\n附录第二行\n")
    draft, = (tmp_path / "drafts/P").glob("*.md")
    assert draft.read_text().endswith("## 验证\n通过\n")


@pytest.mark.parametrize("manifest", ["hooks/hooks.json", ".codex-plugin/hooks.json"])
@pytest.mark.parametrize("verification", [
    "通过\n开关由环境控制\n**推断** 仍需验证失败回退\n这行补充依据",
    "**实测** 构建通过",
    "**【实测】** 构建通过",
    "**实测结果** 构建通过",
    "**[推断结果]**\n根据运行日志判断",
    "**猜测（原会话）** 可能由缓存引起",
])
def test_stop_keeps_bold_evidence_in_closing(manifest, verification, hooks, tmp_path):
    stop = commands(manifest)["Stop"]
    reply = REPLY.replace("通过", verification) + "**其他**　无关附录\n附录第二行\n"
    run(stop, session_id="s", project="P", last_assistant_message=reply)
    draft, = (tmp_path / "drafts/P").glob("*.md")
    assert draft.read_text().endswith(f"## 验证\n{verification}\n")


def test_duplicate_stop_is_detected_across_pending_and_archived_projects(hooks, tmp_path):
    stop = commands(".codex-plugin/hooks.json")["Stop"]
    payload = {"session_id": "s", "turn_id": "same", "last_assistant_message": REPLY}
    run(stop, project="First", **payload)
    run(stop, project="Second", **payload)
    draft, = (tmp_path / "drafts").glob("*/*.md")
    assert draft.parent.name == "First"
    archived = tmp_path / "processed/First" / draft.name
    archived.parent.mkdir(parents=True)
    draft.rename(archived)
    run(stop, project="Third", **payload)
    assert not list((tmp_path / "drafts").glob("*/*.md"))


def test_skip_and_summary_only_use_visible_final(hooks, monkeypatch, tmp_path):
    payload = {"session_id": "s", "prompt": REPLY, "last_assistant_message": "简单回复内容"}
    assert hooks.capture(payload) is None
    assert "no_closing" in (tmp_path / "hooks/capture.log").read_text()
    assert not (tmp_path / "drafts").exists()
    monkeypatch.setenv("HINDDIAN_NO_CLOSING", "summary")
    monkeypatch.setenv("HINDDIAN_SUMMARY_CHARS", "4")
    result = hooks.capture(payload)
    fm, _, body = nf.parse_frontmatter(Path(result["path"]).read_text())
    assert fm["kind"] == "summary" and body.endswith("简单回复\n")
    assert all(fm[key] == "" for key in ("repo", "branch", "commit", "cwd"))


@pytest.mark.parametrize("ids", [("origin/a", "origin?a"), ("a" * 150 + "/", "a" * 150 + "?")])
def test_similar_session_ids_keep_separate_drafts(hooks, ids):
    outputs = [hooks.capture({"session_id": sid, "last_assistant_message": REPLY.replace("旧流程", sid)}) for sid in ids]
    assert outputs[0]["path"] != outputs[1]["path"]
    for output, sid in zip(outputs, ids):
        fm, _, body = nf.parse_frontmatter(Path(output["path"]).read_text())
        assert fm["session_id"] == sid and f"## 原行为\n{sid}\n" in body


@pytest.mark.parametrize("host", ["claude", "codex", "magpie"])
def test_host_captures_final_turn_silently_and_keeps_sources(host, hooks, vault, monkeypatch, tmp_path):
    repo = tmp_path / "my-app"
    commit = make_repo(repo)
    cwd = repo / "src"
    cwd.mkdir()
    (cwd / "untracked").touch()
    monkeypatch.setenv("HINDDIAN_CLIENT_ID", "test-host")
    if host == "magpie":
        skill = ROOT / "adapters/magpie/skills/hinddian-hooks"
        library = tmp_path / "library.json"
        library.write_text(json.dumps({"hooks": [{"name": "hinddian-session-start", "command": "old"}],
                                       "mcp": [{"name": "hinddian-memory"}, {"name": "other"}]}))
        monkeypatch.setenv("MAGPIE_LIBRARY", str(library))
        monkeypatch.setenv("HINDDIAN_MAGPIE_HOOK_DIR", str(tmp_path / "magpie-hooks"))
        monkeypatch.setenv("HINDDIAN_PYTHON", sys.executable)
        subprocess.run([sys.executable, str(skill / "install.py")], capture_output=True, check=True, timeout=5)
        installed = json.loads(library.read_text())
        assert installed["mcp"] == [{"name": "other"}]
        events = {hook["event"]: hook["command"] for hook in installed["hooks"]}
        assert all(len(command) < 1000 for command in events.values())
        start, stop = "session-start", "turn-end"
    else:
        events = commands("hooks/hooks.json" if host == "claude" else ".codex-plugin/hooks.json")
        start, stop = "SessionStart", "Stop"
    run(events[start], session_id="new")
    payload = {"session_id": "origin/a", "cwd": str(cwd), "turn_id": "first", "prompt": "不采集用户输入",
               "last_assistant_message": REPLY}
    run(events[stop], **payload)
    run(events[stop], **payload)
    run(events[stop], **{**payload, "turn_id": "second", "last_assistant_message": REPLY.replace("先备份", "再恢复")})
    draft, = (tmp_path / "drafts/my-app").glob("*.md")
    fm, _, body = nf.parse_frontmatter(draft.read_text())
    assert {key: fm[key] for key in ("session_id", "host", "cwd", "repo", "branch", "commit", "project")} == {
        "session_id": "origin/a", "host": "test-host", "cwd": "src", "repo": "my-app",
        "branch": "test-branch", "commit": commit + "-dirty", "project": "my-app",
    }
    assert dt.datetime.fromisoformat(fm["time"]).utcoffset() is not None
    assert len(fm["turn_ids"]) == 2 and body.count("## 取舍") == 2 and "再恢复" in body
    assert "不采集用户输入" not in body and "导语不采集" not in body and not list(vault.iterdir())
    archive = tmp_path / "processed/my-app" / draft.name
    archive.parent.mkdir(parents=True)
    draft.rename(archive)
    run(events[stop], **payload)
    assert not draft.exists()


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_transcript_capture_uses_only_the_latest_final_answer(host, hooks, tmp_path):
    def event(role, *content, **fields):
        message = {"role": role, "content": list(content), **fields}
        if host == "claude":
            return {"type": role, "message": message}
        return {"type": "response_item", "payload": {"type": "message", **message}}

    transcript = tmp_path / "transcript.jsonl"
    records = [
        event("user", "old question"),
        event("assistant", "old answer"),
        event("user", "<hinddian_recent>old memory</hinddian_recent>"),
        event("assistant", "tool chatter", phase="commentary", stop_reason="tool_use"),
        event("user", {"type": "tool_result", "content": "tool result"}),
        event("assistant", {"type": "thinking", "text": "hidden"}, {"type": "text", "text": "final answer"}),
    ]
    transcript.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    assert hooks.extract.final_reply({"transcript_path": str(transcript)}) == "final answer"
    assert hooks.extract.final_reply({"transcript_path": str(transcript), "last_assistant_message": "direct"}) == "direct"


def test_project_inference_and_setup_without_model(hooks, monkeypatch, capsys):
    pick = hooks._project
    assert pick("", "my-app-api", "", ["my-app", "my-app-api"]) == "my-app-api"
    assert pick("", "new-repo", "", ["hinddian"]) == "new-repo"
    assert pick("", "", "loose", ["hinddian"]) == "通用-未定"
    assert pick("P", "", "", []) == "P"
    import setup

    assert setup.main(["--check"]) == 0
    assert "skip" in capsys.readouterr().out and not hooks.paths.config_path().exists()


def test_local_capture_to_processed_obsidian_note(hooks, vault, monkeypatch, tmp_path):
    repo = tmp_path / "my-app"
    commit = make_repo(repo)
    git(vault, "init", "-q")
    git(vault, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "baseline")
    sid = "origin/session-123"
    run(commands(".codex-plugin/hooks.json")["Stop"], session_id=sid, cwd=str(repo), last_assistant_message=REPLY)
    draft, = (tmp_path / "drafts/my-app").glob("*.md")
    original = draft.read_bytes()
    monkeypatch.syspath_prepend(str(ROOT / "classify"))
    sys.modules.pop("hinddian_batch", None)
    batch = importlib.import_module("hinddian_batch")

    def chat(prompt):
        assert "先备份" in prompt and "放弃覆盖，因为无法回滚" in prompt
        return json.dumps({"ops": [{"op": "create", "title": "部署前先备份", "type": "lesson",
                                    "scene": "部署", "practice": "先备份", "reason": "推断，放弃覆盖，因为无法回滚。",
                                    "sources": ["S01"]}]})

    try:
        monkeypatch.setattr(batch, "chat", chat)
        batch.cmd_run()
        note = vault / "项目/my-app/经验/部署前先备份.md"
        meta, _, body = nf.parse_frontmatter(note.read_text())
        assert meta["sources"] == [f"{sid}@{commit}"] and "放弃覆盖" in body
        assert not draft.exists() and (tmp_path / "processed/my-app" / draft.name).read_bytes() == original
        events = [json.loads(line) for line in batch.LOG.read_text().splitlines()]
        assert len([ev for ev in events if ev["event"] == "model_call"]) == 1
        assert "部署前先备份.md" in next(ev["stat"] for ev in events if ev["event"] == "diff")
    finally:
        sys.modules.pop("hinddian_batch", None)
