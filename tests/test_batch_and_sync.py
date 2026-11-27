from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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


def test_caddy_templates_leave_certificates_and_listeners_configurable():
    directory = ROOT / "deploy/api-host"
    for name, channel in (("Caddyfile.snippet", "DASHBOARD"), ("caddy-hinddian-collector.snippet", "COLLECTOR")):
        text = (directory / name).read_text()
        for key in ("ADDRESS", "CERT", "KEY"):
            assert f"{{$HINDDIAN_{channel}_{key}}}" in text
        assert "/etc/caddy/certs/" not in text and "/etc/caddy/mtls/" not in text


@pytest.fixture
def batch(monkeypatch, vault):
    git(vault, "init", "-q")
    git(vault, "config", "user.name", "Test")
    git(vault, "config", "user.email", "test@example.invalid")
    git(vault, "commit", "--allow-empty", "-qm", "baseline")
    monkeypatch.syspath_prepend(str(ROOT / "classify"))
    sys.modules.pop("hinddian_batch", None)
    module = importlib.import_module("hinddian_batch")
    monkeypatch.setattr(module, "OWNER", "")
    yield module
    sys.modules.pop("hinddian_batch", None)


def git(vault, *args):
    return subprocess.check_output(["git", "-C", str(vault), *args], text=True).strip()


def make_note(batch, title, slug, *, relate=(), practice="A"):
    rel = f"项目/P/经验/{title}"
    note = nf.new_note(id=f"proj/P/lesson/{slug}", path=rel, type="lesson", project="P", title=title,
                       scene="s", practice=practice, reason="测试理由", related=[entry["id"] for entry in relate])
    batch.write_file(rel, batch.render(note, {entry["id"]: entry for entry in relate}))
    return note


def put_draft(*, commit="abcdef1", body="## LESSONS\n- x"):
    result = draft_store.save_payload({"project": "P", "session_id": "sess-1", "body": body,
                                       "meta": {"commit": commit}})
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
    edited = edited.replace("sources: []", "sources: [old-session] # 手写来源注释")
    edited = edited.replace("\n## 场景", f"\n{banner}\n\n## 场景", 1)
    path.write_text(edited + "\n" + legacy + "## 我的补充\n保留  \n")
    draft = put_draft()
    data = {"ops": [{"op": "update", "id": second["id"], "practice": "merged\n## 相关\n- [[evil]]",
                     "sources": ["S01"], "supersedes": [first["id"]]}]}
    monkeypatch.setattr(batch, "chat", lambda prompt: json.dumps(data))
    assert batch.process("P", [draft])[0]["action"] == "update"
    text = path.read_text()
    assert "[[项目/P/经验/A|A]]" in text and "### 相关\n- `evil`" in text
    assert "sources: [old-session, sess-1@abcdef1] # 手写来源注释" in text
    assert "custom:\n  owner: 'someone'" in text and "## 我的补充\n保留  \n" in text
    assert "supersedes:\n  - 'legacy/id'" in text and "superseded_by: 'other/id' # historical" in text
    assert legacy in text and banner in text
    assert batch.load_notes()[first["id"]]["status"] == "active"
    hub = batch.VAULT / "项目/P/README.md"
    hub.write_text("# P\n\n```md\n## 经验\n代码示例\n```\n\n## 决策\nold links\n\n## 经验\n先读现场记录。  \n\n"
                   "## 已取代\nlegacy links\n\n## 手写补充\n请保留\n")
    batch.rebuild_hubs()
    assert legacy in path.read_text() and banner in path.read_text()
    hub_text = hub.read_text()
    assert "## 已取代\nlegacy links" in hub_text and "## 手写补充\n请保留" in hub_text
    assert "```md\n## 经验\n代码示例\n```" in hub_text
    assert "## 经验\n先读现场记录。  \n" in hub_text and "[[项目/P/经验/A|A]]" in hub_text
    index = batch.VAULT / "00-系统/INDEX.md"
    index.write_text(index.read_text().replace("## 全局\n", "## 全局\n手写导航。  \n"))
    index_text = index.read_text()
    batch.rebuild_hubs()
    assert hub.read_text() == hub_text and index.read_text() == index_text
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
    assert after["practice"].startswith("rule=C")
    assert "测试理由" in after["reason"] and "新理由" in after["reason"] and after["sources"] == ["sess-1@abcdef1"]


def test_batch_create_never_overwrites_an_existing_note(batch):
    old = make_note(batch, "部署前先跑门禁", "existing", practice="gate.sh")
    existing = batch.VAULT / "项目/P/经验/缓存命中率.md"
    existing.write_text("# A hand-written page with no frontmatter\n")
    second = existing.with_stem("缓存命中率-2")
    second.write_text("# Also occupied\n")
    result = batch._apply("P", [], {"ops": [{"op": "create", "slug": "existing", "title": "缓存命中率",
                                            "type": "lesson", "scene": "缓存未命中", "reason": "前缀参与匹配",
                                            "practice": "别改前缀", "sources": ["S01"]}]}, {"S01": "sess-1@abcdef1"}, False)
    assert result[0]["action"] == "create" and result[0]["id"] != old["id"]
    assert batch.load_notes()[old["id"]]["practice"] == "gate.sh"
    assert existing.read_text() == "# A hand-written page with no frontmatter\n"
    assert second.read_text() == "# Also occupied\n"
    assert existing.with_stem("缓存命中率-3").is_file()


