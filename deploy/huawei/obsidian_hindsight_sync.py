#!/usr/bin/env python3
"""Obsidian -> Hindsight sync (runs on Huawei, next to Hindsight API).

Pulls the atomic-note export from DMIT (`ssh dmit-vps hinddian-batch export-notes --json`), then:
  new / changed active note  -> retain (document_id = frontmatter id, upsert)
  deleted or superseded note -> DELETE document
State: /var/lib/hinddian/hindsight-sync.json ; status for dashboard: /var/lib/hinddian/hindsight-sync-status.json
Secrets are read from /opt/hindsight/secrets.env at runtime and never printed.
"""
import json, os, pathlib, subprocess, sys, time, urllib.parse, urllib.request, urllib.error, datetime as dt

SECRETS = pathlib.Path(os.environ.get("HS_SECRETS", "/opt/hindsight/secrets.env"))
STATE = pathlib.Path(os.environ.get("HS_STATE", "/var/lib/hinddian/hindsight-sync.json"))
STATUS = STATE.with_name("hindsight-sync-status.json")
SSH_HOST = os.environ.get("HS_SSH_HOST", "dmit-vps")
MAX_RETAIN = int(os.environ.get("HS_MAX_RETAIN", "200"))

def secrets():
    out = {}
    for line in SECRETS.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1); out[k.strip()] = v.strip().strip('"').strip("'")
    return out

S = secrets()
BASE = S.get("HINDSIGHT_API_BASE", "http://127.0.0.1:8888").rstrip("/")
BANK = S.get("HINDSIGHT_BANK_ID", "wanwan")

def api(method, path, body=None, timeout=600):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=None if body is None else json.dumps(body, ensure_ascii=False).encode())
    req.add_header("Authorization", f"Bearer {S['HINDSIGHT_API_TENANT_API_KEY']}")
    if body is not None: req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(); return json.loads(raw) if raw else {}

def doc_path(doc_id): return f"/v1/default/banks/{BANK}/documents/{urllib.parse.quote(doc_id, safe='')}"

def retain(n):
    tags = [f"type:{n['type']}", "source:obsidian"] + ([f"project:{n['project']}"] if n["project"] and n["project"] != "global" else [])
    body = {"async": False, "items": [{"content": n["text"], "context": n["title"], "document_id": n["id"], "tags": tags,
            "metadata": {"title": n["title"], "path": n["path"] + ".md", "project": n["project"], "type": n["type"], "source": "obsidian"}}]}
    return api("POST", f"/v1/default/banks/{BANK}/memories", body)

def forget(doc_id):
    try: api("DELETE", doc_path(doc_id))
    except urllib.error.HTTPError as e:
        if e.code != 404: raise

def main():
    dry = "--dry-run" in sys.argv
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", SSH_HOST, "hinddian-batch", "export-notes", "--json"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode: sys.exit("export failed: " + r.stderr[-300:])
    notes = {n["id"]: n for n in json.loads(r.stdout)}
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    want = {i: n for i, n in notes.items() if n["status"] == "active"}
    todo = [n for i, n in want.items() if state.get(i) != n["sha"]][:MAX_RETAIN]
    gone = [i for i in state if i not in want]
    stats = {"retained": 0, "forgotten": 0, "errors": [], "notes": len(want)}
    for n in todo:
        if dry: print("retain", n["id"]); continue
        try: retain(n); state[n["id"]] = n["sha"]; stats["retained"] += 1
        except Exception as e: stats["errors"].append(f"{n['id']}: {str(e)[:120]}")
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    for i in gone:
        if dry: print("forget", i); continue
        try: forget(i); state.pop(i, None); stats["forgotten"] += 1
        except Exception as e: stats["errors"].append(f"forget {i}: {str(e)[:120]}")
    if not dry:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
        STATUS.write_text(json.dumps({"at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "synced": len(state),
                                      "pending": len([1 for i, n in want.items() if state.get(i) != n["sha"]]), **stats}, ensure_ascii=False))
    print(json.dumps(stats, ensure_ascii=False))

if __name__ == "__main__":
    main()
