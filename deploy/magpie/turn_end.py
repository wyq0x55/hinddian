"""TurnEnd: classify this turn via Magpie-local Jev (preferred), then push_draft to hinddian."""
import json, os, sys
from pathlib import Path

# Magpie-local Jev module shipped beside this hook
sys.path.insert(0, str(Path(__file__).resolve().parent))

url = os.environ.get("HINDDIAN_MEMORY_URL", "http://124.70.90.224/hinddian").rstrip("/")
token = os.environ.get("HINDDIAN_MCP_TOKEN") or os.environ.get("HINDSIGHT_API_KEY") or ""
turn = os.environ.get("MAGPIE_TURN_TEXT") or ""
if not turn.strip() and not sys.stdin.isatty():
    turn = sys.stdin.read(12000)

def req(method, path, body=None, timeout=45):
    import urllib.request
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

def classify_local(turn_text: str, projects: list) -> dict | None:
    """Use Magpie gateway System One on this host (no cloud TypeSafe key)."""
    try:
        import jev
        r = jev.classify_turn(turn_text, projects)
        return {
            "ok": r.ok,
            "value": r.value,
            "confidence": r.confidence,
            "source": r.source,
            "error": r.error,
        }
    except Exception as e:
        print(f"turn-end local Jev skipped: {type(e).__name__}: {str(e)[:120]}")
        return None

def main():
    if not (turn or "").strip():
        return
    projects: list = []
    try:
        g = req("GET", "/api/memory/routing/global", timeout=12)
        projects = [p.get("name") for p in (g.get("projects") or []) if p.get("name")]
    except Exception:
        pass
    klass = classify_local(turn[:8000], projects)
    if klass is None:
        try:
            klass = req("POST", "/api/memory/gates/classify_turn", {"turn": turn[:8000]})
        except Exception as e:
            print(f"turn-end classify failed: {e}")
            return
    val = klass.get("value") or {}
    if not isinstance(val, dict) or not val.get("keep"):
        return
    title = val.get("title") or val.get("summary") or "turn-draft"
    typ = val.get("type") or "lesson"
    project = val.get("project") or "通用-未定"
    scene = val.get("scene") or ""
    practice = val.get("practice") or ""
    reason = val.get("reason") or ""
    nl = chr(10)
    block = f"### {title}{nl}- 场景：{scene}{nl}- 做法：{practice}{nl}- 理由：{reason}{nl}"
    if typ == "decision":
        body = f"## DECISIONS{nl}{block}{nl}## LESSONS{nl}"
    else:
        body = f"## DECISIONS{nl}{nl}## LESSONS{nl}{block}"
    payload = {
        "project": project,
        "title": title,
        "body": body,
        "type": typ,
        "confidence": klass.get("confidence"),
        "origin": f"turn-end:{klass.get('source')}",
    }
    try:
        out = req("POST", "/api/memory/push_draft", payload, timeout=30)
        print(json.dumps(out, ensure_ascii=False)[:300])
    except Exception as e:
        print(f"push_draft failed: {e}")

if __name__ == "__main__":
    main()