def test_batch_similarity_merges_into_existing_note(batch):
    title = "部署前先跑门禁"
    near = make_note(batch, title + "检查", "z-near", practice="执行部署门禁")
    old = make_note(batch, title, "existing", practice="先执行部署门禁脚本")
    assert nf.similarity(title, "先执行部署门禁脚本", near) > batch.DEDUPE
    results = batch._apply("P", [], {"ops": [{"op": "create", "slug": "new-id", "title": title,
                                             "type": "lesson", "scene": "部署前", "reason": "需要门禁检查",
                                             "practice": "先执行部署门禁脚本", "sources": ["S01"]}]}, {"S01": "sess-1@abcdef1"}, False)
    assert results[0]["action"] == "update(dedupe)" and results[0]["id"] == old["id"]
    assert {note["id"] for note in batch.load_notes().values() if note["type"] == "lesson"} == {old["id"], near["id"]}


def test_batch_rejects_incomplete_and_deduplicates_creates_in_the_same_batch(batch):
    complete = {"op": "create", "type": "lesson", "title": "先查连接池",
                "scene": "压测超时", "practice": "先查连接池", "reason": "连接池耗尽后请求排队", "sources": ["S01"]}
    incomplete = {"op": "create", "type": "lesson", "title": "只有标题", "sources": ["S01"]}
    results = batch._apply("P", [], {"ops": [incomplete, {**complete, "slug": "first"},
                                            {**complete, "slug": "second"}]}, {"S01": "sess-1@abcdef1"}, False)
    assert [result["action"] for result in results] == ["create", "update(dedupe)"]
    assert sum(note["type"] == "lesson" for note in batch.load_notes().values()) == 1
    assert "incomplete_atomic_note" in batch.LOG.read_text()


def test_batch_retries_if_capture_replaces_a_draft_during_model_call(batch, monkeypatch):
    draft = put_draft()

    def chat(prompt):
        put_draft(body="## LESSONS\n- newer")
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


def test_batch_rejects_archive_dir_as_input(batch, monkeypatch):
    draft = put_draft()
    archive_dir = batch.PROCESSED / "P"
    archive_dir.mkdir(parents=True)
    archived = draft.rename(archive_dir / draft.name)
    original = archived.read_bytes()
    monkeypatch.setattr(batch, "chat", lambda prompt: '{"ops":[]}')

    with pytest.raises(ValueError, match="input directory is the archive directory"):
        batch.process("P", batch.drafts_of("P", archive_dir))
    result = subprocess.run([sys.executable, str(ROOT / "classify/hinddian_batch.py"), "process", "P",
                             "--dir", str(archive_dir)], capture_output=True, text=True, timeout=3)
    assert result.returncode != 0 and "input directory is the archive directory" in result.stderr
    with pytest.raises(ValueError, match="input directory is the archive directory"):
        batch.process("P", [archived])
    assert archived.read_bytes() == original and not batch.LOG.exists()


@pytest.mark.parametrize("relative_directory", [".", "Q", "Q/nested"], ids=["root", "other-project", "nested"])
def test_batch_rejects_inputs_anywhere_in_processed(batch, monkeypatch, relative_directory):
    draft = put_draft()
    archive_dir = batch.PROCESSED / relative_directory
    archive_dir.mkdir(parents=True)
    archived = draft.rename(archive_dir / draft.name)
    original = archived.read_bytes()
    destination = batch.PROCESSED / "P" / archived.name
    monkeypatch.setattr(batch, "chat", lambda prompt: pytest.fail("archived drafts must not reach the model"))
    message = "input directory is inside the processed archive"

    with pytest.raises(ValueError, match=message):
        batch.process("P", [archived])
    with pytest.raises(ValueError, match=message):
        batch.drafts_of("P", archive_dir)
    with pytest.raises(ValueError, match=message):
        batch.archive(archived, destination)
    result = subprocess.run([sys.executable, str(ROOT / "classify/hinddian_batch.py"), "process", "P",
                             "--dir", str(archive_dir)], capture_output=True, text=True, timeout=3)
    assert result.returncode != 0 and message in result.stderr
    assert archived.read_bytes() == original
    assert not destination.exists() and not batch.LOG.exists()


def test_write_allowlist_refuses_external_and_in_vault_symlink_targets(batch, monkeypatch):
    protected = batch.VAULT / "00-系统/手写.md"
    protected.parent.mkdir()
    note = nf.new_note(id="protected", path="00-系统/手写", project="P", title="手写",
                       scene="原现场", practice="原做法", reason="原原因")
    original = batch.render(note, {})
    protected.write_text(original)
    project = batch.VAULT / "项目"
    project.mkdir()
    (project / "shadow").symlink_to(protected.parent, target_is_directory=True)
    with pytest.raises(nf.UnsafePath):
        batch.write_file("项目/shadow/手写", "bypass")
    monkeypatch.setattr(batch, "chat", lambda prompt: json.dumps({"ops": [
        {"op": "update", "id": "protected", "reason": "覆盖", "sources": ["S01"]},
    ]}))
    draft = put_draft()
    assert batch.process("P", [draft]) == []
    assert draft.exists() and protected.read_text() == original
    assert "update_target_outside_allowlist" in batch.LOG.read_text()


@pytest.mark.parametrize("destination", ["in-vault", "outside", "hardlink"])
def test_batch_rejects_redirected_ledger_before_snapshot(batch, monkeypatch, tmp_path, destination):
    protected = (tmp_path / "outside.md" if destination == "outside" else batch.VAULT / "00-系统/手写.md")
    protected.parent.mkdir(parents=True, exist_ok=True)
    protected.write_text("白名单外的手写正文\n")
    batch.BASE.mkdir(exist_ok=True)
    if destination == "hardlink":
        batch.LOG.hardlink_to(protected)
    else:
        batch.LOG.symlink_to(protected)
    original = git(batch.VAULT, "rev-parse", "HEAD")
    monkeypatch.setattr(batch, "chat", lambda prompt: pytest.fail("unsafe ledger reached model"))
    draft = put_draft()
    with pytest.raises(nf.UnsafePath):
        batch.process("P", [draft])
    assert protected.read_text() == "白名单外的手写正文\n" and draft.exists()
    assert git(batch.VAULT, "rev-parse", "HEAD") == original


