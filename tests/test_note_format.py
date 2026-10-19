from __future__ import annotations

from hinddian import note_format as nf

HUMAN_NOTE = """---
id: proj/P/lesson/a
type: lesson
project: P
tags:
  - alpha
  - beta
status: active
supersedes: []
related: ["[[项目/P/经验/Gone|Gone]]"]
sources: []
updated: 2026-01-01
reviewer: alice
generated: true
---
# A

> 所属：[[项目/P/README|P]]
> 人写的一行引用

## 场景
s with [[项目/P/经验/B|B]] link

## 做法
p

## 理由
r

## 我的补充
人手写的段落，不能丢。
"""


def _parse(tmp_path, text, name="A.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return nf.parse_note(p, tmp_path)


def test_block_list_and_unknown_keys_parse(tmp_path):
    n = _parse(tmp_path, HUMAN_NOTE)
    assert n["tags"] == ["alpha", "beta"]
    assert n["_fm"]["reviewer"] == "alice"
    assert ("我的补充", "人手写的段落，不能丢。") in n["_sections"]


def test_render_preserves_human_content(tmp_path):
    n = _parse(tmp_path, HUMAN_NOTE)
    notes = {n["id"]: n}
    nf.resolve_links(notes)
    n["practice"] = "p2"
    out = nf.render(n, notes, today="2026-02-02")
    assert "reviewer: alice" in out
    assert "generated: true" in out  # unchanged value written back verbatim
    assert "tags:\n  - alpha\n  - beta" in out
    assert "## 我的补充\n人手写的段落，不能丢。" in out
    assert "> 人写的一行引用" in out
    assert "[[项目/P/经验/B|B]]" in out  # wikilinks in existing text are not rewritten
    assert "[[项目/P/经验/Gone|Gone]]" in out  # dangling human link kept, not dropped


def test_render_is_idempotent(tmp_path):
    n = _parse(tmp_path, HUMAN_NOTE)
    notes = {n["id"]: n}
    nf.resolve_links(notes)
    once = nf.render(n, notes, today="2026-02-02")
    m = _parse(tmp_path, once, "A2.md")
    m["path"] = n["path"]
    nf.resolve_links({m["id"]: m})
    assert nf.render(m, {m["id"]: m}, today="2026-02-02") == once


def test_frontmatter_values_cannot_inject_keys():
    out = nf.dump_frontmatter([("title", "x\nstatus: obsolete"), ("tags", ["a]\nid: evil"])])
    lines = out.splitlines()
    assert not any(line.startswith(("status:", "id:")) for line in lines)
    fm, _, _ = nf.parse_frontmatter(out + "\nbody")
    assert fm["title"] == "x\nstatus: obsolete"
    assert fm["tags"] == ["a]\nid: evil"]


def test_guard_field_blocks_section_injection():
    assert nf.guard_field("ok\n## 相关\n- [[x]]") == "ok\n### 相关\n- [[x]]"
    assert nf.guard_field("# title") == "### title"


def test_safe_segment():
    assert nf.safe_project("../../etc") not in ("..", "")
    assert "/" not in nf.safe_project("a/b")
    assert nf.safe_project("..") == "通用-未定"
    assert nf.safe_title("t\nstatus: x") == "t-status- x"


def test_score_works_for_chinese():
    n = {"title": "部署门禁", "scene": "API 主机 部署时", "practice": "", "reason": ""}
    assert nf.score("部署", n) > 0
    assert nf.score("无关话题", n) == 0


def test_slugify_keeps_ascii_and_hashes_cjk():
    assert nf.slugify("Only HTTPS") == "only-https"
    assert nf.slugify("") == "note"
    a, b = nf.slugify("HTTPS 证书"), nf.slugify("HTTPS 端口")
    assert a.startswith("https-") and b.startswith("https-") and a != b
    assert nf.slugify("部署门禁") == nf.slugify("部署门禁") != nf.slugify("日志轮转")
    assert nf.slugify("部署门禁").startswith("n-")
