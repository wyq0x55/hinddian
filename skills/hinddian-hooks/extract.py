"""Whitelist extraction for Magpie turn/session text.

Keep only user messages + final assistant replies.
Strip: system/persona, routing tables, MCP/tool schemas, skills catalog,
recalled memory dumps, raw tool logs, hook noise.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

# Role markers common across agents / Magpie dumps
_ROLE_RE = re.compile(
    r"(?im)^(?:#{1,3}\s*)?(?:\[)?(system|developer|user|human|assistant|model|tool|function)"
    r"(?:\s*(?:message|role))?(?:\])?\s*[:：]\s*"
)

_JUNK_BLOCK = re.compile(
    r"(?is)(?:"
    r"<system(?:_reminder)?>.*?</system(?:_reminder)?>|"
    r"```(?:json)?\s*\{[^{}]{0,200}\"?(?:tools?|mcpServers|inputSchema|parameters)\"?.*?\n```|"
    r"(?:^|\n)(?:MCP|Tools?|Skills?|Routing|Route table|Hinddian-memory|Projects:)\s*:?[^\n]*(?:\n(?:[ \t]+|\-|\*).*)*|"
    r"(?:^|\n)(?:Gate should_recall|when_to_recall|PROJECT \w).*|"
    r"(?:^|\n)(?:function_calls|tool_result|toolu_|invoke\s+\w+).*"
    r")"
)

_RECALL_DUMP = re.compile(
    r"(?is)(?:recalled?\s+memor(?:y|ies)|routing_global|routing_project|"
    r"hinddian-memory MCP|Stable prefix).*?(?=\n(?:user|human|assistant)[:：]|\Z)"
)

_MAX_ASSIST = int(os.environ.get("HINDDIAN_EXTRACT_ASSIST_CHARS", "4000"))
_MAX_USER = int(os.environ.get("HINDDIAN_EXTRACT_USER_CHARS", "3000"))
_MAX_TOTAL = int(os.environ.get("HINDDIAN_EXTRACT_TOTAL_CHARS", "12000"))


def _clean_piece(text: str, *, role: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    t = _JUNK_BLOCK.sub("\n", t)
    t = _RECALL_DUMP.sub("\n", t)
    # drop long json blobs / stack traces
    t = re.sub(r"(?s)```(?:json|javascript|typescript|python|bash|shell)?\n.{800,}?\n```", "[code omitted]", t)
    t = re.sub(r"(?m)^(Traceback \(most recent call last\):).*(?=\n\S|\Z)", r"\1 …", t)
    lim = _MAX_USER if role == "user" else _MAX_ASSIST
    if len(t) > lim:
        t = t[: lim - 20] + "\n…[truncated]"
    return t.strip()


def _from_messages(messages: list[Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or m.get("type") or "").lower()
        if role in ("human",):
            role = "user"
        if role in ("model", "ai", "bot"):
            role = "assistant"
        if role not in ("user", "assistant"):
            continue
        content = m.get("content") or m.get("text") or m.get("message") or ""
        if isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, str):
                    parts.append(p)
                elif isinstance(p, dict):
                    if p.get("type") in ("tool_use", "tool_result", "function_call"):
                        continue
                    parts.append(str(p.get("text") or p.get("content") or ""))
            content = "\n".join(parts)
        elif not isinstance(content, str):
            content = str(content)
        cleaned = _clean_piece(content, role=role)
        if cleaned:
            out.append((role, cleaned))
    return out


def _from_plaintext(text: str) -> list[tuple[str, str]]:
    raw = (text or "").strip()
    if not raw:
        return []
    # Try JSON envelope first
    if raw.startswith("{") or raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return _from_messages(data)
            if isinstance(data, dict):
                for key in ("messages", "conversation", "turns", "history"):
                    if isinstance(data.get(key), list):
                        return _from_messages(data[key])
                # single message
                if data.get("role") or data.get("content"):
                    return _from_messages([data])
                # common agent hook fields
                user = data.get("prompt") or data.get("user_message") or data.get("last_user_message")
                asst = (
                    data.get("last_assistant_message")
                    or data.get("assistant_message")
                    or data.get("response")
                    or data.get("output")
                )
                pairs = []
                if user:
                    pairs.append(("user", _clean_piece(str(user), role="user")))
                if asst:
                    pairs.append(("assistant", _clean_piece(str(asst), role="assistant")))
                pairs = [(r, t) for r, t in pairs if t]
                if pairs:
                    return pairs
        except Exception:
            pass

    # Role-labeled plaintext
    parts: list[tuple[str, str]] = []
    matches = list(_ROLE_RE.finditer(raw))
    if matches:
        for i, m in enumerate(matches):
            role = m.group(1).lower()
            if role in ("human",):
                role = "user"
            if role in ("model",):
                role = "assistant"
            if role not in ("user", "assistant"):
                continue
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
            cleaned = _clean_piece(raw[start:end], role=role)
            if cleaned:
                parts.append((role, cleaned))
        if parts:
            return parts

    # Fallback: treat whole blob as mixed; strip junk then keep as user-ish note
    cleaned = _clean_piece(raw, role="user")
    return [("user", cleaned)] if cleaned else []


def whitelist_pairs(turn_text: str | None = None, messages: list | None = None) -> list[tuple[str, str]]:
    if messages:
        return _from_messages(messages)
    return _from_plaintext(turn_text or "")


def format_whitelist(pairs: list[tuple[str, str]]) -> str:
    chunks = []
    total = 0
    for role, text in pairs:
        block = f"{role.upper()}:\n{text}"
        if total + len(block) > _MAX_TOTAL:
            remain = _MAX_TOTAL - total
            if remain > 80:
                chunks.append(block[: remain - 20] + "\n…[truncated]")
            break
        chunks.append(block)
        total += len(block) + 2
    return "\n\n".join(chunks).strip()


def extract_turn_text(raw: str | None = None) -> str:
    """Public: whitelist-only text for one turn (or stdin blob)."""
    return format_whitelist(whitelist_pairs(raw or ""))


def structured_body(*, decisions: list[str], lessons: list[str], preferences: list[str], title: str = "") -> str:
    nl = "\n"
    lines = []
    if title:
        lines.append(f"# {title}")
        lines.append("")
    lines.append("## DECISIONS")
    for d in decisions or []:
        if d and str(d).strip():
            lines.append(f"- {str(d).strip()}")
    lines.append("")
    lines.append("## LESSONS")
    for d in lessons or []:
        if d and str(d).strip():
            lines.append(f"- {str(d).strip()}")
    lines.append("")
    lines.append("## PREFERENCES")
    for d in preferences or []:
        if d and str(d).strip():
            lines.append(f"- {str(d).strip()}")
    return nl.join(lines).strip() + "\n"


def parse_hook_payload(stdin_text: str = "", env: dict | None = None) -> dict[str, Any]:
    """Best-effort Magpie / agent hook payload → session_id, cwd, turn text, project hint."""
    env = env or dict(os.environ)
    raw = (stdin_text or "").strip()
    data: dict[str, Any] = {}
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}

    session_id = (
        data.get("session_id")
        or data.get("sessionId")
        or data.get("conversation_id")
        or data.get("conversationId")
        or data.get("thread_id")
        or env.get("MAGPIE_SESSION_ID")
        or env.get("CLAUDE_SESSION_ID")
        or env.get("CODEX_SESSION_ID")
        or env.get("CURSOR_SESSION_ID")
        or ""
    )
    cwd = (
        data.get("cwd")
        or data.get("cwd_path")
        or env.get("MAGPIE_CWD")
        or env.get("PWD")
        or ""
    )
    turn = (
        env.get("MAGPIE_TURN_TEXT")
        or data.get("turn_text")
        or data.get("transcript")
        or ""
    )
    # Claude Code / Codex Stop & SessionStart common fields
    if not turn and data:
        user = (
            data.get("prompt")
            or data.get("user_prompt")
            or data.get("last_user_message")
            or data.get("user_message")
        )
        asst = (
            data.get("last_assistant_message")
            or data.get("assistant_message")
            or data.get("response")
            or data.get("completion")
            or data.get("output")
        )
        if user or asst:
            pairs = []
            if user:
                pairs.append(("user", _clean_piece(str(user), role="user")))
            if asst:
                pairs.append(("assistant", _clean_piece(str(asst), role="assistant")))
            turn = format_whitelist([(r, x) for r, x in pairs if x])
        # Optional transcript file (Claude Stop often provides transcript_path)
        tpath = data.get("transcript_path") or data.get("transcriptPath")
        if not turn and tpath:
            try:
                from pathlib import Path as _P
                tp = _P(str(tpath))
                if tp.is_file() and tp.stat().st_size < 2_000_000:
                    turn = extract_turn_text(tp.read_text(encoding="utf-8", errors="replace")[-80000:])
            except Exception:
                pass
    if not turn and data:
        # Build from last user+assistant in payload
        pairs = whitelist_pairs(messages=data.get("messages") if isinstance(data.get("messages"), list) else None)
        if not pairs:
            pairs = whitelist_pairs(json.dumps(data, ensure_ascii=False)[:20000])
        turn = format_whitelist(pairs)
    elif not turn and raw and not data:
        turn = extract_turn_text(raw)
    else:
        turn = extract_turn_text(turn) if turn else extract_turn_text(raw)

    # Claude / Codex cwd aliases
    if not cwd:
        cwd = str(data.get("working_directory") or data.get("workdir") or "").strip()

    return {
        "session_id": str(session_id or "").strip() or None,
        "cwd": str(cwd or "").strip(),
        "turn_text": turn,
        "raw_data": data,
        "first_message": (
            env.get("MAGPIE_FIRST_MESSAGE")
            or env.get("MAGPIE_PROMPT")
            or data.get("prompt")
            or ""
        ),
    }
