from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from string import Template
from urllib.parse import unquote

import pytest

from hinddian import chapters, recording

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/hinddian"
FIXTURES = ROOT / "tests/fixtures/notes"
SAMPLES = ROOT / "docs/samples"


@pytest.fixture
def spool(tmp_path, monkeypatch):
    monkeypatch.setenv("HINDDIAN_NOTES_SPOOL", str(tmp_path / "sources"))
    monkeypatch.setenv("HINDDIAN_HOOK_DIR", str(tmp_path / "legacy"))
    monkeypatch.setenv("HINDDIAN_CONFIG", str(tmp_path / "missing-config.json"))
    monkeypatch.delenv("HINDDIAN_MEMORY_URL", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_HINDDIAN_MEMORY_URL", raising=False)
    monkeypatch.delenv("MAGPIE_TURN_TEXT", raising=False)
    return tmp_path / "sources"


def run_stop(session_id, *, host="codex", project="hinddian", **payload):
    manifest = PLUGIN / (".codex-plugin/hooks.json" if host == "codex" else "hooks/hooks.json")
    hook = json.loads(manifest.read_text())["hooks"]["Stop"][0]["hooks"][0]["command"]
    command = Template(hook).substitute(PLUGIN_ROOT=PLUGIN, CLAUDE_PLUGIN_ROOT=PLUGIN)
    result = subprocess.run(shlex.split(command), input=json.dumps({
        "session_id": session_id, "cwd": f"/work/{project}", **payload,
    }), text=True, capture_output=True, check=True, timeout=5)
    assert (result.stdout, result.stderr) == ("", "")


def sources_for(note):
    link = re.search(r"\[脱敏会话记录\]\(([^)]+)\)", note.read_text())[1]
    return (note.parent / unquote(link)).resolve()


def assert_citations(note):
    source = json.loads(sources_for(note).read_text())
    lines = [line for line in note.read_text().splitlines() if line.startswith("- ")]
    for line in lines:
        citations = re.findall(r"`([^`]+) / ([^`]+)@(\d+)`", line)
        assert citations
        for session_id, position, offset in citations:
            assert session_id == source["session_id"]
            assert 0 <= int(offset) < len(source["records"][position]["text"])


def model_fragments(prompt):
    return json.loads(prompt.removeprefix(chapters.PROMPT))["fragments"]


def sample_model(prompt):
    fragments = model_fragments(prompt)
    entries = []
    for kind, status, evidence, text in (
        ("goal", "observed", ("原会话第 14 行",), "让三个宿主停止自动注入和召回历史，并保留数据与旧草稿定稿能力。"),
        ("decision", "observed", ("原会话第 64 行",), "优先移除启动时的注入与逐条提示词召回，保留录入与显式查询，降低迁移风险。"),
        ("attempt", "observed", ("No module named pytest",), "系统 Python 缺少 pytest。改用 uv 创建的临时虚拟环境安装测试依赖。"),
        ("attempt", "observed", ("第 146、162 行",), "两次修改测试的补丁因预期上下文不符被拒绝。"),
        ("attempt", "observed", ("FileNotFoundError",), "中段的独立冒烟运行没读到预期 Markdown 草稿，报 FileNotFoundError。"),
        ("attempt", "hypothesis", ("FileNotFoundError",), "缺少草稿曾使旧缓冲兼容性存疑。单次读文件失败无法确定根因。"),
        ("decision", "observed", ("第 246–258 行",), "改用宿主参数化测试与既有临时 vault fixture，通过本地 API 和固定 Jev 响应端到端验证，等待后台定稿后再读草稿。"),
        ("verification", "observed", ("原会话第 269 行", "原会话第 289 行"),
         "三种宿主均落了新回合，并为旧会话写出含 OPEN QUESTIONS 的临时草稿。由此排除了「移除注入会一律破坏旧缓冲定稿」的假设。启动输出为零，唯一 HTTP 请求是后台定稿，全套 200 项测试通过。"),
        ("question", "pending", ("原会话第 289 行",), "真实网关和线上宿主尚待验证。独立冒烟运行未读到草稿的确切根因也未查明。"),
        ("question", "pending", ("脱敏原始记录的保留期",), "确认脱敏记录保留期、是否跨机器同步，以及 Dashboard 是否仍依赖旧 Hindsight 索引。"),
        ("goal", "observed", ("把 README",), "将 README 的测试命令改为 python -m pytest。"),
        ("verification", "observed", ("已更新 README",), "已更新 README，git diff --check 返回 0。"),
    ):
        refs = [next((fragment["position"] for fragment in fragments if marker in fragment["text"]), None)
                for marker in evidence]
        if all(refs):
            entries.append({"kind": kind, "status": status, "text": text, "refs": refs})
    return {"entries": entries}


def replay_sample(spool, output, session_id, host, project):
    run_stop(session_id, host=host, project=project, transcript_path=str(FIXTURES / (session_id + ".jsonl")))
    session = spool / ("session-" + recording.digest(session_id))
    return chapters.organize(session, output, sample_model)


@pytest.mark.parametrize(("session_id", "host", "project"), [
    ("phase-one", "codex", "hinddian"),
    ("short-control", "claude", "short-control"),
])
def test_sample_chapters(spool, tmp_path, session_id, host, project):
    note = replay_sample(spool, tmp_path / "chapters", session_id, host, project)
    assert note
    assert_citations(note)
    source = json.loads(sources_for(note).read_text())
    sample_note = SAMPLES / note.relative_to(tmp_path)
    sample_source = json.loads(sources_for(sample_note).read_text())
    assert note.read_text() == sample_note.read_text()
    assert {key: source[key] for key in ("session_id", "records")} == sample_source
    text = note.read_text()
    if session_id == "phase-one":
        assert text.index("缺少 pytest") < text.index("FileNotFoundError")
        assert text.index("FileNotFoundError") < text.index("改用宿主参数化测试") < text.index("排除")
        assert "**推测**" in text
        assert "## OPEN QUESTIONS（未决问题）" in text and "**待验证** 真实网关" in text
    else:
        assert text.count("\n- ") == 2
        assert "输入中未整理出明确的未决问题" in text


def test_long_transcript_retries_without_repeating_entries(spool, tmp_path):
    long_text = "开头" + "\x01" * 8500 + "中段失败" + "证据" * 8500 + "原文结尾"
    transcript = tmp_path / "host.jsonl"
    rows = [
        {"type": "message", "role": "assistant", "phase": "commentary", "content": long_text},
        {"type": "message", "role": "system", "content": "REMOVE_SYSTEM"},
        {"type": "response_item", "payload": {"type": "reasoning", "content": "REMOVE_REASONING"}},
        {"type": "response_item", "payload": {"type": "function_call_output", "output": "REMOVE_TOOL"}},
        {"type": "message", "role": "assistant", "content": [
            {"type": "thinking", "text": "REMOVE_THINKING"},
            {"type": "text", "text": "换路依据 <private>REMOVE_PRIVATE <private>REMOVE_INNER</private>"
                                     " REMOVE_OUTER</private> <hinddian_recent>REMOVE_RECALL</hinddian_recent>"
                                     " <system-reminder>REMOVE_REMINDER</system-reminder>"
                                     " <tool_result>REMOVE_MARKUP_TOOL</tool_result>"
                                     " <environment_context>REMOVE_WRAPPER</environment_context>"
                                     " Bearer example_token_should_be_redacted"},
        ]},
        {"type": "message", "role": "user", "content": "待验证问题"},
    ]
    transcript.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    for _ in range(2):
        run_stop("long", transcript_path=str(transcript))
    session = next(spool.glob("session-*"))
    output = tmp_path / "chapters"
    calls = []

    def model(prompt):
        fragments = model_fragments(prompt)
        assert len(prompt.removeprefix(chapters.PROMPT)) <= chapters.CHUNK_CHARS
        calls.append(prompt)
        if len(calls) == 2:
            return {"entries": [{"kind": "attempt", "status": "observed", "text": "无效", "refs": ["invented@0"]}]}
        entries = []
        for kind, status, marker in (("attempt", "observed", "中段失败"), ("decision", "observed", "换路依据"),
                                     ("question", "pending", "待验证问题"), ("verification", "observed", "后来复测通过")):
            for fragment in fragments:
                if marker in fragment["text"]:
                    entry = {"kind": kind, "status": status, "text": marker, "refs": [fragment["position"]]}
                    entries.extend([entry, entry])
        return {"entries": entries}

    with pytest.raises(ValueError, match="reference does not resolve"):
        chapters.organize(session, output, model)
    assert not list(output.rglob("*.md"))
    snapshot = (session / "source.json").read_text()
    source = json.loads(snapshot)
    assert list(source["records"].values())[0]["text"] == long_text
    assert "REMOVE_" not in snapshot and "example_token_should_be_redacted" not in snapshot
    inputs = list(session.glob("inputs/*.json"))
    assert len(inputs) == 2 and (session / "source.json") not in inputs
    note = chapters.organize(session, output, model)
    assert note
    assert calls.count(calls[0]) == 1 and calls.count(calls[1]) == 2
    fragments = [fragment for prompt in dict.fromkeys(calls) for fragment in model_fragments(prompt)]
    first_position = next(iter(source["records"]))
    assert "".join(part["text"] for part in fragments if part["position"].startswith(first_position + "@")) == long_text
    assert "REMOVE_" not in "".join(calls) and "example_token_should_be_redacted" not in "".join(calls)
    contents = note.read_text()
    for marker in ("中段失败", "换路依据", "待验证问题", "OPEN QUESTIONS"):
        assert contents.count(marker) == 1
    assert_citations(note)
    before = len(calls)
    assert chapters.organize(session, output, model) == note
    assert len(calls) == before and note.read_text() == contents
    assert len(list(output.rglob("*.md"))) == 1

    with transcript.open("a") as handle:
        handle.write(json.dumps({"type": "message", "role": "assistant", "content": "后来复测通过"}) + "\n")
    run_stop("long", transcript_path=str(transcript))
    assert chapters.organize(session, output, model) == note
    assert note.read_text().count("后来复测通过") == 1
    updated = json.loads(sources_for(note).read_text())
    assert {position: updated["records"][position] for position in source["records"]} == source["records"]
    assert_citations(note)


def test_inline_stop_keeps_visible_turn_only(spool):
    payload = {
        "turn_id": "first",
        "turn_text": "SYSTEM:\nREMOVE_SYSTEM\n<private>\nUSER:\nREMOVE_PRIVATE\n</private>\n"
                     "USER:\n<developer>REMOVE_TAG</developer>需求\n"
                     "TOOL:\nREMOVE_TOOL\nASSISTANT:\n可见结语",
    }
    run_stop("magpie-like", host="claude", **payload)
    run_stop("magpie-like", host="claude", **payload)
    session = next(spool.glob("session-*"))
    _, _, records = recording.materialize(session)
    assert [item["text"] for item in records] == ["需求", "可见结语"]


def test_cli_replays_after_gateway_timeout(spool, tmp_path, monkeypatch, capsys):
    run_stop("short-control", transcript_path=str(FIXTURES / "short-control.jsonl"))
    output = tmp_path / "chapters"
    monkeypatch.setattr(sys, "argv", ["chapters", "--session", "short-control", "--output", str(output)])

    def timeout(prompt):
        raise TimeoutError

    monkeypatch.setattr(chapters.jev, "chat_json", timeout)
    assert chapters.main() == 1
    assert "TimeoutError" in capsys.readouterr().err
    assert not list(output.rglob("*.md"))

    monkeypatch.setattr(chapters.jev, "chat_json", sample_model)
    assert chapters.main() == 0
    path = Path(capsys.readouterr().out.strip())
    assert path.is_file()
    assert_citations(path)
    monkeypatch.setattr(chapters.jev, "chat_json", timeout)
    assert chapters.main() == 0
    assert list(output.rglob("*.md")) == [path]