@pytest.mark.parametrize("directory", ["state", "processed"])
def test_batch_rejects_symlink_in_configured_write_root(batch, monkeypatch, tmp_path, directory):
    target = tmp_path / "outside"
    target.mkdir()
    alias = tmp_path / "aliased-parent"
    alias.symlink_to(target, target_is_directory=True)
    if directory == "state":
        monkeypatch.setattr(batch, "BASE", alias / "state")
        monkeypatch.setattr(batch, "LOG", batch.BASE / "batch-ledger.jsonl")
    else:
        monkeypatch.setattr(batch, "PROCESSED", alias / "processed")
    monkeypatch.setattr(batch, "chat", lambda prompt: pytest.fail("unsafe root reached model"))
    draft = put_draft()
    with pytest.raises(nf.UnsafePath):
        batch.process("P", [draft])
    assert draft.exists() and not list(target.iterdir())


def test_legacy_project_state_entry_cannot_run(batch):
    script = ROOT / "tools/project_state.py"
    result = subprocess.run([sys.executable, str(script), "P"], capture_output=True, text=True, timeout=3)
    assert result.returncode == 2 and "can't open file" in result.stderr
    assert not script.exists() and not list(batch.VAULT.rglob("*.md"))


def test_batch_holds_drafts_without_commit_and_rejects_unknown_sources(batch, monkeypatch):
    legacy = put_draft(commit="")
    monkeypatch.setattr(batch, "chat", lambda prompt: pytest.fail("unattributed draft reached model"))
    assert batch.process("P", [legacy]) == []
    assert legacy.exists() and "missing_session_or_commit" in batch.LOG.read_text()
    draft = put_draft()
    monkeypatch.setattr(batch, "chat", lambda prompt: json.dumps({"ops": [
        {"op": "create", "title": "完整但无来源", "type": "lesson", "scene": "场景",
         "practice": "做法", "reason": "理由", "sources": ["S99"]},
    ]}))
    assert batch.process("P", [draft]) == []
    assert draft.exists() and not list(batch.VAULT.rglob("*.md"))
    assert "missing_or_unknown_source" in batch.LOG.read_text()


def test_pending_legacy_drafts_do_not_block_eligible_batches(batch, monkeypatch):
    legacy = put_draft(commit="")
    modern = legacy.with_stem("z-modern")
    modern.write_text(legacy.read_text().replace('commit: ""', "commit: abcdef1"))
    monkeypatch.setattr(batch, "BATCH", 1)
    monkeypatch.setattr(batch, "RUN_MAX_BATCHES", 1)
    monkeypatch.setattr(batch, "chat", lambda prompt: '{"ops":[]}')
    batch.cmd_run()
    assert legacy.exists() and not modern.exists()


def test_batch_leaves_another_projects_legacy_index_count(batch, monkeypatch):
    other = batch.VAULT / "项目/Other/README.md"
    other.parent.mkdir(parents=True)
    other.write_text("# Other\n")
    index = batch.VAULT / "00-系统/INDEX.md"
    index.parent.mkdir()
    entry = "- [[项目/Other/README|Other]] — 71 条决策/经验"
    index.write_text(f"---\nid: system/index\ngenerated: true\n---\n# INDEX\n\n## 项目\n{entry}\n")
    monkeypatch.setattr(batch, "chat", lambda prompt: json.dumps({"ops": [
        {"op": "create", "title": "现场经验", "type": "lesson", "scene": "场景",
         "practice": "做法", "reason": "理由", "sources": ["S01"]},
    ]}))
    batch.process("P", [put_draft()])
    assert entry in index.read_text()
    assert "- [[项目/P/README|P]] — 1 条决策/经验" in index.read_text()


def test_batch_rebuild_preserves_manual_lines_inside_generated_block(batch, monkeypatch):
    hub = batch.VAULT / "项目/P/README.md"
    hub.parent.mkdir(parents=True)
    manual = "- [[手工链接|手记链接]] — 手工注释。\n手填段落应保留。\n<!-- 手工评论 -->\n- [[裸手工链接]]\n"
    stale = "- [[旧自动链接]] <!-- hinddian:generated -->\n"
    hub.write_text(f"# P\n\n## 经验\n手记保留在块外。\n<!-- hinddian:links -->\n{manual}{stale}"
                   "<!-- /hinddian:links -->\n")
    monkeypatch.setattr(batch, "chat", lambda prompt: json.dumps({"ops": [
        {"op": "create", "title": "先备份", "type": "lesson", "scene": "场景",
         "practice": "做法", "reason": "理由", "sources": ["S01"]},
    ]}))
    batch.process("P", [put_draft()])
    result = hub.read_text()
    assert "手记保留在块外。\n<!-- hinddian:links -->\n" + manual in result
    assert "[[项目/P/经验/先备份|先备份]]" in result and stale not in result
    batch.rebuild_hubs()
    assert hub.read_text() == result


def test_rebuild_hubs_preserves_unmarked_links(batch):
    hub = batch.VAULT / "项目/P/README.md"
    hub.parent.mkdir(parents=True)
    orphan = "- [[项目/P/经验/曾经有效|曾经有效]]"
    note = make_note(batch, "仍然有效", "active")
    current = f"- [[{note['path']}|仍然有效]]"
    manual = "手写待补清单\n- [[项目/P/经验/待补复盘|待补复盘]]\n"
    original = (f"# P\n\n## 经验\n{orphan}\n<!-- hinddian:links -->\n{orphan}\n{current}\n{manual}"
                "<!-- /hinddian:links -->\n")
    hub.write_text(original)
    added = make_note(batch, "新经验", "new")
    marked = f"- [[{added['path']}|新经验]] <!-- hinddian:generated -->\n"

    batch.rebuild_hubs()

    result = hub.read_text()
    assert result == original.replace("<!-- /hinddian:links -->", marked + "<!-- /hinddian:links -->")
    batch.rebuild_hubs()
    assert hub.read_text() == result


