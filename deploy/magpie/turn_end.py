import json, os, sys, urllib.request

url = os.environ.get("HINDDIAN_MEMORY_URL", "http://124.70.90.224/hinddian").rstrip("/")
token = os.environ.get("HINDDIAN_MCP_TOKEN") or os.environ.get("HINDSIGHT_API_KEY") or ""
turn = os.environ.get("MAGPIE_TURN_TEXT") or ""
if not turn.strip() and not sys.stdin.isatty():
    turn = sys.stdin.read(12000)

def req(method, path, body=None, timeout=45):
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

def main():
    if not (turn or "").strip():
        return
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
