from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hinddian import draft_store, jev, jev_log, note_format as nf, session_finalize
from hinddian.api import app
from hinddian.config import get_settings

COLLECTOR = "collector-token"
DASH = "dashboard-token"


@pytest.fixture
def client(vault, monkeypatch):
    monkeypatch.setenv("HINDDIAN_MCP_TOKEN", COLLECTOR)
    monkeypatch.setenv("AUTH_TOKEN", DASH)
    monkeypatch.setenv("HINDDIAN_ALLOW_NO_AUTH", "false")
    get_settings.cache_clear()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def collector(token=COLLECTOR):
    return {"Authorization": f"Bearer {token}"}


def dashboard():
    return {"Authorization": f"Bearer {DASH}"}


def test_collector_requires_token_and_channels_are_separate(client):
    uri = "/api/memory/finalize"
    assert client.post(uri, json={}).status_code == 401
    assert client.post(uri, json={}, headers=collector("wrong")).status_code == 403
    assert client.post(uri, json={}, headers=dashboard()).status_code == 403
    assert client.get("/api/drafts", headers=collector()).status_code == 403


def test_dashboard_header_from_proxy(client):
    assert client.get("/api/overview", headers={"X-Hinddian-Dashboard": DASH}).status_code == 200


def test_equal_tokens_refused(client, monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", COLLECTOR)
    get_settings.cache_clear()
    assert client.get("/api/overview", headers=collector()).status_code == 503


def test_missing_tokens_fail_closed(client, monkeypatch):
    monkeypatch.delenv("HINDDIAN_MCP_TOKEN")
    monkeypatch.delenv("AUTH_TOKEN")
    get_settings.cache_clear()
    assert client.post("/api/memory/finalize", json={}).status_code == 503
    assert client.get("/api/overview").status_code == 503


def test_push_draft_rest(client, tmp_path):
    response = client.post("/api/memory/push_draft", headers=collector(),
                           json={"project": "P", "title": "t", "body": "b", "session_id": "s1"})
    assert response.json()["upsert"] is True
    assert (tmp_path / "drafts/P/session-s1.md").is_file()


def test_health_is_public_and_minimal(client):
    assert set(client.get("/api/health").json()) == {"ok", "service", "version"}


@pytest.fixture
def dash_client(client, vault):
    for index in range(3):
        draft_store.save_payload({"project": "my-app", "session_id": str(index)})
    for kind in ("lesson", "decision"):
        rel = f"项目/my-app/{nf.FOLDER[kind]}/{kind}"
        note = nf.new_note(id=f"proj/my-app/{kind}/test", path=rel, type=kind, project="my-app", title=kind)
        nf.write_note_file(vault, rel, nf.render(note, {}, today="2026-11-23"))
    return client


def test_overview_counts(dash_client):
    data = dash_client.get("/api/overview", headers=dashboard()).json()
    assert data["vault"] == {"ok": True, "error": None, "projects": 1, "decisions": 1, "lessons": 1, "tips": 0}
    assert data["drafts"] == {"ok": True, "error": None, "total": 3, "processed": 0}
    batch = dash_client.get("/api/batch", headers=dashboard()).json()
    assert batch["projects"] == [{"project": "my-app", "drafts": 3, "processed": 0}]


def test_dashboard_lists_drafts(dash_client):
    draft_store.save_payload({"project": "my-app", "title": "一次会话", "body": "body here",
                              "session_id": "s-dash", "jev_source": "none"})
    rows = dash_client.get("/api/drafts", params={"status": "pending"}, headers=dashboard()).json()
    row = next(row for row in rows if row["session_id"] == "s-dash")
    assert row["title"] == "一次会话"
    detail = dash_client.get("/api/draft", params={"id": row["id"]}, headers=dashboard()).json()
    assert "body here" in detail["body"]
    assert dash_client.get("/api/draft", params={"id": "nope/x.md"}, headers=dashboard()).status_code == 404
    assert dash_client.get("/api/drafts").status_code == 401


def test_dashboard_needs_auth_but_static_does_not(dash_client):
    assert dash_client.get("/api/overview").status_code == 401
    assert dash_client.get("/api/drafts", headers=collector()).status_code == 403
    assert dash_client.get("/static/manifest.webmanifest").status_code == 200
    assert dash_client.get("/", headers=dashboard()).status_code == 200


@pytest.mark.parametrize(("method", "uri"), [
    ("POST", "/mcp"), ("GET", "/.well-known/oauth-authorization-server"),
    ("POST", "/api/memory/recall"), ("GET", "/api/memory/routing/global"),
    ("GET", "/api/memory/notes"), ("POST", "/api/memory/upsert_note"),
    ("POST", "/api/memory/suggest_correction"), ("GET", "/api/notes"), ("GET", "/api/note"),
    ("POST", "/api/gate/P/approve"), ("GET", "/api/corrections"),
    ("POST", "/api/memory/gates/classify_turn"),
])
def test_removed_routes_are_closed(client, method, uri):
    assert client.request(method, uri, headers=dashboard()).status_code == 404


def test_jev_report_validates_appends_and_shows_on_dashboard(client, tmp_path, monkeypatch):
    log = tmp_path / "jev.jsonl"
    monkeypatch.setenv("HINDDIAN_JEV_LOG", str(log))
    url = "/api/memory/gates/report"
    assert client.post(url, json={"session_id": "s"}).status_code == 401
    assert client.post(url, json={"session_id": "s"}, headers=dashboard()).status_code == 403
    for bad in ({}, {"session_id": "s", "keep": "yes"}, {"session_id": "s", "event": "x"},
                {"session_id": "s", "error": "x" * 5000}):
        assert client.post(url, json=bad, headers=collector()).status_code == 422
    record = {"session_id": "s1", "host": "mac", "project": "P", "jev_source": "none", "keep": None,
              "error": "jev_unavailable token=abc123", "turn_count": 3, "pushed": False, "turn": "secret text"}
    assert client.post(url, json=record, headers=collector()).json() == {"ok": True}
    assert client.post(url, json={**record, "session_id": "s2", "jev_source": "jev:local", "keep": False, "error": None},
                       headers=collector()).status_code == 200
    raw = log.read_text()
    assert "secret text" not in raw and "abc123" not in raw and raw.count("\n") == 2
    assert client.get("/api/jev-decisions", headers=collector()).status_code == 403
    data = client.get("/api/jev-decisions", headers=dashboard()).json()
    assert [row["session_id"] for row in data["items"]] == ["s2", "s1"]
    assert data["summary"]["by_source_24h"] == {"none": 1, "jev:local": 1}
    assert data["summary"]["hosts"][0]["host"] == "mac" and data["summary"]["drop_24h"] == 1


def test_jev_log_rotates(tmp_path, monkeypatch):
    monkeypatch.setenv("HINDDIAN_JEV_LOG", str(tmp_path / "j.jsonl"))
    monkeypatch.setattr(jev_log, "MAX_BYTES", 400)
    for index in range(20):
        jev_log.append(jev_log.validate({"session_id": f"s{index}"}))
    assert (tmp_path / "j.jsonl.1").exists() and (tmp_path / "j.jsonl").stat().st_size <= 400
    assert jev_log.recent(5)[0]["session_id"] == "s19"


def test_jev_backend_alias(client):
    assert client.get("/api/memory/jev-backend", headers=collector()).status_code == 200


def _fin_body(**kw):
    return {"session_id": "sf1", "cwd": "/home/test/work/my-app/src", "repo": "my-app", "client_id": "mac-mini",
            "finalize_reason": "idle", "turn_count": 2,
            "turns": [{"text": "用户: 部署前要备份\n助手: 好的 SECRETTURN\nBearer syntheticcredential"}], **kw}


def test_server_finalize_runs_jev_pushes_and_logs(client, tmp_path, monkeypatch):
    log = tmp_path / "jev.jsonl"
    monkeypatch.setenv("HINDDIAN_JEV_LOG", str(log))
    seen = {}

    def classify(text, projects, cwd):
        seen.update(text=text, cwd=cwd)
        return jev.GateResult(True, {"keep": True, "type": "lesson", "title": "部署前备份", "lesson": ["先备份"],
                                     "open_question": ["多久一次"]}, 0.9, "jev:local")

    monkeypatch.setattr(session_finalize.jev, "classify_turn", classify)
    url = "/api/memory/finalize"
    assert client.post(url, json=_fin_body()).status_code == 401
    assert client.post(url, json=_fin_body(), headers=dashboard()).status_code == 403
    assert client.post(url, json={"turns": []}, headers=collector()).status_code == 422
    assert client.post(url, json=_fin_body(turns=[{"text": "x" * 20000}] * 11), headers=collector()).status_code == 422
    result = client.post(url, json=_fin_body(), headers=collector()).json()
    assert result["outcome"] == "pushed" and result["retry"] is False and result["source"] == "jev:local"
    text = (tmp_path / "drafts/my-app/session-sf1.md").read_text()
    assert "session_id: sf1" in text and "- 先备份" in text and "OPEN QUESTIONS" in text
    assert seen["cwd"] == "src" and "SECRETTURN" in seen["text"] and "syntheticcredential" not in seen["text"]
    raw = log.read_text()
    assert "SECRETTURN" not in raw and "部署前要备份" not in raw
    item = client.get("/api/jev-decisions", headers=dashboard()).json()["items"][0]
    assert item["host"] == "mac-mini" and item["pushed"] and item["outcome"] == "pushed" and item["keep"]


def test_server_finalize_jev_down_writes_nothing_and_asks_retry(client, tmp_path, monkeypatch):
    for verdict, retry in ((jev.GateResult(False, None, 0, "none"), True),
                           (jev.GateResult(True, {"keep": True}, 0.9, "llm"), False)):
        monkeypatch.setattr(session_finalize.jev, "classify_turn", lambda *args: verdict)
        result = client.post("/api/memory/finalize", json=_fin_body(), headers=collector()).json()
        assert result["pushed"] is False and result["source"] == "none" and result["retry"] is retry
    assert not (tmp_path / "drafts").exists()
    items = client.get("/api/jev-decisions", headers=dashboard()).json()["items"]
    assert {item["outcome"] for item in items} == {"jev_unavailable", "llm_forbidden"}
    monkeypatch.setattr(session_finalize.jev, "classify_turn",
                        lambda *args: jev.GateResult(True, {"keep": False}, 0.3, "jev:cloud"))
    result = client.post("/api/memory/finalize", json=_fin_body(), headers=collector()).json()
    assert result == {**result, "outcome": "keep_false", "retry": False, "keep": False}


def test_server_pick_project():
    pick = session_finalize.pick_project
    payload = {"project": "", "repo": "", "cwd": ""}
    assert pick({**payload, "repo": "my-app-api"}, "x", ["my-app", "my-app-api"]) == "my-app-api"
    assert pick({**payload, "repo": "new-repo"}, "hinddian", ["hinddian"]) == "new-repo"
    assert pick({**payload, "cwd": "loose"}, "hinddian", ["hinddian"]) == "hinddian"
    assert pick({**payload, "project": "P"}, None, []) == "P"
    assert pick(payload, None, []) == "通用-未定"
