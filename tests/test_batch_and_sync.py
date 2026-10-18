from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

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