@pytest.mark.parametrize(("opening", "closing"), [
    pytest.param("<!-- hinddian:links -->", "<!-- /hinddian:links -->", id="standard"),
    pytest.param(" <!-- hinddian:links --> \t", " <!-- /hinddian:links -->\t ", id="padded"),
])
def test_rebuild_hubs_prunes_only_confirmed_legacy_link(batch, opening, closing):
    current = make_note(batch, "在用", "current")
    hub = batch.VAULT / "项目/P/README.md"
    stale = "- [[项目/P/经验/已移除|已移除]]"
    pending = "- [[项目/P/经验/待补复盘|待补复盘]]"
    marked = f"- {batch.link_of(current)} <!-- hinddian:generated -->"
    original = (f"# P\n\n## 经验\n{stale}\n{opening}\n{stale}\n{pending}\n"
                f"```md\n{stale}\n```\n{marked}\n{closing}\n")
    hub.write_text(original)
    batch.rebuild_hubs()
    assert hub.read_text() == original

    result = subprocess.run([sys.executable, str(ROOT / "classify/hinddian_batch.py"), "rebuild-hubs",
                             "--prune-legacy-link", "项目/P/README.md", "经验", stale[2:]],
                            capture_output=True, text=True, timeout=4)

    assert result.returncode == 0, result.stderr
    expected = original.replace(f"{opening}\n{stale}\n", f"{opening}\n")
    assert hub.read_text() == expected
    batch.rebuild_hubs()
    assert hub.read_text() == expected


@pytest.mark.parametrize("links", ["{stale}\n{stale}", "```md\n{stale}\n```"])
def test_rebuild_hubs_rejects_nonunique_legacy_link(batch, links):
    make_note(batch, "在用", "current")
    hub = batch.VAULT / "项目/P/README.md"
    stale = "[[项目/P/经验/已移除|已移除]]"
    content = links.format(stale=f"- {stale}")
    original = f"# P\n\n## 经验\n<!-- hinddian:links -->\n{content}\n<!-- /hinddian:links -->\n"
    hub.write_text(original)

    with pytest.raises(ValueError, match="expected one unmarked legacy link"):
        batch.rebuild_hubs(legacy_link=("项目/P/README.md", "经验", stale))

    assert hub.read_text() == original


@pytest.mark.parametrize("first_matches", [True, False], ids=["ambiguous", "unique-in-second-block"])
def test_rebuild_hubs_prune_checks_all_blocks_in_section(batch, first_matches):
    make_note(batch, "在用", "current")
    hub = batch.VAULT / "项目/P/README.md"
    legacy = "[[项目/P/经验/已移除|已移除]]"
    pending = legacy if first_matches else "[[项目/P/经验/待补|待补]]"
    fenced = "```md\n<!-- /hinddian:links -->\n<!-- hinddian:links -->\n```\n"
    original = (f"# P\n\n## 经验\n<!-- hinddian:links -->\n手写待补入口\n- {pending}\n{fenced}"
                f"<!-- /hinddian:links -->\n\n<!-- hinddian:links -->\n旧版生成入口\n- {legacy}\n"
                "<!-- /hinddian:links -->\n")
    hub.write_text(original)
    head = git(batch.VAULT, "rev-parse", "HEAD")

    result = subprocess.run([sys.executable, str(ROOT / "classify/hinddian_batch.py"), "rebuild-hubs",
                             "--prune-legacy-link", "项目/P/README.md", "经验", legacy],
                            capture_output=True, text=True, timeout=4)

    if first_matches:
        assert result.returncode != 0 and "found 2" in result.stderr
        assert hub.read_bytes() == original.encode()
        assert git(batch.VAULT, "rev-parse", "HEAD") == head
    else:
        assert result.returncode == 0, result.stderr
        text = hub.read_text()
        assert f"手写待补入口\n- {pending}\n" in text
        assert "旧版生成入口\n" in text and f"- {legacy}\n" not in text
        assert fenced in text


@pytest.mark.parametrize(("before", "after", "error"), [
    pytest.param("<!-- hinddian:links -->\n旧版链接\n- {legacy}\n<!-- hinddian:links -->\n"
                 "<!-- /hinddian:links -->\n<!-- /hinddian:links -->\n", "",
                 "nested", id="nested"),
    pytest.param("<!-- /hinddian:links -->\n", "", "unmatched closing", id="orphan-close"),
    pytest.param("", "<!-- hinddian:links -->", "unclosed", id="unclosed-at-eof"),
    pytest.param("<!-- hinddian:links --> \t\n旧版链接\n- {legacy}\n<!-- hinddian:links -->\n"
                 "<!-- /hinddian:links -->\n<!-- /hinddian:links --> \t\n", "",
                 "nested", id="nested-padded-outer"),
    pytest.param(" <!-- /hinddian:links --> \t\n", "", "unmatched closing", id="orphan-close-padded"),
    pytest.param("", "   <!-- hinddian:links --> \t", "unclosed", id="unclosed-padded"),
])
def test_rebuild_hubs_prune_rejects_malformed_markers_without_writes(batch, tmp_path, before, after, error):
    make_note(batch, "在用", "current")
    hub = batch.VAULT / "项目/P/README.md"
    legacy = "[[项目/P/经验/已移除|已移除]]"
    hub.write_text(f"# P\n\n## 经验\n{before.format(legacy=legacy)}\n"
                   f"<!-- hinddian:links -->\n手写待补入口\n- {legacy}\n<!-- /hinddian:links -->\n{after}")
    git(batch.VAULT, "add", "-A")
    git(batch.VAULT, "commit", "-qm", "hub fixture")
    (batch.VAULT / "手写变更.md").write_text("保留手写文字\n")
    batch.LOG.parent.mkdir(parents=True, exist_ok=True)
    batch.LOG.write_bytes(b'{"event":"existing"}\n')
    head = git(batch.VAULT, "rev-parse", "HEAD")

    def snapshot():
        return {path: (path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else None)
                for path in tmp_path.rglob("*")}

    original = snapshot()
    result = subprocess.run([sys.executable, str(ROOT / "classify/hinddian_batch.py"), "rebuild-hubs",
                             "--prune-legacy-link", "项目/P/README.md", "经验", legacy],
                            capture_output=True, text=True, timeout=4)

    assert result.returncode != 0 and error in result.stderr
    assert snapshot() == original
    assert git(batch.VAULT, "rev-parse", "HEAD") == head


