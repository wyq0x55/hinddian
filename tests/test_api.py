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
    monkeypatch.setenv("STATUS_DB", str(tmp_path / "db" / "s.db"))
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
    N.upsert_note({"action": "add", "type": "lesson", "project": "P", "title": "部署门禁", "scene": "华为"})
    r = client.post("/api/memory/recall", json={"query": "部署"}, headers=agent())
    body = r.json()
    assert body["via"] == "local-fallback"
    assert body["results"][0]["title"] == "部署门禁"


def test_push_draft_rest(client):
    r = client.post("/api/memory/push_draft", json={"project": "P", "title": "t", "body": "b", "session_id": "s1"}, headers=agent())
    assert r.json()["upsert"] is True


def test_health_is_public_and_minimal(client):
    assert set(client.get("/api/health").json()) == {"ok", "service", "version"}
