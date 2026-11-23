from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hinddian import draft_store, note_format as nf

ROOT = Path(__file__).resolve().parents[1]


def test_hook_copies_in_sync():
    result = subprocess.run([sys.executable, str(ROOT / "tools/sync_hooks.py"), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_plaintext_server_defaults():
    result = subprocess.run(["git", "grep", "-nE", r"http://[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+", "--", ".", ":!*.md", ":!tests"],
                            cwd=ROOT, capture_output=True, text=True)
    hits = "\n".join(line for line in result.stdout.splitlines() if "127.0.0.1" not in line)
    assert hits == "", hits


@pytest.fixture
def batch(monkeypatch, vault):
    monkeypatch.syspath_prepend(str(ROOT / "classify"))
    sys.modules.pop("hinddian_batch", None)
    module = importlib.import_module("hinddian_batch")
    monkeypatch.setattr(module, "OWNER", "")
    yield module
    sys.modules.pop("hinddian_batch", None)


def make_note(batch, title, slug, *, relate=(), practice="A"):
    rel = f"项目/P/经验/{title}"
    note = nf.new_note(id=f"proj/P/lesson/{slug}", path=rel, type="lesson", project="P", title=title,
                       scene="s", practice=practice, reason="测试理由", related=[entry["id"] for entry in relate])
    batch.write_file(rel, batch.render(note, {entry["id"]: entry for entry in relate}))
    return note


def put_draft():
    result = draft_store.save_payload({"project": "P", "session_id": "sess-1", "body": "## LESSONS\n- x"})
    return Path(result["path"])


def test_batch_apply_uses_shared_format(batch, monkeypatch):
    first = make_note(batch, "A", "a")
    second = make_note(batch, "B", "b", relate=[first], practice="B")
    path = batch.VAULT / (second["path"] + ".md")
    legacy = "## 取代  \n\n- [[路径/旧方案|旧方案]]  \n\n"
    banner = "> ⚠️ 已被 [[路径/新方案|新方案]] 取代  "
    edited = path.read_text().replace("status: active", "status: active\n"
                                      "custom:\n  owner: 'someone'\n"
                                      "supersedes:\n  - 'legacy/id'\n"
                                      "superseded_by: 'other/id' # historical")
    edited = edited.replace("\n## 场景", f"\n{banner}\n\n## 场景", 1)
    path.write_text(edited + "\n" + legacy + "## 我的补充\n保留  \n")
    draft = put_draft()
    data = {"ops": [{"op": "update", "id": second["id"], "practice": "merged\n## 相关\n- [[evil]]",
                     "sources": ["S01"], "supersedes": [first["id"]]}]}
    monkeypatch.setattr(batch, "chat", lambda prompt: json.dumps(data))
    assert batch.process("P", [draft])[0]["action"] == "update"
    text = path.read_text()
    assert "[[项目/P/经验/A|A]]" in text and "### 相关\n- `evil`" in text and "sources: [sess-1]" in text
    assert "custom:\n  owner: 'someone'" in text and "## 我的补充\n保留  \n" in text
    assert "supersedes:\n  - 'legacy/id'" in text and "superseded_by: 'other/id' # historical" in text
    assert legacy in text and banner in text
    assert batch.load_notes()[first["id"]]["status"] == "active"
    hub = batch.VAULT / "项目/P/README.md"
    hub.write_text("# P\n\n## 决策\nold links\n\n## 已取代\nlegacy links\n\n## 手写补充\n请保留\n")
    batch.rebuild_hubs()
    assert legacy in path.read_text() and banner in path.read_text()
    assert "## 已取代" not in hub.read_text() and "## 手写补充\n请保留" in hub.read_text()
    assert not draft.exists() and (batch.PROCESSED / "P" / draft.name).is_file()


def test_same_length_human_edit_with_preserved_mtime_is_visible_and_survives_batch(batch, monkeypatch):
    note = make_note(batch, "手写测试", "human", practice="rule=A")
    path = batch.VAULT / (note["path"] + ".md")
    stat = path.stat()
    assert batch.load_notes()[note["id"]]["practice"] == "rule=A"
    path.write_text(path.read_text().replace("rule=A", "rule=B"))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_size == stat.st_size and path.stat().st_mtime_ns == stat.st_mtime_ns
    assert batch.load_notes()[note["id"]]["practice"] == "rule=B"

    def chat(prompt):
        assert "rule=B" in prompt and "rule=A" not in prompt
        path.write_text(path.read_text().replace("rule=B", "rule=C"))
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        return json.dumps({"ops": [{"op": "update", "id": note["id"], "practice": "model-rule",
                                    "reason": "新理由", "sources": ["S01"]}]})

    monkeypatch.setattr(batch, "chat", chat)
    batch.process("P", [put_draft()])
    after = batch.load_notes()[note["id"]]
    assert after["practice"] == "rule=C"
    assert after["reason"] == "新理由" and after["sources"] == ["sess-1"]


def test_batch_create_never_overwrites_an_existing_note(batch):
    old = make_note(batch, "部署前先跑门禁", "existing", practice="gate.sh")
    existing = batch.VAULT / "项目/P/经验/缓存命中率.md"
    existing.write_text("# A hand-written page with no frontmatter\n")
    second = existing.with_stem("缓存命中率-2")
    second.write_text("# Also occupied\n")
    result = batch._apply("P", [], {"ops": [{"op": "create", "slug": "existing", "title": "缓存命中率",
                                            "type": "lesson", "practice": "别改前缀"}]}, {}, False)
    assert result[0]["action"] == "create" and result[0]["id"] != old["id"]
    assert batch.load_notes()[old["id"]]["practice"] == "gate.sh"
    assert existing.read_text() == "# A hand-written page with no frontmatter\n"
    assert second.read_text() == "# Also occupied\n"
    assert existing.with_stem("缓存命中率-3").is_file()


def test_batch_similarity_merges_into_existing_note(batch):
    title = "部署前先跑门禁"
    old = make_note(batch, title, "existing", practice="先执行部署门禁脚本")
    results = batch._apply("P", [], {"ops": [{"op": "create", "slug": "new-id", "title": title,
                                             "type": "lesson", "practice": "先执行部署门禁脚本"}]}, {}, False)
    assert results[0]["action"] == "update(dedupe)" and results[0]["id"] == old["id"]
    assert set(batch.load_notes()) == {old["id"]}


def test_batch_retries_if_capture_replaces_a_draft_during_model_call(batch, monkeypatch):
    draft = put_draft()

    def chat(prompt):
        draft_store.save_payload({"project": "P", "session_id": "sess-1", "body": "## LESSONS\n- newer"})
        return '{"ops":[]}'

    monkeypatch.setattr(batch, "chat", chat)
    with pytest.raises(RuntimeError, match="draft changed"):
        batch.process("P", [draft])
    assert "- newer" in draft.read_text()
    assert not batch.PROCESSED.exists()


def test_batch_refuses_outside_paths(batch, tmp_path):
    draft = put_draft()
    outside = tmp_path / "outside"
    outside.mkdir()
    batch.PROCESSED.mkdir()
    (batch.PROCESSED / "P").symlink_to(outside, target_is_directory=True)
    with pytest.raises(nf.UnsafePath):
        batch._apply("P", [draft], {"ops": []}, {}, False)
    with pytest.raises(ValueError, match="invalid project"):
        batch.drafts_of("../outside")
    assert draft.is_file() and list(outside.iterdir()) == []