@pytest.mark.parametrize("example", [
    pytest.param("    {marker}\n", id="four-space-code"),
    pytest.param("\t{marker}\n", id="tab-code"),
    pytest.param("> {marker}\n", id="quote"),
    pytest.param("- 示例\n\n      {marker}\n", id="list-code"),
    pytest.param("`{marker}`\n", id="inline-code"),
    pytest.param("<!-- 示例说明\n## 经验\n{marker}\n", id="multiline-comment"),
])
def test_rebuild_hubs_prune_ignores_marker_examples_without_writes(batch, tmp_path, example):
    current = make_note(batch, "在用", "current")
    hub = batch.VAULT / "项目/P/README.md"
    legacy = "[[项目/P/经验/已移除|已移除]]"
    opener, closer = "<!-- hinddian:links -->", "<!-- /hinddian:links -->"
    original = (f"# P\n\n## 经验\n\n{opener}\n- {batch.link_of(current)}\n{closer}\n\n"
                f"{example.format(marker=opener)}\n手写待补入口\n\n- {legacy}\n手写备注。\n\n"
                f"{example.format(marker=closer)}")
    hub.write_text(original)
    git(batch.VAULT, "add", "-A")
    git(batch.VAULT, "commit", "-qm", "hub fixture")
    head = git(batch.VAULT, "rev-parse", "HEAD")

    def snapshot():
        return {path: (path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else None)
                for path in tmp_path.rglob("*")}

    before = snapshot()
    result = subprocess.run([sys.executable, str(ROOT / "classify/hinddian_batch.py"), "rebuild-hubs",
                             "--prune-legacy-link", "项目/P/README.md", "经验", legacy],
                            capture_output=True, text=True, timeout=4)

    assert result.returncode != 0 and "found 0" in result.stderr
    assert snapshot() == before
    assert git(batch.VAULT, "rev-parse", "HEAD") == head


@pytest.mark.parametrize("dirty", [False, True], ids=["clean", "dirty"])
def test_rebuild_hubs_dry_run_rejects_before_any_write(batch, dirty):
    make_note(batch, "在用", "current")
    git(batch.VAULT, "add", "-A")
    git(batch.VAULT, "commit", "-qm", "active note")
    if dirty:
        (batch.VAULT / "手写变更.md").write_text("保留手写文字\n")
    head = git(batch.VAULT, "rev-parse", "HEAD")
    status = git(batch.VAULT, "status", "--porcelain", "--untracked-files=all")
    notes = {path: path.read_bytes() for path in batch.VAULT.rglob("*.md")}
    draft = put_draft()
    draft_bytes = draft.read_bytes()
    ledger = b'{"event":"existing"}\n'
    batch.LOG.parent.mkdir(parents=True, exist_ok=True)
    batch.LOG.write_bytes(ledger)

    result = subprocess.run([sys.executable, str(ROOT / "classify/hinddian_batch.py"),
                             "rebuild-hubs", "--dry-run"], capture_output=True, text=True, timeout=4)

    assert result.returncode == 2 and "--dry-run is only supported with process" in result.stderr
    assert git(batch.VAULT, "rev-parse", "HEAD") == head
    assert git(batch.VAULT, "status", "--porcelain", "--untracked-files=all") == status
    assert {path: path.read_bytes() for path in batch.VAULT.rglob("*.md")} == notes
    assert draft.read_bytes() == draft_bytes and not batch.PROCESSED.exists()
    assert batch.LOG.read_bytes() == ledger


def test_process_dry_run_still_checks_model_update_without_writing_notes(batch, monkeypatch):
    note = make_note(batch, "在用", "current")
    path = batch.VAULT / (note["path"] + ".md")
    original = path.read_bytes()
    git(batch.VAULT, "add", "-A")
    git(batch.VAULT, "commit", "-qm", "active note")
    head = git(batch.VAULT, "rev-parse", "HEAD")
    draft = put_draft()
    draft_bytes = draft.read_bytes()
    monkeypatch.setattr(batch, "chat", lambda prompt: json.dumps({"ops": [
        {"op": "update", "id": note["id"], "tags": ["new"], "sources": ["S01"]},
    ]}))

    result = batch.process("P", [draft], dry=True)

    assert result[0]["action"] == "update"
    assert path.read_bytes() == original and draft.read_bytes() == draft_bytes
    assert not batch.PROCESSED.exists()
    assert git(batch.VAULT, "rev-parse", "HEAD") == head
    assert not git(batch.VAULT, "status", "--porcelain", "--untracked-files=all")
    assert json.loads(batch.LOG.read_text().splitlines()[0])["dry_run"] is True


