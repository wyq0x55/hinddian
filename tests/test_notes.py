from __future__ import annotations

from pathlib import Path

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
    b = _lesson("Same", force_new=True)
    assert a["id"] != b["id"] and a["path"] != b["path"]
    assert len(N.list_notes(project="P")) == 2


def test_chinese_titles_get_distinct_ids(vault):
    a = _lesson("部署前先跑门禁")
    b = _lesson("日志轮转")
    assert a["id"] != b["id"] and not a["id"].endswith("/note")
    assert a["id"].startswith("proj/P/lesson/n-")


def test_agent_add_flags_near_duplicates(vault):
    a = _lesson("部署前先跑门禁脚本", practice="每次部署前跑 gate.sh")
    r = _lesson("部署前要先跑门禁", practice="部署前跑 gate.sh")
    assert r["ok"] is False and r["error"] == "similar_exists"
    assert r["candidates"][0]["id"] == a["id"]
    assert _lesson("日志轮转", practice="logrotate 每天")["ok"]          # unrelated → written
    assert _lesson("部署前要先跑门禁", practice="部署前跑 gate.sh", force_new=True)["ok"]
    # the dashboard (trusted) path is never blocked
    assert N.upsert_note({"action": "add", "type": "lesson", "project": "P", "title": "部署前先跑门禁脚本"}, trusted=True)["ok"]


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


def test_project_search_includes_global_tips(vault):
    _lesson("部署门禁", practice="gate.sh")
    N.upsert_note({"action": "add", "type": "tip", "title": "部署前清缓存", "practice": "rm -rf .cache"})
    N.upsert_note({"action": "add", "type": "lesson", "project": "Q", "title": "部署别的项目", "scene": "s"})
    hits = {h["type"] for h in N.search_notes("部署", project="P")}
    assert hits == {"lesson", "tip"}
    assert all(h["project"] != "Q" for h in N.search_notes("部署", project="P"))
    assert {h["type"] for h in N.search_notes("部署", project="P", type_="lesson")} == {"lesson"}


def test_list_and_get_drafts(vault, tmp_path):
    r = N.push_draft(
        project="ut-agent",
        title="会话记忆状态",
        body="- 记住部署前跑门禁\n- 不要写密钥",
        meta={"session_id": "codex-memory-state-20261019", "jev_source": "local", "origin": "session-finalize"},
    )
    assert r["ok"]
    pending = N.list_drafts(status="pending")
    assert len(pending) == 1
    row = pending[0]
    assert row["project"] == "ut-agent"
    assert row["title"] == "会话记忆状态"
    assert row["session_id"] == "codex-memory-state-20261019"
    assert row["jev_source"] == "local"
    assert row["status"] == "pending"
    assert "门禁" in row["snippet"]
    got = N.get_draft(row["id"])
    assert got and got["body"] and "门禁" in got["body"]
    assert N.get_draft("../escape/x") is None
    assert N.list_drafts(project="other") == []

    # simulate batch move to processed/
    src = Path(r["path"])
    dest_dir = N.PROCESSED / "ut-agent"
    dest_dir.mkdir(parents=True)
    dest = dest_dir / src.name
    src.replace(dest)
    assert N.list_drafts(status="pending") == []
    done = N.list_drafts(status="processed")
    assert len(done) == 1 and done[0]["status"] == "processed"
    assert N.get_draft(done[0]["id"])["status"] == "processed"
    both = N.list_drafts(status="all")
    assert len(both) == 1
