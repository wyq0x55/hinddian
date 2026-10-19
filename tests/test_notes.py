from __future__ import annotations

from hinddian import notes as N


def _text(vault, res):
    return (vault / (res["path"] + ".md")).read_text(encoding="utf-8")


def _lesson(title, **kw):
    return N.upsert_note({"action": "add", "type": "lesson", "project": "P", "title": title, "scene": "s", **kw})


# ------------------------------------------------------------------ links
def test_update_keeps_related_links(vault):
    a = _lesson("A")
    b = _lesson("B", related=[a["id"]])
    assert "[[项目/P/经验/A|A]]" in _text(vault, b)
    N.upsert_note({"action": "update", "id": b["id"], "practice": "p2"})
    t = _text(vault, b)
    assert 'related: ["[[项目/P/经验/A|A]]"]' in t
    assert "p2" in t


def test_supersede_banner_survives_rerender(vault):
    old = _lesson("Old")
    new = N.upsert_note({"action": "supersede", "type": "lesson", "project": "P", "title": "New", "supersedes": [old["id"]]})
    assert "已被 [[项目/P/经验/New|New]] 取代" in _text(vault, old)
    N.upsert_note({"action": "update", "id": old["id"], "practice": "touched"})
    t = _text(vault, old)
    assert "已被 [[项目/P/经验/New|New]] 取代" in t
    assert "status: superseded" in t
    assert N.get_note(old["id"])["superseded_by"] == new["id"]


def test_id_and_path_collisions_get_suffix(vault):
    a = _lesson("Same")
    b = _lesson("Same")
    assert a["id"] != b["id"] and a["path"] != b["path"]
    assert len(N.list_notes(project="P")) == 2


# ------------------------------------------------------------------ gate
def test_agent_cannot_write_decision_with_flags(vault):
    for flags in ({"_from_dashboard": True}, {"user_confirmed": True}, {"face_correction": True}, {"confirmed": True}):
        r = N.upsert_note({"action": "add", "type": "decision", "project": "P", "title": "D", **flags})
        assert r["action"] == "suggested", flags
    assert N.list_notes(project="P", type_="decision") == []
    q = N.list_corrections()
    assert len(q) == 4
    assert all("_from_dashboard" not in c["payload"] for c in q)


def _approved_decision(vault):
    N.upsert_note({"action": "add", "type": "decision", "project": "P", "title": "D"})
    cid = N.list_corrections()[0]["id"]
    r = N.decide_correction(cid, approve=True)
    assert r["ok"] and r["result"]["gated"] == "dashboard"
    return r["result"]["id"]


def test_dashboard_approval_writes_decision(vault):
    did = _approved_decision(vault)
    assert N.get_note(did)["type"] == "decision"
    assert N.decide_correction(N.list_corrections(status="all")[0]["id"], approve=True)["error"] == "not_pending"


def test_decision_note_cannot_be_relabeled_or_retired_by_agent(vault):
    did = _approved_decision(vault)
    before = N.get_note(did)["text"]
    for payload in (
        {"action": "update", "id": did, "type": "lesson", "practice": "hijack"},
        {"action": "obsolete", "id": did, "type": "tip"},
        {"action": "supersede", "type": "lesson", "project": "P", "title": "X", "supersedes": [did]},
    ):
        assert N.upsert_note(payload)["action"] == "suggested", payload
    assert N.get_note(did)["text"] == before
    assert N.get_note(did)["status"] == "active"


def test_lessons_and_tips_write_directly(vault):
    assert _lesson("L")["gated"] == "auto"
    t = N.upsert_note({"action": "add", "type": "preference", "title": "Pref"})
    assert t["gated"] == "auto" and t["id"].startswith("tip/")


def test_hard_delete_forbidden(vault):
    assert N.upsert_note({"action": "delete", "id": "x"})["error"] == "hard_delete_forbidden"


# ------------------------------------------------------------------ paths
def test_project_traversal_stays_in_vault(vault, tmp_path):
    r = N.upsert_note({"action": "add", "type": "lesson", "project": "../../escape", "title": "X"})
    assert r["ok"]
    assert (vault / (r["path"] + ".md")).is_file()
    assert not (tmp_path / "escape").exists()


def test_push_draft_sanitises(vault, tmp_path):
    r = N.push_draft(project="../x", title="t\nstatus: x", body="b", meta={"jev_source": "a\nstatus: evil", "bad key": "1", "session_id": "../../s"})
    p = r["path"]
    assert p.startswith(str(N.DRAFTS))
    text = open(p, encoding="utf-8").read()
    head = text.split("\n---\n")[0]
    assert "\nstatus:" not in head
    assert "bad key" not in head
    assert N.push_draft(project="holdout", title="t", body="b")["project"] == N.UNKNOWN_PROJECT


def test_routing_project_rejects_traversal(vault, tmp_path):
    (tmp_path / "README.md").write_text("## 当前状态\nsecret\n", encoding="utf-8")
    assert "secret" not in N.routing_project("../..")["current_state"]


# ------------------------------------------------------------------ search
def test_search_notes_chinese(vault):
    N.upsert_note({"action": "add", "type": "lesson", "project": "P", "title": "部署门禁", "scene": "API 主机 部署"})
    _lesson("无关")
    hits = N.search_notes("部署时注意什么")
    assert hits and hits[0]["title"] == "部署门禁"