def test_rebuild_hubs_preserves_manual_links_and_fenced_examples(batch):
    hub = batch.VAULT / "项目/P/README.md"
    retired = hub.parent / "经验/已退役.md"
    retired.parent.mkdir(parents=True)
    retired.write_text("---\nid: retired\nproject: P\ntype: lesson\nstatus: retired\n---\n# 已退役\n")
    manual_links = ("- [[项目/P/经验/已退役|手写别名，仍需查阅]]\n- [[项目/P/经验/已退役|已退役]]\n"
                    "- [[项目/P/经验/悬空链接|手写待补入口]]\n")
    marked_link = "- [[项目/P/经验/示例|示例]] <!-- hinddian:generated -->\n"
    example = f"```md\n<!-- hinddian:links -->\n{manual_links}{marked_link}<!-- /hinddian:links -->\n```\n"
    original = f"# P\n\n## 经验\n{example}<!-- hinddian:links -->\n{manual_links}手写说明。\n"
    original += f"~~~md\n{marked_link}~~~\n<!-- /hinddian:links -->\n"
    hub.write_text(original)

    batch.rebuild_hubs()

    assert hub.read_text() == original
    assert retired.is_file()


@pytest.mark.parametrize(("overlay", "expected"), [
    ("tags: [handwritten,] # 手写说明", "tags: [handwritten, new,] # 手写说明"),
    ("tags: [handwritten]\n-手写: 不能丢", "tags: [handwritten, new]\n-手写: 不能丢"),
    pytest.param(
        "tags: [\n  handwritten, # 手写标签\n  ]",
        "tags: [\n  handwritten, # 手写标签\n  new,\n  ]",
        id="multiline-trailing-comma",
    ),
    pytest.param(
        'tags: [ # 开始，]不是结束\n  "handwritten" # 手写标签，逗号 ,\n] # 结束',
        'tags: [ # 开始，]不是结束\n  "handwritten", # 手写标签，逗号 ,\n  new\n] # 结束',
        id="multiline-comment-without-trailing-comma",
    ),
    pytest.param(
        "'tags': !!seq [\n  'handwritten' ] # 手写标签",
        "'tags': !!seq [\n  'handwritten', new ] # 手写标签",
        id="multiline-close-on-last-item-line",
    ),
])
def test_batch_update_keeps_valid_yaml_frontmatter(batch, monkeypatch, overlay, expected):
    note = batch.VAULT / "项目/P/经验/独立手改.md"
    note.parent.mkdir(parents=True)
    note.write_text(f"---\nid: manual\nproject: P\ntype: lesson\n{overlay}\nsources: [origin@abcdef1]\n"
                    "---\n# 独立手改\n\n## 理由\n手写说明\n")
    draft = put_draft()
    monkeypatch.setattr(batch, "chat", lambda prompt: json.dumps({"ops": [
        {"op": "update", "id": "manual", "tags": ["new"], "reason": "新证据", "sources": ["S01"]},
    ]}))

    batch.process("P", [draft])

    result = note.read_text()
    parsed = yaml.safe_load(result.split("---\n", 2)[1])
    assert expected in result
    assert parsed["tags"] == ["handwritten", "new"]
    assert parsed["sources"] == ["origin@abcdef1", "sess-1@abcdef1"]
    if "-手写:" in overlay:
        assert parsed["-手写"] == "不能丢"
    assert "手写说明\n\n新证据" in result
    assert not draft.exists() and (batch.PROCESSED / "P" / draft.name).is_file()


def test_batch_updates_and_reloads_multiline_flow_fields(batch, monkeypatch):
    previous = make_note(batch, "已有经验", "old")
    added = make_note(batch, "新增经验", "new")
    note = batch.VAULT / "项目/P/经验/独立手改.md"
    old_link, new_link = map(batch.link_of, (previous, added))
    original = ("---\nid: manual\nproject: P\ntype: lesson\n"
                "tags: [\n  # 手写空列表\n  ]\n"
                "sources: [\norigin@abcdef1\n] # 来源说明\n"
                f'related:\n  [\n  "{old_link}",\n  ]\n'
                "manual:\n  owner: '某人' # 手写属性\n"
                "---\n# 独立手改\n\n## 相关\n手写关联说明\n")
    note.write_text(original)
    draft = put_draft()
    draft.write_text(draft.read_text().replace("session_id: sess-1", "session_id: alpha,beta"))
    draft_text = draft.read_bytes()
    monkeypatch.setattr(batch, "chat", lambda prompt: json.dumps({"ops": [
        {"op": "update", "id": "manual", "tags": ["new"], "sources": ["S01"],
         "related": [previous["id"], added["id"]]},
    ]}))

    batch.process("P", [draft])

    result = note.read_text()
    expected = yaml.safe_load(original.split("---\n", 2)[1])
    expected.update(tags=["new"], sources=["origin@abcdef1", "alpha,beta@abcdef1"], related=[old_link, new_link])
    assert yaml.safe_load(result.split("---\n", 2)[1]) == expected
    assert "tags: [\n  # 手写空列表\n  new\n  ]\n" in result
    assert 'sources: [\norigin@abcdef1,\n  "alpha,beta@abcdef1"\n] # 来源说明\n' in result
    assert f'related:\n  [\n  "{old_link}",\n  "{new_link}",\n  ]\n' in result
    assert "manual:\n  owner: '某人' # 手写属性\n" in result
    assert result.endswith(f"## 相关\n手写关联说明\n\n- {new_link}\n")
    loaded = batch.load_notes()["manual"]
    assert loaded["tags"] == expected["tags"] and loaded["sources"] == expected["sources"]
    assert loaded["related"] == [previous["id"], added["id"]]
    archive = batch.PROCESSED / "P" / draft.name
    assert not draft.exists() and archive.read_bytes() == draft_text

    draft.write_bytes(draft_text)
    batch.process("P", [draft])
    assert note.read_text() == result and not draft.exists() and archive.read_bytes() == draft_text


