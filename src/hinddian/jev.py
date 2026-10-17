"""TypeSafe Jev (System One) gates with small-LLM fallback.

API: POST https://api.typesafe.ai/v1/systemone
Auth: Authorization: Bearer <TYPESAFE_API_KEY>
Env: TYPESAFE_API_KEY (required for Jev); TYPESAFE_DEFAULT_MODEL (default jev-latest)
Confidence: JEV_MIN_CONFIDENCE (default 0.65). Below → fallback or skip.
Never log or return the API key.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_URL = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/") + "/v1/systemone"
DEFAULT_MODEL = os.environ.get("TYPESAFE_DEFAULT_MODEL", "jev-latest")
MIN_CONF = float(os.environ.get("JEV_MIN_CONFIDENCE", "0.65"))
NOUL_YES = float(os.environ.get("JEV_NOUL_YES", "0.55"))
GATEWAY = os.environ.get("HB_GATEWAY", "http://127.0.0.1:3425/v1/chat/completions")
FALLBACK_MODEL = os.environ.get("JEV_FALLBACK_MODEL", "group/auto-flash")


@dataclass
class GateResult:
    ok: bool
    value: Any
    confidence: float
    source: str  # "jev" | "llm" | "skip" | "error"
    raw: dict | None = None
    error: str | None = None


def _api_key() -> str | None:
    k = (os.environ.get("TYPESAFE_API_KEY") or "").strip()
    return k or None


def available() -> bool:
    return bool(_api_key())


def _post_jev(state: Any, questions: dict) -> dict:
    key = _api_key()
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY not set")
    body = json.dumps({"model": DEFAULT_MODEL, "state": state, "questions": questions}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        DEFAULT_URL,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _llm_json(prompt: str) -> dict:
    body = json.dumps(
        {"model": FALLBACK_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1},
        ensure_ascii=False,
    ).encode()
    req = urllib.request.Request(
        GATEWAY,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer magpie"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        text = json.loads(r.read())["choices"][0]["message"]["content"]
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text[text.find("{") : text.rfind("}") + 1])


def noul(state: Any, instructions: str, *, true_c: str = "", false_c: str = "") -> GateResult:
    """Yes/no gate. value=True means yes."""
    q: dict = {"type": "noul", "instructions": instructions}
    if true_c or false_c:
        q["criteria"] = {"true": true_c or "yes", "false": false_c or "no"}
    if available():
        try:
            raw = _post_jev(state, {"g": q})
            ans = raw.get("answers", {}).get("g", {})
            p = float(ans.get("noul", 0))
            conf = abs(p - 0.5) * 2  # calibrated distance from coin-flip
            if conf < MIN_CONF:
                return GateResult(False, None, conf, "jev", raw, "low_confidence")
            return GateResult(True, p >= NOUL_YES, conf, "jev", raw)
        except Exception as e:
            return GateResult(False, None, 0.0, "error", None, str(e)[:200])
    return GateResult(False, None, 0.0, "skip", None, "no_typesafe_key")


def choice(state: Any, instructions: str, criteria: dict[str, str | None]) -> GateResult:
    q = {"type": "choice", "instructions": instructions, "criteria": criteria}
    if available():
        try:
            raw = _post_jev(state, {"g": q})
            ans = raw.get("answers", {}).get("g", {})
            conf = float(ans.get("confidence") or 0)
            val = ans.get("choice")
            if conf < MIN_CONF:
                return GateResult(False, val, conf, "jev", raw, "low_confidence")
            return GateResult(True, val, conf, "jev", raw)
        except Exception as e:
            return GateResult(False, None, 0.0, "error", None, str(e)[:200])
    return GateResult(False, None, 0.0, "skip", None, "no_typesafe_key")


def should_recall(cwd: str, first_message: str, projects: list[str]) -> GateResult:
    state = {"cwd": cwd or "", "message": (first_message or "")[:2000], "projects": projects}
    r = noul(
        state,
        "Should the agent recall project memory before answering? Yes if the task touches an existing project, prior decisions, or known pitfalls.",
        true_c="Task needs prior project memory",
        false_c="Greeting, unrelated, or fully self-contained",
    )
    if r.source in ("jev",) and r.ok:
        return r
    if r.source == "jev" and r.error == "low_confidence":
        # fall through to LLM
        pass
    elif r.source == "error":
        pass
    elif r.source == "skip":
        pass
    else:
        return r
    try:
        data = _llm_json(
            "用 JSON 回答是否需要召回项目记忆。字段: {\"should_recall\": true|false, \"confidence\": 0-1, \"project\": \"名或空\"}\n"
            f"cwd={cwd}\nmessage={first_message[:1500]}\nprojects={projects}"
        )
        return GateResult(
            True,
            bool(data.get("should_recall")),
            float(data.get("confidence") or 0.5),
            "llm",
            data,
        )
    except Exception as e:
        return GateResult(True, True, 0.4, "llm", None, f"fallback_default_yes:{e}"[:120])  # fail open to recall


def match_project(cwd: str, message: str, projects: list[str]) -> GateResult:
    if not projects:
        return GateResult(True, None, 1.0, "skip", None)
    # cheap path match first
    low = (cwd + " " + message).lower()
    for p in projects:
        if p.lower() in low:
            return GateResult(True, p, 0.95, "path", None)
    r = choice(
        {"cwd": cwd, "message": message[:2000]},
        "Which project does this session belong to? Pick none if unclear.",
        {p: f"Project {p}" for p in projects} | {"none": "No matching project / general tips only"},
    )
    if r.ok and r.value and r.value != "none":
        return r
    if r.source == "jev" and (not r.ok or r.value == "none"):
        if r.error == "low_confidence" or r.value == "none":
            try:
                data = _llm_json(
                    "用 JSON 选择项目。字段 {\"project\": \"名或 null\", \"confidence\": 0-1}\n"
                    f"可选: {projects}\ncwd={cwd}\nmessage={message[:1500]}"
                )
                proj = data.get("project")
                if proj in projects:
                    return GateResult(True, proj, float(data.get("confidence") or 0.5), "llm", data)
                return GateResult(True, None, float(data.get("confidence") or 0.5), "llm", data)
            except Exception as e:
                return GateResult(True, None, 0.3, "error", None, str(e)[:120])
    return GateResult(True, None, r.confidence, r.source, r.raw, r.error)


def turn_worth_keeping(turn_text: str) -> GateResult:
    r = noul(
        (turn_text or "")[:6000],
        "Does this single turn contain a reusable engineering decision, pitfall, or agent tip worth drafting into long-term memory? Ignore process chatter.",
        true_c="Reusable decision/lesson/tip",
        false_c="Process, chit-chat, one-off, or already trivial",
    )
    if r.ok:
        return r
    if r.source in ("skip", "error") or r.error == "low_confidence":
        try:
            data = _llm_json(
                "只分析这一轮对话。JSON: {\"keep\": true|false, \"confidence\": 0-1, \"type\": \"decision|lesson|tip|none\", "
                "\"project\": \"项目名或通用-未定\", \"title\": \"中文短标题\", \"summary\": \"一句话\"}\n"
                f"TURN:\n{turn_text[:5000]}"
            )
            return GateResult(True, data, float(data.get("confidence") or 0.5), "llm", data)
        except Exception as e:
            return GateResult(True, {"keep": False}, 0.3, "error", None, str(e)[:120])
    return r


def classify_turn(turn_text: str, projects: list[str]) -> GateResult:
    """Return dict with keep/type/project/title/summary via Jev choice+noul or LLM."""
    keep = turn_worth_keeping(turn_text)
    if keep.source == "llm" and isinstance(keep.value, dict):
        return keep
    if keep.ok and keep.value is False:
        return GateResult(True, {"keep": False, "type": "none"}, keep.confidence, keep.source, keep.raw)
    if keep.ok and keep.value is True:
        typ = choice(
            turn_text[:4000],
            "Classify the reusable knowledge type.",
            {
                "decision": "Chose A over B with lasting reasons",
                "lesson": "Pitfall and how to avoid it",
                "tip": "Cross-project agent/tool usage tip",
                "none": "Not worth keeping",
            },
        )
        proj = match_project("", turn_text, projects)
        payload = {
            "keep": True,
            "type": typ.value if typ.ok else "lesson",
            "project": proj.value or "通用-未定",
            "title": "",
            "summary": "",
            "confidence": min(keep.confidence, typ.confidence if typ.ok else keep.confidence),
        }
        if payload["type"] == "none":
            payload["keep"] = False
        # title via LLM always (Jev cannot generate strings)
        try:
            data = _llm_json(
                "根据原文写 JSON: {\"title\": \"中文短标题\", \"summary\": \"一句话\", "
                "\"scene\": \"场景\", \"practice\": \"做法\", \"reason\": \"理由\"}\n"
                f"type={payload['type']}\nTEXT:\n{turn_text[:4000]}"
            )
            payload.update({k: data.get(k, "") for k in ("title", "summary", "scene", "practice", "reason")})
        except Exception:
            payload["title"] = payload["type"] or "草稿"
            payload["summary"] = (turn_text or "")[:120]
        return GateResult(True, payload, payload["confidence"], "jev+llm", {"keep": keep.raw, "type": typ.raw})
    # fallback already attempted inside turn_worth_keeping
    if isinstance(keep.value, dict):
        return keep
    return GateResult(True, {"keep": False}, keep.confidence, keep.source, keep.raw, keep.error)


def write_verdict(new_summary: str, candidates: list[dict]) -> GateResult:
    """4-state: add|update|supersede|noop against candidate note digests."""
    state = {"new": new_summary[:3000], "candidates": candidates[:12]}
    r = choice(
        state,
        "How should this new memory relate to existing notes?",
        {
            "add": "Truly new topic; create a note",
            "update": "Same topic; merge into an existing id",
            "supersede": "New conclusion replaces an old note",
            "noop": "Duplicate or not worth keeping",
        },
    )
    if r.ok:
        return r
    try:
        data = _llm_json(
            "四态裁决 JSON: {\"verdict\": \"add|update|supersede|noop\", \"target_id\": \"或空\", "
            "\"confidence\": 0-1, \"reason\": \"…\"}\n"
            f"NEW:\n{new_summary[:2500]}\nCANDIDATES:\n{json.dumps(candidates[:12], ensure_ascii=False)[:4000]}"
        )
        return GateResult(True, data.get("verdict"), float(data.get("confidence") or 0.5), "llm", data)
    except Exception as e:
        return GateResult(True, "add", 0.3, "error", None, str(e)[:120])
