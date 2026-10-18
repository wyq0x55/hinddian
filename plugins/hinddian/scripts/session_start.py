"""SessionStart: finalize previous session buffer; inject routing; Jev should-recall."""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract
import finalize
import session_buf

url = os.environ.get("HINDDIAN_MEMORY_URL", "http://124.70.90.224/hinddian").rstrip("/")
token = os.environ.get("HINDDIAN_MCP_TOKEN") or os.environ.get("HINDSIGHT_API_KEY") or ""


def req(method, path, body=None, timeout=12):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode()
    r = urllib.request.Request(url + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read())


def should_recall_local(cwd_: str, message: str, projects: list):
    try:
        import jev

        r = jev.should_recall(cwd_, message, projects)
        return {
            "ok": r.ok,
            "should_recall": r.value,
            "confidence": r.confidence,
            "source": r.source,
            "error": r.error,
        }
    except Exception as e:
        print(f"session-start local Jev skipped: {type(e).__name__}: {str(e)[:100]}")
        return None


def main():
    stdin = ""
    if not sys.stdin.isatty():
        stdin = sys.stdin.read(50000)
    payload = extract.parse_hook_payload(stdin)
    cwd = payload.get("cwd") or os.environ.get("MAGPIE_CWD") or os.environ.get("PWD") or ""
    msg = payload.get("first_message") or os.environ.get("MAGPIE_FIRST_MESSAGE") or os.environ.get("MAGPIE_PROMPT") or ""
    new_sid = session_buf.stable_session_id(payload.get("session_id"), cwd, msg[:80] if msg else "new")

    # Flush previous session drafts (Magpie has no portable session-end)
    flushed = finalize.finalize_idle_and_others(current_sid=new_sid)
    for fr in flushed:
        src = fr.get("source") or fr.get("skipped")
        print(f"hinddian finalize session={fr.get('session_id')} source={src} reason={fr.get('reason')}")

    try:
        global_rt = req("GET", "/api/memory/routing/global")
    except Exception as e:
        print(f"hinddian-memory: routing unavailable ({e}). Prefer MCP hinddian-memory if tools are listed.")
        return
    projects = global_rt.get("projects") or []
    plist = "; ".join(
        f"{p.get('name')}({p.get('decisions', 0)}d/{p.get('lessons', 0)}l)" for p in projects
    ) or "none"
    print("hinddian-memory MCP (not raw Hindsight). Stable prefix — do not rewrite.")
    print(f"Projects: {plist}")
    print(f"Guidance: {global_rt.get('guidance', '')}")
    print("Memory write: session-bucket (one draft/session after Jev keep). Threshold counts session drafts.")
    proj = None
    blob = (cwd + " " + msg).lower()
    for p in projects:
        n = p.get("name") or ""
        if n and n.lower() in blob:
            proj = n
            break
    names = [p.get("name") for p in projects if p.get("name")]
    gate = should_recall_local(cwd, msg, names)
    if gate is None:
        try:
            gate = req("POST", "/api/memory/gates/should_recall", {"cwd": cwd, "message": msg}, timeout=20)
        except Exception:
            gate = {"should_recall": True, "source": "fallback"}
    if proj:
        try:
            pr = req("GET", "/api/memory/routing/project/" + urllib.parse.quote(proj))
            print(f"PROJECT {pr.get('project')} | state: {(pr.get('current_state') or '')[:240]}")
            print(f"when_to_recall: {pr.get('when_to_recall', '')}")
            print(f"decisions: {len(pr.get('decisions') or [])} lessons: {len(pr.get('lessons') or [])}")
        except Exception:
            pass
    src = gate.get("source", "")
    if gate.get("should_recall"):
        print(
            f"Gate should_recall=YES (source={src}). If task needs memory: MCP routing_project then "
            "recall(project=…). Put recall AFTER this prefix. Never Hindsight retain; write via "
            "upsert_note or session-finalize drafts only. No secrets in notes."
        )
    else:
        print(
            f"Gate should_recall=NO (source={src}). Skip recall unless the user asks about prior "
            "decisions. No secrets in notes."
        )


if __name__ == "__main__":
    main()