@pytest.mark.parametrize("custom", [
    "manual: !Local value # 手写属性\n",
    "manual: !Local\n  owner: '某人' # 手写属性\n  data: !List [old, !Item value]\n",
    "manual: !Local &metadata [value, !Item '保留'] # 手写属性\ncopy: *metadata\n",
])
def test_batch_preserves_unrelated_yaml_tags(batch, monkeypatch, custom):
    note = make_note(batch, "手写", "manual")
    path = batch.VAULT / (note["path"] + ".md")
    original = path.read_text().replace("tags: []\n", "tags: [\n  old, # 手写标签\n  ]\n" + custom)
    path.write_text(original)
    draft = put_draft()
    monkeypatch.setattr(batch, "chat", lambda prompt: json.dumps({"ops": [
        {"op": "update", "id": note["id"], "tags": ["new"], "sources": ["S01"]},
    ]}))

    batch.process("P", [draft])

    expected = original.replace("  old, # 手写标签\n", "  old, # 手写标签\n  new,\n")
    expected = expected.replace("sources: []", "sources: [sess-1@abcdef1]")
    assert path.read_text() == expected
    loaded = batch.load_notes()[note["id"]]
    assert loaded["tags"] == ["old", "new"] and loaded["sources"] == ["sess-1@abcdef1"]
    assert not draft.exists() and (batch.PROCESSED / "P" / draft.name).is_file()


@pytest.mark.parametrize(("overlay", "message"), [
    ("tags: !Local [old]\n", "cannot update opaque frontmatter field tags"),
    ("tags: &old [old]\nmanual: !Local {saved: *old}\n", "would change existing values"),
])
def test_batch_refuses_to_change_custom_yaml_values(batch, monkeypatch, overlay, message):
    note = make_note(batch, "手写", "manual")
    path = batch.VAULT / (note["path"] + ".md")
    original = path.read_text().replace("tags: []\n", overlay)
    path.write_text(original)
    draft = put_draft()
    monkeypatch.setattr(batch, "chat", lambda prompt: json.dumps({"ops": [
        {"op": "update", "id": note["id"], "tags": ["new"], "sources": ["S01"]},
    ]}))

    with pytest.raises(ValueError, match=message):
        batch.process("P", [draft])

    assert path.read_text() == original and draft.exists()
    assert not (batch.PROCESSED / "P" / draft.name).exists()


@pytest.mark.parametrize("manual", [
    pytest.param("&local !Local [*local]", id="custom-cycle"),
    pytest.param("&local [*local]", id="standard-cycle"),
    pytest.param("&local {nested: [*local]}", id="indirect-cycle"),
])
def test_batch_warns_on_recursive_yaml_and_keeps_notes_and_draft(batch, monkeypatch, capsys, manual):
    safe = make_note(batch, "在用", "current")
    note = batch.VAULT / "项目/P/经验/手写.md"
    front = f"id: recursive\nproject: P\ntype: lesson\ntags: [old]\nmanual: {manual}\n"
    assert yaml.compose(front) is not None
    original = f"---\n{front}---\n# 手写\n\n## 理由\n手写说明\n".encode()
    note.write_bytes(original)
    other_note = batch.VAULT / (safe["path"] + ".md")
    other_bytes = other_note.read_bytes()
    draft = put_draft()
    draft_bytes = draft.read_bytes()
    monkeypatch.setattr(batch, "chat", lambda prompt: json.dumps({"ops": [
        {"op": "update", "id": note_id, "tags": ["new"], "reason": "新增说明", "sources": ["S01"]}
        for note_id in (safe["id"], "recursive")
    ]}))

    assert batch.process("P", [draft]) == []

    warning = capsys.readouterr().err
    assert "recursive YAML alias" in warning and "项目/P/经验/手写" in warning
    assert any(event["event"] == "write_rejected" and event.get("reason") == "recursive_frontmatter_alias"
               for event in map(json.loads, batch.LOG.read_text().splitlines()))
    assert note.read_bytes() == original and other_note.read_bytes() == other_bytes
    assert draft.read_bytes() == draft_bytes and not batch.PROCESSED.exists()


def test_run_skips_recursive_batches_and_reaches_drafts_past_the_batch_limit(batch, monkeypatch, capsys):
    safe = make_note(batch, "在用", "current")
    recursive = make_note(batch, "手写", "recursive")
    note = batch.VAULT / (recursive["path"] + ".md")
    note.write_text(note.read_text().replace("tags: []\n", "tags: []\nmanual: &local !Local [*local]\n"))
    original_note = note.read_bytes()
    assert b"manual: &local !Local [*local]" in original_note
    draft = put_draft()
    template = draft.read_text()
    draft.unlink()
    pending = {
        draft.with_name(f"{index:03}.md"): (template + f"\nmanual-review-marker-{index:03}\n").encode()
        for index in range(1, 62)
    }
    for path, original in pending.items():
        path.write_bytes(original)
    monkeypatch.setattr(batch, "BATCH", 20)
    monkeypatch.setattr(batch, "RUN_MAX_BATCHES", 3)
    calls = []

    def chat(prompt):
        markers = [index for index in range(1, 62) if f"manual-review-marker-{index:03}" in prompt]
        calls.append(markers)
        target = safe if markers == [61] else recursive
        return json.dumps({"ops": [
            {"op": "update", "id": target["id"], "reason": "新增说明", "sources": ["S01"]},
        ]})

    monkeypatch.setattr(batch, "chat", chat)
    for _ in range(2):
        with pytest.raises(RuntimeError, match=r"P: 3 batch\(es\) skipped"):
            batch.cmd_run()
        assert capsys.readouterr().err.count("batch skipped, drafts retained") == 3

    first_batches = [list(range(start, start + 20)) for start in (1, 21, 41)]
    assert calls == [*first_batches, [61], *first_batches]
    tail = draft.with_name("061.md")
    assert not tail.exists()
    assert {file.name: file.read_bytes() for file in (batch.PROCESSED / "P").iterdir()} == {
        tail.name: pending.pop(tail),
    }
    assert {path: path.read_bytes() for path in tail.parent.glob("*.md")} == pending
    assert note.read_bytes() == original_note
    assert "新增说明" in (batch.VAULT / (safe["path"] + ".md")).read_text()


