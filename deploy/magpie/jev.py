"""Jev (System One) gates via Magpie local gateway (preferred) or TypeSafe cloud.

Primary (no cloud key needed when Magpie has ``typesafe`` / jev provider):
  POST http://127.0.0.1:3425/v1/systemone
  Auth: Authorization: Bearer magpie   (or MAGPIE_GATEWAY_KEY / JEV_API_KEY)
  Model: typesafe/jev-latest (Magpie) — also accepts jev-latest

  Magpie hosts call localhost:3425. Huawei uses magpie-tunnel.service
  (LocalForward DMIT Magpie :3425 → 127.0.0.1:3425). Override with JEV_BASE_URL
  or MAGPIE_JEV_URL (full …/v1/systemone URL).

Secondary (optional):
  POST https://api.typesafe.ai/v1/systemone
  Auth: Bearer TYPESAFE_API_KEY
  Model: jev-latest

Tertiary: Magpie chat completions LLM fallback (group/auto-flash).

Never log or return API keys.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

MIN_CONF = float(os.environ.get("JEV_MIN_CONFIDENCE", "0.65"))
NOUL_YES = float(os.environ.get("JEV_NOUL_YES", "0.55"))
GATEWAY = os.environ.get("HB_GATEWAY", "http://127.0.0.1:3425/v1/chat/completions")
FALLBACK_MODEL = os.environ.get("JEV_FALLBACK_MODEL", "group/auto-flash")
CLOUD_URL = (
    os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/")
    + "/v1/systemone"
)
CLOUD_MODEL = os.environ.get("TYPESAFE_DEFAULT_MODEL", "jev-latest")
MAGPIE_MODEL = os.environ.get("JEV_MODEL", "typesafe/jev-latest")


@dataclass
class GateResult:
    ok: bool
    value: Any
    confidence: float
    source: str  # "jev" | "llm" | "skip" | "error" | "path"
    raw: dict | None = None
    error: str | None = None


def _gateway_base() -> str:
    """Derive Magpie base (scheme://host:port) from HB_GATEWAY or default."""
    raw = (os.environ.get("MAGPIE_GATEWAY") or "").strip()
    if raw:
        return raw.rstrip("/")
    chat = GATEWAY.rstrip("/")
    if chat.endswith("/v1/chat/completions"):
        chat = chat[: -len("/v1/chat/completions")]
    elif chat.endswith("/chat/completions"):
        chat = chat[: -len("/chat/completions")]
    if not chat:
        chat = "http://127.0.0.1:3425"
    return chat


def _magpie_systemone_url() -> str:
    explicit = (
        os.environ.get("JEV_BASE_URL")
        or os.environ.get("MAGPIE_JEV_URL")
        or ""
    ).strip()
    if explicit:
        u = explicit.rstrip("/")
        if not u.endswith("/systemone"):
            u = u + "/systemone" if u.endswith("/v1") else u + "/v1/systemone"
        return u
    return _gateway_base().rstrip("/") + "/v1/systemone"


def _magpie_key() -> str:
    return (
        os.environ.get("JEV_API_KEY")
        or os.environ.get("MAGPIE_GATEWAY_KEY")
        or "magpie"
    ).strip()


def _typesafe_key() -> str | None:
    k = (os.environ.get("TYPESAFE_API_KEY") or "").strip()
    return k or None


def _force_cloud() -> bool:
    return (os.environ.get("JEV_FORCE_CLOUD") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _endpoints() -> list[tuple[str, str, str, str]]:
    """Ordered (url, bearer, model, label)."""
    out: list[tuple[str, str, str, str]] = []
    if not _force_cloud():
        out.append((_magpie_systemone_url(), _magpie_key(), MAGPIE_MODEL, "magpie"))
    ts = _typesafe_key()
    if ts:
        out.append((CLOUD_URL, ts, CLOUD_MODEL, "typesafe-cloud"))
    return out


def available() -> bool:
    """True if Magpie-local gateway path is configured or cloud key is set.

    Does not probe the network; connection failures fall through to LLM.
    """
    return bool(_endpoints())


def backend_info() -> dict[str, Any]:
    """Safe diagnostics (no secrets)."""
    eps = [
        {
            "label": label,
            "url": url,
            "model": model,
            "auth": "bearer-set",
        }
        for url, _key, model, label in _endpoints()
    ]
    return {
        "prefer": eps[0]["label"] if eps else None,
        "endpoints": eps,
        "llm_fallback": GATEWAY,
        "llm_model": FALLBACK_MODEL,
        "force_cloud": _force_cloud(),
    }


def _post_json(url: str, body: dict, headers: dict, timeout: float = 30) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={**headers, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _post_jev(state: Any, questions: dict) -> tuple[dict, str]:
    """Try Magpie gateway then optional TypeSafe cloud. Returns (raw, label)."""
    errors: list[str] = []
    for url, key, model, label in _endpoints():
        try:
            raw = _post_json(
                url,
                {"model": model, "state": state, "questions": questions},
                {"Authorization": f"Bearer {key}"},
                timeout=30,
            )
            return raw, label
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read()[:180].decode(errors="replace")
            except Exception:
                pass
            errors.append(f"{label}:HTTP {e.code} {detail}")
        except Exception as e:
            errors.append(f"{label}:{type(e).__name__}:{str(e)[:120]}")
    if not _endpoints():
        raise RuntimeError("no_jev_endpoint")
    raise RuntimeError("; ".join(errors)[:300] or "jev_failed")


def _llm_json(prompt: str) -> dict:
    body = {
        "model": FALLBACK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
    }
    key = _magpie_key()
    raw = _post_json(
        GATEWAY,
        body,
        {"Authorization": f"Bearer {key}"},
        timeout=120,
    )
    text = raw["choices"][0]["message"]["content"]
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
    if not available():
        return GateResult(False, None, 0.0, "skip", None, "no_jev_endpoint")
    try:
        raw, label = _post_jev(state, {"g": q})
        ans = raw.get("answers", {}).get("g", {})
        p = float(ans.get("noul", 0))
        conf = abs(p - 0.5) * 2
        if conf < MIN_CONF:
            return GateResult(False, None, conf, "jev", raw, "low_confidence")
        return GateResult(True, p >= NOUL_YES, conf, f"jev:{label}", raw)
    except Exception as e:
        return GateResult(False, None, 0.0, "error", None, str(e)[:200])


def choice(state: Any, instructions: str, criteria: dict[str, str | None]) -> GateResult:
    q = {"type": "choice", "instructions": instructions, "criteria": criteria}
    if not available():
        return GateResult(False, None, 0.0, "skip", None, "no_jev_endpoint")
    try:
        raw, label = _post_jev(state, {"g": q})
        ans = raw.get("answers", {}).get("g", {})
        conf = float(ans.get("confidence") or 0)
        val = ans.get("choice")
        if conf < MIN_CONF:
            return GateResult(False, val, conf, "jev", raw, "low_confidence")
        return GateResult(True, val, conf, f"jev:{label}", raw)
    except Exception as e:
        return GateResult(False, None, 0.0, "error", None, str(e)[:200])


def _jev_ok(r: GateResult) -> bool:
    return r.ok and (r.source == "jev" or str(r.source).startswith("jev:"))


def should_recall(cwd: str, first_message: str, projects: list[str]) -> GateResult:
    state = {"cwd": cwd or "", "message": (first_message or "")[:2000], "projects": projects}
    r = noul(
        state,
        "Should the agent recall project memory before answering? Yes if the task touches an existing project, prior decisions, or known pitfalls.",
        true_c="Task needs prior project memory",
        false_c="Greeting, unrelated, or fully self-contained",
    )
    if _jev_ok(r):
        return r
    if r.source == "jev" and r.error == "low_confidence":
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
        return GateResult(True, True, 0.4, "llm", None, f"fallback_default_yes:{e}"[:120])


def match_project(cwd: str, message: str, projects: list[str]) -> GateResult:
    if not projects:
        return GateResult(True, None, 1.0, "skip", None)
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
    if (r.source == "jev" or str(r.source).startswith("jev:")) and (not r.ok or r.value == "none"):
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
    if r.source in ("skip", "error") or r.error == "low_confidence" or str(r.source).startswith("jev"):
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
