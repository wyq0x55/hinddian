"""SessionStart: finalize previous session buffers (detached); inject the memory routing block.

The block sits at the very front of the conversation, so it must be byte-stable across turns
and sessions (prompt-cache prefix): fixed rules + sorted project names only — no counts,
dates or note text. Per-message recall happens later, in prompt_recall.py.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract  # noqa: E402
import hookcfg  # noqa: E402
import session_buf  # noqa: E402

RULES = """\
长期记忆来自 hinddian-memory MCP（以 Obsidian 笔记为准）。
- 自动召回：用户消息若命中相关笔记，会以 <hinddian_recall> 附在该消息后。可能不相关，自行判断；不必向用户复述。
- 需要更多：recall(query, project) 搜索；get_note(id) 看全文；routing_project(project) 看项目现状与决策/经验列表。
- 工具可能是延迟加载的：首次调用找不到时，先用 ToolSearch 搜 "hinddian" 加载，不要因此当作没有记忆。
- 写入：会话由 hooks 自动整理成草稿（push_draft），Agent 不要手调 push_draft。用户要记住、或你发现记忆有误时：tip/preference/lesson → upsert_note；decision/架构纠正 → suggest_correction（仪表盘「Agent 修正」批准）。不硬删（supersede/obsolete），不写密钥。
- 长期记忆以 hinddian 为准：要记住的内容按上面写入，不要另写进 Agent 自带的记忆（Claude 的 MEMORY.md、Codex memories）。"""


def routing_block(projects: list[str], current: str | None) -> str:
    lines = ["<hinddian_memory>", RULES]
    if projects:
        lines.append("- 已知项目：" + "、".join(projects))
    if current:
        lines.append(f"- 当前目录对应项目：{current}")
    lines.append("</hinddian_memory>")
    return "\n".join(lines)


def match_project(cwd: str, projects: list[str]) -> str | None:
    low = cwd.lower()
    hits = [p for p in projects if p and p.lower() in low]
    return max(hits, key=len) if hits else None


def main() -> None:
    stdin = sys.stdin.read(50000) if not sys.stdin.isatty() else ""
    try:
        raw = json.loads(stdin) if stdin.strip().startswith("{") else {}
    except ValueError:
        raw = {}
    why = hookcfg.transport_problem()
    if why:
        setup = hookcfg.HERE / "setup.py"
        hookcfg.emit_context(
            "SessionStart",
            f"hinddian-memory 未就绪（{why}）。请提醒用户在终端运行一次：\n"
            f'  python3 "{setup}" --url https://<host>:8444/hinddian --token <HINDDIAN_MCP_TOKEN>',
            raw,
        )
        return
    payload = extract.parse_hook_payload(stdin)
    cwd = payload.get("cwd") or os.environ.get("PWD") or ""
    sid = session_buf.stable_session_id(payload.get("session_id"), cwd, "new")

    # compact / resume continue the same session: nothing new to finalize
    if raw.get("source") not in ("compact", "resume"):
        if not hookcfg.spawn_finalize("--current", sid, log=session_buf.hook_dir() / "finalize.log"):
            import finalize

            finalize.finalize_idle_and_others(current_sid=sid)

    try:
        g = hookcfg.req("GET", "/api/memory/routing/global", timeout=5)
        projects = sorted(p["name"] for p in g.get("projects") or [] if p.get("name"))
    except Exception:  # noqa: BLE001 — server down: still give the rules, just no project list
        projects = []
    current = match_project(cwd, projects)
    if current:  # prompt_recall scopes per-message recall to it
        with contextlib.suppress(OSError):
            session_buf.side_file(sid, "project").write_text(current, encoding="utf-8")
    hookcfg.emit_context("SessionStart", routing_block(projects, current), raw)


if __name__ == "__main__":
    main()
