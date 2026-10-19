from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hinddian import notes as N
from hinddian.config import get_settings

MCP = "agent-token"
DASH = "dashboard-token"


@pytest.fixture
def client(vault, monkeypatch, tmp_path):
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("HINDDIAN_MCP_TOKEN", MCP)
    monkeypatch.setenv("AUTH_TOKEN", DASH)
    monkeypatch.setenv("HINDSIGHT_BASE_URL", "http://127.0.0.1:9")  # unreachable → local fallback
    monkeypatch.delenv("HINDDIAN_ALLOW_NO_AUTH", raising=False)
    get_settings.cache_clear()
    from hinddian.api import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def rpc(c, method, params=None, token=MCP):
    return c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                  headers={"Authorization": f"Bearer {token}"})


def agent(token=MCP):
    return {"Authorization": f"Bearer {token}"}


def dash(token=DASH):
    return {"Authorization": f"Bearer {token}", "X-Hinddian": "1"}


def test_mcp_requires_agent_token(client):
    assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
    assert rpc(client, "ping", token="nope").status_code == 403
    assert rpc(client, "ping").json()["result"] == {}


def test_dashboard_token_cannot_be_used_as_agent_and_vice_versa(client):
    assert rpc(client, "ping", token=DASH).status_code == 403
    assert client.get("/api/corrections", headers=agent()).status_code == 403


def test_agent_cannot_self_approve(client):
    r = rpc(client, "tools/call", {"name": "upsert_note", "arguments": {
        "action": "add", "type": "decision", "project": "P", "title": "D", "user_confirmed": True, "_from_dashboard": True}})
    assert '"suggested"' in r.json()["result"]["content"][0]["text"]
    cid = N.list_corrections()[0]["id"]
    # the old agent-side approval routes are gone
    assert client.post(f"/api/memory/corrections/{cid}/approve", headers=agent()).status_code in (404, 405)
    # the dashboard route refuses the agent token
    assert client.post(f"/api/corrections/{cid}/approve", headers={**agent(), "X-Hinddian": "1"}).status_code == 403
    assert N.list_notes(project="P", type_="decision") == []
    # the human can
    r = client.post(f"/api/corrections/{cid}/approve", headers=dash())
    assert r.status_code == 200 and r.json()["ok"]
    assert len(N.list_notes(project="P", type_="decision")) == 1


def test_dashboard_header_from_proxy(client):
    assert client.get("/api/corrections", headers={"X-Hinddian-Dashboard": DASH}).status_code == 200
    assert client.post("/api/corrections/x/approve", headers={"X-Hinddian-Dashboard": DASH}).status_code == 403  # csrf


