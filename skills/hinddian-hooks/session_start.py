"""SessionStart: finalize previous session buffers (detached); inject the memory routing block.

The block sits at the very front of the conversation, so it must be byte-stable across turns
and sessions (prompt-cache prefix): fixed rules + sorted project names only — no counts,
dates or note text. A bounded recent-memory section follows it; per-message recall happens
later, in prompt_recall.py.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract  # noqa: E402
import hookcfg  # noqa: E402
import session_buf  # noqa: E402

RECENT_ITEMS = max(0, min(20, int(os.environ.get("HINDDIAN_SESSION_RECENT_ITEMS", "6"))))
RECENT_CHARS = 2400  # approximate ~800 tokens; includes section markers
START_TIMEOUT = 5.0  # routing and recent-note requests share the existing routing budget

RULES = """\
长期记忆来自 hinddian-memory MCP（以 Obsidian 笔记为准）。
- 自动召回：用户消息若命中相关笔记，会以 <hinddian_recall> 附在该消息后。可能不相关，自行判断；不必向用户复述。
- 需要更多：recall(query, project) 搜索；get_note(id) 看全文；routing_project(project) 看项目现状与决策/经验列表。
- 工具可能是延迟加载的：首次调用找不到时，先用 ToolSearch 搜 "hinddian" 加载，不要因此当作没有记忆。
- 写入：会话由 hooks 自动整理成草稿（push_draft），Agent 不要手调 push_draft。用户要记住、或你发现记忆有误时：tip/preference/lesson/decision 均用 upsert_note 直写；suggest_correction 同样直写。人在 Obsidian 改删即管理记忆，仪表盘审批可选。不硬删（supersede/obsolete），不调 Hindsight retain，不写密钥。
- 双可读笔记：标题即命题，填写 type/project/status 与场景/做法/理由；先看项目标题地图，再 get_note 展开全文，updated 表示笔记更新时间。
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


def last_closing_summary(sid: str, project: str, projects: list[str]) -> str:
    """Read the latest other session's final assistant reply, never a user-only turn.

    Work is bounded even if local cleanup has stopped running. Side files and malformed or
    oversized buffers are ignored, and both open and finalized buffers can supply a closing.
    """
    latest, stamp = None, -1.0
    deadline = time.monotonic() + 0.05
    for count, path in enumerate(session_buf.sessions_dir().glob("*.json")):
        if count >= 200 or time.monotonic() >= deadline:
            break
        if path.name.endswith(".recalled.json"):
            continue
        try:
            if path.stat().st_size > 512_000:
                continue
            buf = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(buf, dict) or not buf.get("session_id") or buf["session_id"] == sid:
                continue
            owner = buf.get("project")
            if not owner:
                try:
                    owner = session_buf.side_file(buf["session_id"], "project").read_text(encoding="utf-8").strip()
                except OSError:
                    owner = match_project(str(buf.get("cwd") or ""), projects)
            if owner != project:
                continue
            updated = float(buf.get("updated_at") or 0)
            if updated > stamp:
                latest, stamp = buf, updated
        except (OSError, ValueError, TypeError):
            continue
    if latest:
        for turn in reversed(latest.get("turns") or []):
            if not isinstance(turn, dict):
                continue
            for role, text in reversed(extract.whitelist_pairs(str(turn.get("text") or ""))):
                if role == "assistant" and text.strip():
                    return " ".join(session_buf.strip_private(text).split())[:1000]
    return ""


def recent_context(sid: str, current: str | None, projects: list[str], deadline: float) -> str:
    if not current:
        return ""
    summary = ""
    with contextlib.suppress(Exception):  # optional local context must never break SessionStart
        closing = last_closing_summary(sid, current, projects)
        if closing:
            summary = "上次会话结语：" + closing
    titles = []
    remaining = deadline - time.monotonic()
    if RECENT_ITEMS and remaining > 0.05:
        with contextlib.suppress(Exception):
            rows = hookcfg.req("GET", "/api/memory/notes?" + urlencode(
                {"project": current, "limit": RECENT_ITEMS, "order": "recent"}),
                timeout=min(2.0, remaining))
            titles = ["- " + " ".join(str(n["title"]).split())[:160]
                      for n in rows if isinstance(n, dict) and n.get("title")
                      and n.get("status", "active") == "active" and n.get("project", current) == current]
    if not titles and not summary:
        return ""
    head, tail = "<hinddian_recent>\n", "\n</hinddian_recent>"
    budget = RECENT_CHARS - len(head) - len(tail)
    # Reserve the closing before clipping long title lists.
    index = "\n".join(["最近的项目笔记（仅标题）：", *titles[:RECENT_ITEMS]]) if titles else ""
    index = index[:max(0, budget - len(summary) - 1)]
    return head + "\n".join(part for part in (index, summary) if part) + tail


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

    deadline = time.monotonic() + START_TIMEOUT
    try:
        g = hookcfg.req("GET", "/api/memory/routing/global", timeout=START_TIMEOUT)
        projects = sorted(p["name"] for p in g.get("projects") or [] if p.get("name"))
    except Exception:  # noqa: BLE001 — server down: still give the rules, just no project list
        projects = []
    current = match_project(cwd, projects)
    if current:  # prompt_recall scopes per-message recall to it
        with contextlib.suppress(OSError):
            session_buf.side_file(sid, "project").write_text(current, encoding="utf-8")
    block = routing_block(projects, current)
    recent = recent_context(sid, current, projects, deadline)
    hookcfg.emit_context("SessionStart", block + ("\n" + recent if recent else ""), raw)


if __name__ == "__main__":
    main()
