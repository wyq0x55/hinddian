"""Server-side session finalize: hook buffer → Jev keep/extract → push_draft, logged to jev_log.

Jev runs here (the server's JEV_BASE_URL first, then TypeSafe cloud if configured — see jev.py).
Both fail → source=none, nothing is written and the client keeps its buffer to retry.
Only metadata goes to the decision log, never turn text.
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable

from . import jev, jev_log

UNKNOWN_PROJECT = "通用-未定"
MAX_TURNS = 400
MAX_TURN_CHARS = 20000
MAX_TOTAL_CHARS = 200000
CLIP_LIMIT, CLIP_HEAD = 12000, 4000


class FinalizeError(ValueError):
    pass


def _s(v: Any, n: int) -> str:
    if v is None:
        return ""
    if not isinstance(v, (str, int, float)):
        raise FinalizeError("string expected")
    return re.sub(r"[\x00-\x1f]+", " ", str(v)).strip()[:n]


def _base(v: Any) -> str:
    return os.path.basename(_s(v, 512).rstrip("/\\").replace("\\", "/"))[:128]


def parse(args: dict) -> dict:
    """Validate the hook payload. Only turn text (already whitelisted by the hook) is accepted."""
    if not isinstance(args, dict):
        raise FinalizeError("object expected")
    sid = _s(args.get("session_id"), 128)
    if not sid:
        raise FinalizeError("session_id required")
    turns = args.get("turns")
    if not isinstance(turns, list):
        raise FinalizeError("turns must be a list")
    if len(turns) > MAX_TURNS:
        raise FinalizeError("too many turns")
    texts, total = [], 0
    for t in turns:
        tx = t.get("text") if isinstance(t, dict) else t
        if not isinstance(tx, str):
            raise FinalizeError("turn text must be a string")
        tx = tx.strip()[:MAX_TURN_CHARS]
        total += len(tx)
        if total > MAX_TOTAL_CHARS:
            raise FinalizeError("buffer too large")
        if tx:
            texts.append(tx)
    tc = args.get("turn_count")
    return {
        "session_id": sid,
        "project": _s(args.get("project"), 128),
        "cwd": _base(args.get("cwd")),
        "repo": _base(args.get("repo")),
        "client_id": _s(args.get("client_id") or args.get("host"), 64) or "unknown",
        "finalize_reason": _s(args.get("finalize_reason") or args.get("reason"), 40) or "unknown",
        "turn_count": tc if isinstance(tc, int) and not isinstance(tc, bool) and tc >= 0 else len(turns),
        "texts": texts,
    }


def clip(text: str) -> str:
    if len(text) <= CLIP_LIMIT:
        return text
    return text[:CLIP_HEAD] + "\n\n…（中间省略）…\n\n" + text[-(CLIP_LIMIT - CLIP_HEAD):]


def norm_source(src: str | None) -> str:
    s = str(src or "")
    if s.startswith("jev:local") or s in ("magpie", "local") or (s.startswith("jev:") and ("magpie" in s or "local" in s)):
        return "jev:local"
    if s.startswith("jev:cloud") or s in ("cloud", "typesafe-cloud") or (s.startswith("jev:") and "cloud" in s):
        return "jev:cloud"
    return s if s.startswith("jev:") else "none"


def pick_project(p: dict, jev_project: str | None, projects: list[str]) -> str:
    """Hook's project > a known project named by the repo / cwd basename > the repo itself (a new
    project waits for dashboard approval) > what Jev read from the text > 通用-未定."""
    if p["project"]:
        return p["project"]
    for name in (p["repo"], p["cwd"]):
        if not name:
            continue
        low = name.lower()
        hits = [x for x in projects if x and (x.lower() == low or x.lower() in low)]
        if hits:
            return max(hits, key=len)
    if p["repo"]:
        return p["repo"]
    if jev_project and jev_project != UNKNOWN_PROJECT:
        return jev_project
    return UNKNOWN_PROJECT


def _items(v: Any) -> list[str]:
    return [str(x).strip() for x in (v or []) if str(x).strip()] if isinstance(v, list) else []


def body(val: dict, title: str, typ: str) -> str:
    d, l, pr = _items(val.get("decision")), _items(val.get("lesson")), _items(val.get("preference"))
    if not (d or l or pr):
        block = f"### {title}\n- 场景：{val.get('scene') or ''}\n- 做法：{val.get('practice') or ''}\n- 理由：{val.get('reason') or ''}"
        if typ == "decision":
            d = [block]
        elif typ == "preference":
            pr = [block]
        else:
            l = [block]
    out = []
    for head, xs in (("DECISIONS", d), ("LESSONS", l), ("PREFERENCES", pr)):
        out.append(f"## {head}")
        out += [x if x.startswith("### ") else f"- {x}" for x in xs]
        out.append("")
    oq = _items(val.get("open_question"))
    if oq:
        out.append("## OPEN QUESTIONS")
        out += [f"- {x}" for x in oq]
        out.append("")
    return "\n".join(out).strip() + "\n"


def finalize(args: dict, *, projects: Callable[[], list[str]], push: Callable[[dict], Any]) -> dict:
    """Returns {ok, outcome, retry, source, keep, pushed, ...}. retry=True → client keeps the buffer."""
    p = parse(args)
    res = _run(p, projects, push)
    _log(p, res)
    return {k: v for k, v in res.items() if k != "draft_obj"}


def _run(p: dict, projects, push) -> dict:
    if not p["texts"]:
        return {"ok": True, "outcome": "empty", "retry": False, "source": "none", "keep": None, "pushed": False}
    try:
        names = projects()
    except Exception:
        names = []
    try:
        r = jev.classify_turn(clip("\n\n---\n\n".join(p["texts"])), names, p["cwd"])
    except Exception as e:
        return {"ok": False, "outcome": "jev_unavailable", "retry": True, "source": "none", "keep": None,
                "pushed": False, "error": f"jev_unavailable: {type(e).__name__}"}
    raw = str(r.source or "none")
    if raw.startswith("llm"):  # no loose LLM auto-keep
        return {"ok": True, "outcome": "llm_forbidden", "retry": False, "source": "none", "keep": None, "pushed": False}
    src = norm_source(raw)
    if src == "none":
        return {"ok": False, "outcome": "jev_unavailable", "retry": True, "source": "none", "keep": None,
                "pushed": False, "error": f"jev_unavailable: {str(r.error or '')[:120]}"}
    val = r.value if isinstance(r.value, dict) else {}
    conf = r.confidence
    if not val.get("keep"):
        return {"ok": True, "outcome": "keep_false", "retry": False, "source": src, "keep": False,
                "pushed": False, "confidence": conf}
    title = str(val.get("title") or val.get("summary") or f"session-{p['session_id'][:12]}")[:200]
    typ = str(val.get("type") or "lesson")
    payload = {
        "project": pick_project(p, val.get("project"), names),
        "title": title, "body": body(val, title, typ), "type": typ, "confidence": conf,
        "origin": f"session-finalize:{p['finalize_reason']}:{src}:server",
        "session_id": p["session_id"], "jev_source": src, "turn_count": p["turn_count"],
        "finalize_reason": p["finalize_reason"],
    }
    try:
        out = push(payload)
    except Exception as e:
        return {"ok": False, "outcome": "push_failed", "retry": True, "source": src, "keep": True, "pushed": False,
                "confidence": conf, "error": f"push_failed: {type(e).__name__}"}
    draft = (out.get("path") or out.get("id")) if isinstance(out, dict) else None
    return {"ok": True, "outcome": "pushed", "retry": False, "source": src, "keep": True, "pushed": True,
            "confidence": conf, "project": payload["project"], "draft_path": draft}


def _log(p: dict, res: dict) -> None:
    try:
        jev_log.append(jev_log.validate({
            "session_id": p["session_id"], "project": res.get("project") or p["project"] or None,
            "cwd": p["cwd"] or None, "host": p["client_id"], "event": "finalize",
            "finalize_reason": p["finalize_reason"], "jev_source": res.get("source"), "keep": res.get("keep"),
            "confidence": res.get("confidence") if isinstance(res.get("confidence"), (int, float)) else None,
            "outcome": res.get("outcome"), "error": res.get("error"), "turn_count": p["turn_count"],
            "pushed": bool(res.get("pushed")), "draft_path": res.get("draft_path"),
        }))
    except Exception:
        pass  # logging never breaks finalize