def test_equal_tokens_refused(client, monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", MCP)
    get_settings.cache_clear()
    assert client.get("/api/corrections", headers=agent()).status_code == 503


def test_missing_tokens_fail_closed(client, monkeypatch):
    monkeypatch.delenv("HINDDIAN_MCP_TOKEN")
    monkeypatch.delenv("AUTH_TOKEN")
    get_settings.cache_clear()
    assert rpc(client, "ping").status_code == 503
    assert client.get("/api/corrections").status_code == 503


def test_recall_falls_back_to_local_search(client):
    N.upsert_note({"action": "add", "type": "lesson", "project": "P", "title": "部署门禁", "scene": "API 主机"})
    r = client.post("/api/memory/recall", json={"query": "部署"}, headers=agent())
    body = r.json()
    assert body["via"] == "local-fallback"
    assert body["results"][0]["title"] == "部署门禁"


def test_push_draft_rest(client):
    r = client.post("/api/memory/push_draft", json={"project": "P", "title": "t", "body": "b", "session_id": "s1"}, headers=agent())
    assert r.json()["upsert"] is True


def test_health_is_public_and_minimal(client):
    assert set(client.get("/api/health").json()) == {"ok", "service", "version"}


def test_recall_hindsight_contract(client, monkeypatch):
    """Body matches Hindsight's RecallRequest; results are filtered on note metadata, not the
    top-level `type` (which is Hindsight's fact kind)."""
    import httpx

    from hinddian import memory_mcp

    seen = []

    def handler(request):
        seen.append((request.url.path, __import__("json").loads(request.content)))
        return httpx.Response(200, json={"results": [
            {"id": "1", "text": "a", "type": "world", "metadata": {"type": "lesson", "project": "P"}},
            {"id": "2", "text": "b", "type": "world", "metadata": {"type": "lesson", "project": "Q"}},
        ]})

    real = httpx.Client
    monkeypatch.setattr(memory_mcp.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    memory_mcp._recall_path.clear()
    r = client.post("/api/memory/recall", json={"query": "部署", "project": "P", "type": "lesson"}, headers=agent()).json()
    assert r["via"] == "hindsight"
    assert [x["id"] for x in r["results"]] == ["1"]
    path, body = seen[0]
    assert path == "/v1/default/banks/hinddian/memories/recall"
    assert body == {"query": "部署", "budget": "mid", "tags": ["source:obsidian", "type:lesson", "project:P"], "tags_match": "all_strict"}


def _mock_hindsight(monkeypatch, results):
    import httpx

    from hinddian import memory_mcp

    seen = []

    def handler(request):
        seen.append(__import__("json").loads(request.content))
        return httpx.Response(200, json={"results": results})

    real = httpx.Client
    monkeypatch.setattr(memory_mcp.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    memory_mcp._recall_path.clear()
    return seen


def test_project_recall_includes_tips_and_one_row_per_note(client, monkeypatch):
    seen = _mock_hindsight(monkeypatch, [
        {"id": "f1", "document_id": "proj/P/lesson/a", "text": "a1", "metadata": {"type": "lesson", "project": "P"}, "scores": {"reranker": 0.7}},
        {"id": "f2", "document_id": "tip/t", "text": "t1", "metadata": {"type": "tip"}, "scores": {"reranker": 0.6}},
        {"id": "f3", "document_id": "proj/P/lesson/a", "text": "a2", "metadata": {"type": "lesson", "project": "P"}, "scores": {"reranker": 0.9}},
    ])
    r = client.post("/api/memory/recall", json={"query": "部署", "project": "P"}, headers=agent()).json()
    assert seen[0]["tags"] == ["project:P", "type:tip"] and seen[0]["tags_match"] == "any_strict"
    assert [x["document_id"] for x in r["results"]] == ["proj/P/lesson/a", "tip/t"]
    first = r["results"][0]
    assert first["text"] == "a1" and first["facts"] == 2 and first["scores"]["reranker"] == 0.9


def test_auto_verdict_merges_into_the_most_similar_note(client, monkeypatch):
    from hinddian import jev, memory_mcp

    N.upsert_note({"action": "add", "type": "lesson", "project": "P", "title": "日志轮转", "practice": "logrotate"})
    gate = N.upsert_note({"action": "add", "type": "lesson", "project": "P", "title": "部署前先跑门禁", "practice": "gate.sh"})
    seen = {}

    def verdict(digest, cands):
        seen["cands"] = cands
        return jev.GateResult(True, "update", 0.9, "jev:local", {"answers": {"g": {"choice": "update"}}})

    monkeypatch.setattr(memory_mcp.jev, "write_verdict", verdict)
    r = memory_mcp.call_tool("upsert_note", {"action": "add", "type": "lesson", "project": "P", "title": "部署门禁要先跑",
                                             "practice": "部署前 gate.sh --strict", "auto_verdict": True})
    assert seen["cands"][0]["id"] == gate["id"] and "practice" in seen["cands"][0]
    assert r["action"] == "update" and r["id"] == gate["id"]
    assert N.get_note(gate["id"])["practice"] == "部署前 gate.sh --strict"
    assert len(N.list_notes(project="P")) == 2


# ------------------------------------------------------------------ dashboard v2
@pytest.fixture
def dash_client(client, monkeypatch, tmp_path, vault):
    base = tmp_path / "base"
    (base / "drafts" / "my-app").mkdir(parents=True)
    for i in range(3):
        (base / "drafts" / "my-app" / f"session-{i}.md").write_text("---\ntitle: s\n---\n", encoding="utf-8")
    monkeypatch.setenv("HB_BASE", str(base))
    monkeypatch.setenv("HC_VAULT", str(vault))
    from hinddian import classify_remote

    classify_remote.invalidate()
    (vault / "项目" / "my-app").mkdir(parents=True)
    (vault / "项目" / "my-app" / "README.md").write_text("---\nid: proj/my-app/readme\ntype: state\n---\n# my-app\n", encoding="utf-8")
    N.upsert_note({"action": "add", "type": "lesson", "project": "my-app", "title": "部署前先跑门禁", "practice": "gate.sh"})
    N.upsert_note({"action": "add", "type": "decision", "project": "my-app", "title": "只走 HTTPS"})  # → queued
    return client


def test_overview_counts(dash_client):
    o = dash_client.get("/api/overview", headers=dash()).json()
    assert o["vault"] == {"ok": True, "error": None, "projects": 1, "decisions": 0, "lessons": 1, "tips": 0}
    assert o["corrections"]["pending"] == 1
    assert o["drafts"]["ok"] and o["drafts"]["total"] == 3 and o["drafts"]["ready"] == 0


def test_notes_list_hides_hub_pages_and_searches(dash_client):
    rows = dash_client.get("/api/notes", headers=dash()).json()
    assert [r["type"] for r in rows] == ["lesson"]
    hits = dash_client.get("/api/notes", params={"q": "门禁"}, headers=dash()).json()
    assert hits and hits[0]["title"] == "部署前先跑门禁"
    assert dash_client.get("/api/note", params={"id": "nope"}, headers=dash()).status_code == 404
    nid = rows[0]["id"]
    assert dash_client.get("/api/note", params={"id": nid}, headers=dash()).json()["practice"] == "gate.sh"


def test_dashboard_recall_and_gate(dash_client):
    r = dash_client.post("/api/recall", json={"query": "部署门禁"}, headers=dash()).json()
    assert r["via"] == "local-fallback" and r["results"]
    g = dash_client.get("/api/gate", headers=dash()).json()
    assert g["projects"][0]["project"] == "my-app" and g["projects"][0]["state"] == "accumulating"
    assert dash_client.post("/api/gate/..%2Fx/approve", headers={**dash()}).status_code in (400, 404)


def test_dashboard_needs_auth_but_static_does_not(dash_client):
    assert dash_client.get("/api/overview").status_code == 401
    assert dash_client.get("/api/notes", headers=agent()).status_code == 403
    assert dash_client.get("/static/manifest.webmanifest").status_code == 200
    assert dash_client.get("/", headers=dash()).status_code == 200
