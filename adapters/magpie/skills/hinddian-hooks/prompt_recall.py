"""UserPromptSubmit: recall notes relevant to the user's message and attach them to that turn.

Cache-safe by placement: the text lands at the tail of the current turn, never in the
conversation prefix. Kept cheap: skips short / acknowledgement / slash / system prompts,
at most MAX_ITEMS one-line items, only notes not already injected this session, one request
with a short timeout (silently skipped when slow or down).

Off switch: HINDDIAN_AUTO_RECALL=0 (or "auto_recall": false in config.json).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hookcfg  # noqa: E402
import session_buf  # noqa: E402

MIN_CHARS = int(os.environ.get("HINDDIAN_RECALL_MIN_CHARS", "8"))
MAX_ITEMS = int(os.environ.get("HINDDIAN_RECALL_MAX_ITEMS", "3"))
MIN_SCORE = float(os.environ.get("HINDDIAN_RECALL_MIN_SCORE", "0.5"))  # Hindsight reranker (0..1)
LOCAL_MIN_SCORE = 0.3  # server's local bigram fallback: share of query bigrams matched
# Note types worth injecting (hub / project-state pages are not). Without metadata a Hindsight
# result only carries its fact kind (world/experience/observation), so those pass too.
NOTE_TYPES = {"decision", "lesson", "tip", "world", "experience", "observation"}
TIMEOUT = float(os.environ.get("HINDDIAN_RECALL_TIMEOUT", "3"))
ACKS = {
    "ok", "okay", "yes", "no", "y", "n", "thanks", "thx", "continue", "go", "go on", "lgtm", "done",
    "好", "好的", "可以", "行", "嗯", "是", "对", "不", "继续", "谢谢", "收到", "没问题", "需要", "不需要", "开始",
}


def worth_recalling(prompt: str) -> bool:
    p = prompt.strip()
    if not p or p.startswith(("/", "<task-notification>", "<system-reminder>", "<command-")):
        return False
    if p.lower().strip(" .!?。！？~") in ACKS:
        return False
    return len(re.sub(r"\s+", "", p)) >= MIN_CHARS


def _snippet(text: str, limit: int = 110) -> str:
    t = re.sub(r"\A---\n.*?\n---\n", "", text or "", flags=re.S)
    t = "\n".join(l for l in t.splitlines() if l.strip() and not l.startswith(("#", "> ")))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit] + ("…" if len(t) > limit else "")


def normalize(results: list) -> list[dict]:
    """Hindsight results and the local-fallback rows → [{id, title, snippet}], relevance-filtered."""
    out = []
    for r in results or []:
        if not isinstance(r, dict):
            continue
        meta = r.get("metadata") or {}
        if (meta.get("type") or r.get("type") or "lesson") not in NOTE_TYPES:  # hubs / project state pages
            continue
        scores = r.get("scores") or {}
        rel = scores.get("reranker", scores.get("final"))
        if rel is not None and float(rel) < MIN_SCORE:
            continue
        if "score" in r and float(r["score"]) < LOCAL_MIN_SCORE:
            continue
        nid = r.get("document_id") or r.get("id")
        title = meta.get("title") or r.get("title") or r.get("context") or _snippet(r.get("text", ""), 30)
        body = r.get("text") or (r.get("practice") or "") + " " + (r.get("scene") or "")
        out.append({"id": str(nid or ""), "title": str(title), "snippet": _snippet(body)})
    return out


def session_project(sid: str) -> str:
    """Project matched from cwd at SessionStart (session_start.py writes it); "" = none."""
    try:
        return session_buf.side_file(sid, "project").read_text(encoding="utf-8").strip()[:120]
    except OSError:
        return ""


def pick_new(sid: str, items: list[dict]) -> list[dict]:
    p = session_buf.side_file(sid, "recalled.json")
    try:
        seen = set(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        seen = set()
    fresh, ids = [], set()
    for i in items:  # one line per note, even if the server sent several facts of it
        if i["id"] and i["id"] not in seen and i["id"] not in ids:
            fresh.append(i)
            ids.add(i["id"])
    fresh = fresh[:MAX_ITEMS]
    if fresh:
        p.write_text(json.dumps(sorted(seen | {i["id"] for i in fresh}), ensure_ascii=False), encoding="utf-8")
    return fresh


def render(items: list[dict]) -> str:
    lines = ["<hinddian_recall>", "可能相关的长期记忆（按本条消息自动检索，可能不相关）："]
    lines += [f"- [{i['id']}] {i['title']}" + (f" — {i['snippet']}" if i["snippet"] else "") for i in items]
    lines += ["需要全文用 get_note(id)。", "</hinddian_recall>"]
    return "\n".join(lines)


def main() -> None:
    if not hookcfg.flag("HINDDIAN_AUTO_RECALL", True) or hookcfg.transport_problem():
        return
    stdin = sys.stdin.read(100000) if not sys.stdin.isatty() else ""
    try:
        raw = json.loads(stdin) if stdin.strip().startswith("{") else {}
    except ValueError:
        return
    prompt = str(raw.get("prompt") or raw.get("user_prompt") or raw.get("message") or "")
    if not worth_recalling(prompt):
        return
    sid = session_buf.stable_session_id(raw.get("session_id"), raw.get("cwd") or "", "new")
    body = {"query": prompt.strip()[:500], "budget": "low"}
    project = session_project(sid)
    if project:  # this project's notes + global tips, not every project's
        body["project"] = project
    try:
        r = hookcfg.req("POST", "/api/memory/recall", body, timeout=TIMEOUT)
    except Exception:  # noqa: BLE001 — never block or fail the user's turn
        return
    items = pick_new(sid, normalize(r.get("results") if isinstance(r, dict) else []))
    if items:
        hookcfg.emit_context("UserPromptSubmit", render(items), raw)


if __name__ == "__main__":
    main()