@pytest.mark.parametrize("overlay", [
    "tags: [handwritten]\nhistory: &past [origin@abcdef1]\nsources: *past # 原来源",
    "tags: !!seq [handwritten] # 手写标签\nsources: [origin@abcdef1]",
    "tags: &original !!seq [handwritten]\nmanual_tags: *original\nsources: [origin@abcdef1]",
    "tags: &original [\n  handwritten,\n  ]\nmanual_tags: *original\nsources: [origin@abcdef1]",
])
def test_batch_update_preserves_yaml_alias_and_sequence_values(batch, monkeypatch, overlay):
    note = batch.VAULT / "项目/P/经验/手写.md"
    note.parent.mkdir(parents=True)
    original = f"---\nid: manual\nproject: P\ntype: lesson\n{overlay}\n---\n# 手写\n\n## 理由\n手写说明\n"
    note.write_text(original)
    draft = put_draft()
    draft.write_text(draft.read_text().replace("session_id: sess-1", "session_id: alpha,beta"))
    monkeypatch.setattr(batch, "chat", lambda prompt: json.dumps({"ops": [
        {"op": "update", "id": "manual", "tags": ["handwritten", "new"], "reason": "新证据", "sources": ["S01"]},
    ]}))

    if "manual_tags:" in overlay:
        with pytest.raises(ValueError, match="would change existing values"):
            batch.process("P", [draft])
        assert note.read_text() == original and draft.exists()
        return

    batch.process("P", [draft])

    result = note.read_text()
    expected = yaml.safe_load(original.split("---\n", 2)[1])
    expected["sources"] = ["origin@abcdef1", "alpha,beta@abcdef1"]
    expected["tags"] = ["handwritten", "new"]
    assert yaml.safe_load(result.split("---\n", 2)[1]) == expected
    if "*past" in overlay:
        assert "history: &past [origin@abcdef1]\n" in result
    else:
        assert "tags: !!seq [handwritten, new] # 手写标签\n" in result
    for comment in ("# 原来源", "# 手写标签"):
        if comment in original:
            assert comment in result
    assert "手写说明\n\n新证据" in result
    assert not draft.exists() and (batch.PROCESSED / "P" / draft.name).is_file()


def test_batch_update_keeps_commented_yaml_list_and_original_source_id(batch, monkeypatch):
    note = batch.VAULT / "项目/P/经验/独立手改.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\nid: manual\nproject: P\ntype: lesson\ntags:\n# 手写列表说明\n"
                    "  - handwritten # 行尾说明\nsources: [origin@abcdef1]\n# 来源说明\n"
                    "---\n# 独立手改\n\n## 理由\n手写说明\n")
    draft = put_draft()
    draft.write_text(draft.read_text().replace("session_id: sess-1", "session_id: alpha,beta"))
    monkeypatch.setattr(batch, "chat", lambda prompt: json.dumps({"ops": [
        {"op": "update", "id": "manual", "tags": ["new"], "reason": "新证据", "sources": ["S01"]},
    ]}))
    batch.process("P", [draft])
    result = note.read_text()
    assert "tags:\n# 手写列表说明\n  - handwritten # 行尾说明\n  - new\n" in result
    assert 'sources: [origin@abcdef1, "alpha,beta@abcdef1"]\n# 来源说明\n' in result
    parsed = batch.load_notes()["manual"]
    assert parsed["tags"] == ["handwritten", "new"]
    assert parsed["sources"] == ["origin@abcdef1", "alpha,beta@abcdef1"]
    assert parsed["reason"] == "手写说明\n\n新证据"


def test_batch_snapshots_dirty_vault_and_logs_diff_for_all_model_ops(batch, monkeypatch, capsys):
    head = git(batch.VAULT, "rev-parse", "HEAD")
    human = batch.VAULT / "手写.md"
    human.write_text("保留正文")
    draft = put_draft(body="## LESSONS\n- " + "字" * 2000 + "\n## OPEN QUESTIONS\n独立待验证项")
    titles = ["backup", "resolver", "latency", "filesystem", "queues", "journal", "network", "volume", "point"]
    ops = [{"op": "create", "title": title, "type": "lesson", "scene": f"现场 {title}",
            "practice": title, "reason": f"对应现象 {title}", "sources": ["S01"]} for title in titles]

    def chat(prompt):
        assert "独立待验证项" in prompt and git(batch.VAULT, "rev-parse", "HEAD") != head
        assert git(batch.VAULT, "status", "--porcelain") == ""
        return json.dumps({"ops": ops})

    monkeypatch.setattr(batch, "chat", chat)
    assert len(batch.process("P", [draft])) == len(ops)
    events = [json.loads(line) for line in batch.LOG.read_text().splitlines()]
    baseline = next(event for event in events if event["event"] == "snapshot")
    diff = next(event for event in events if event["event"] == "diff")
    assert baseline["created"] and diff["baseline"] == baseline["commit"]
    assert "point.md" in diff["stat"] in capsys.readouterr().out
    assert "手写.md" not in diff["stat"] and human.read_text() == "保留正文"
    assert git(batch.VAULT, "diff", "--cached", "--stat") == ""
