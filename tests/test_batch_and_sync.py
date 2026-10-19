from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_hook_copies_in_sync():
    r = subprocess.run([sys.executable, str(ROOT / "tools/sync_hooks.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_no_plaintext_server_defaults():
    """Code and config must not default to a public plain-http server (docs may name the host)."""
    hits = subprocess.run(["git", "grep", "-nE", r"http://[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+", "--", ".", ":!*.md", ":!tests"],
                          cwd=ROOT, capture_output=True, text=True).stdout
    hits = "\n".join(h for h in hits.splitlines() if "127.0.0.1" not in h)
    assert hits == "", hits


def test_batch_apply_uses_shared_format(tmp_path, monkeypatch):
    """Batch writes keep human links/sections and honour the shared lock."""
    monkeypatch.setenv("HC_VAULT", str(tmp_path / "vault"))
    monkeypatch.setenv("HB_BASE", str(tmp_path / "base"))
    monkeypatch.setenv("HINDDIAN_VAULT_LOCK", str(tmp_path / "vault.lock"))
    monkeypatch.syspath_prepend(str(ROOT / "classify"))
    sys.modules.pop("hinddian_batch", None)
    hb = importlib.import_module("hinddian_batch")
    monkeypatch.setattr(hb, "OWNER", "")
    monkeypatch.setattr(hb, "rebuild_hubs", lambda: None)

    from hinddian import notes as N

    monkeypatch.setattr(N, "VAULT", tmp_path / "vault")
    monkeypatch.setattr(N, "OWNER", "")
    (tmp_path / "vault").mkdir()
    a = N.upsert_note({"action": "add", "type": "lesson", "project": "P", "title": "A", "scene": "s"})
    b = N.upsert_note({"action": "add", "type": "lesson", "project": "P", "title": "B", "scene": "s", "related": [a["id"]]})
    pb = tmp_path / "vault" / (b["path"] + ".md")
    pb.write_text(pb.read_text(encoding="utf-8") + "\n## 我的补充\n保留\n", encoding="utf-8")

    draft = tmp_path / "d.md"
    draft.write_text("## LESSONS\n- x\n", encoding="utf-8")
    data = {"ops": [{"op": "update", "id": b["id"], "practice": "merged\n## 相关\n- [[evil]]", "sources": ["S01"]}]}
    res = hb._apply("P", [draft], data, {"S01": "sess-1"}, dry=False)
    assert res[0]["action"] == "update"
    t = pb.read_text(encoding="utf-8")
    assert "[[项目/P/经验/A|A]]" in t
    assert "## 我的补充\n保留" in t
    assert "### 相关\n- `evil`" in t
    assert "sources: [sess-1]" in t


@pytest.fixture
def batch(tmp_path, monkeypatch, vault):
    monkeypatch.setenv("HC_VAULT", str(vault))
    monkeypatch.setenv("HB_BASE", str(tmp_path / "base"))
    monkeypatch.syspath_prepend(str(ROOT / "classify"))
    sys.modules.pop("hinddian_batch", None)
    hb = importlib.import_module("hinddian_batch")
    monkeypatch.setattr(hb, "OWNER", "")
    yield hb
    sys.modules.pop("hinddian_batch", None)


def test_batch_create_never_overwrites_an_existing_note(batch, vault):
    from hinddian import notes as N

    old = N.upsert_note({"action": "add", "type": "lesson", "project": "P", "title": "部署前先跑门禁", "practice": "gate.sh"})
    clash = old["id"].rsplit("/", 1)[-1]
    res = batch._apply("P", [], {"ops": [{"op": "create", "slug": clash, "title": "缓存命中率", "type": "lesson", "practice": "别改前缀"}]}, {}, False)
    assert res[0]["action"] == "create" and res[0]["id"] != old["id"]
    assert N.get_note(old["id"])["practice"] == "gate.sh"


def test_incremental_batch_queues_decisions(batch, vault):
    from hinddian import notes as N

    dec = N.upsert_note({"action": "add", "type": "decision", "project": "P", "title": "只走 HTTPS"}, trusted=True)
    ops = {"ops": [
        {"op": "create", "slug": "tls-only", "title": "新决策", "type": "decision", "practice": "x"},
        {"op": "update", "id": dec["id"], "title": "只走 HTTPS", "type": "decision", "practice": "改写"},
        {"op": "create", "slug": "lesson-a", "title": "一条经验", "type": "lesson", "practice": "y"},
    ]}
    res = batch._apply("P", [], ops, {}, False, review_decisions=True)
    assert [r["action"] for r in res] == ["queued", "queued", "create"]
    assert N.get_note(dec["id"])["practice"] == ""             # decision untouched until approved
    assert len(N.list_notes(project="P", type_="decision")) == 1
    queue = {c["action"]: c for c in N.list_corrections()}
    assert set(queue) == {"add", "update"} and queue["update"]["target_id"] == dec["id"]
    assert N.decide_correction(queue["update"]["id"], approve=True)["ok"]
    assert N.get_note(dec["id"])["practice"] == "改写"
    # the first (user-approved) batch still writes decisions directly
    res = batch._apply("P", [], {"ops": [{"op": "create", "slug": "d2", "title": "另一个决策", "type": "decision"}]}, {}, False)
    assert res[0]["action"] == "create"


def test_export_indexes_content_not_links_or_dates(batch, vault):
    from hinddian import notes as N

    a = N.upsert_note({"action": "add", "type": "lesson", "project": "P", "title": "部署门禁", "practice": "gate.sh"})
    pa = vault / (a["path"] + ".md")
    pa.write_text(pa.read_text(encoding="utf-8") + "\n## 我的补充\n人写的\n", encoding="utf-8")
    before = {n["id"]: n for n in batch.cmd_export()}[a["id"]]
    assert "## 做法\ngate.sh" in before["text"] and "## 我的补充\n人写的" in before["text"]
    assert "id:" not in before["text"] and "所属" not in before["text"]
    # a relink + date bump (what every batch run / hub rebuild does) leaves the index sha alone
    b = N.upsert_note({"action": "add", "type": "lesson", "project": "P", "title": "日志轮转", "practice": "logrotate", "related": [a["id"]]})
    t = pa.read_text(encoding="utf-8").replace("updated: ", "updated: 1999-01-01 #")
    pa.write_text(t, encoding="utf-8")
    N.upsert_note({"action": "update", "id": a["id"], "related": [b["id"]]})
    assert {n["id"]: n for n in batch.cmd_export()}[a["id"]]["sha"] == before["sha"]
    N.upsert_note({"action": "update", "id": a["id"], "practice": "gate.sh --strict"})
    assert {n["id"]: n for n in batch.cmd_export()}[a["id"]]["sha"] != before["sha"]
