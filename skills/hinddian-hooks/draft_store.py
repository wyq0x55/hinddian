"""Local draft writer shared by the capture hooks and HTTP collector."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

if __package__:
    from . import note_format as nf, paths
else:
    import note_format as nf
    import paths

DRAFT_META_KEYS = ("type", "confidence", "origin", "session_id", "jev_source", "turn_count", "finalize_reason")
_META_KEY = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


def valid_project(project: str) -> bool:
    return bool(project and not project.startswith(".") and nf.safe_project(project) == project)


def pending_projects(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir() and not path.is_symlink()
                  and path.name != "holdout" and valid_project(path.name))


def draft_files(root: Path, project: str) -> list[Path]:
    directory = root / project
    if not valid_project(project) or directory.is_symlink():
        return []
    return sorted(path for path in directory.glob("*.md") if path.is_file() and not path.is_symlink())


def project_names(vault: Path) -> list[str]:
    projects = vault / "项目"
    if not projects.is_dir() or not projects.resolve().is_relative_to(vault.resolve()):
        return []
    return sorted(p.name for p in projects.iterdir()
                  if p.is_dir() and not p.is_symlink() and not p.name.startswith(("_", ".")))


def save_payload(payload: dict) -> dict:
    meta = {key: payload[key] for key in DRAFT_META_KEYS if payload.get(key) is not None}
    if isinstance(payload.get("meta"), dict):
        meta = {**payload["meta"], **meta}
    return write_draft(
        paths.drafts_dir(), vault=paths.vault_dir(), project=payload.get("project") or "通用-未定",
        title=payload.get("title") or "session", body=payload.get("body") or "", meta=meta,
    )


def append_capture(root: Path, processed: Path, *, vault: Path, project: str, meta: dict,
                   turn: str, at: str, text: str) -> dict:
    for directory in (root, processed):
        paths.check_draft_root(directory, vault)
    if root.resolve().is_relative_to(processed.resolve()) or processed.resolve().is_relative_to(root.resolve()):
        raise ValueError("drafts and processed must be separate directories")
    project = nf.safe_project(project)
    if project == "holdout":
        project = "通用-未定"
    identity = [meta["session_id"], meta["host"]]
    if not meta["session_id"]:
        identity.append(turn)
    session = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
    revision = hashlib.sha256(json.dumps(meta, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    name = f"session-{session}-{revision}"
    with nf.vault_lock(timeout=0):
        for directory in (root, processed):
            if (directory / project).is_symlink():
                raise nf.UnsafePath("capture directory must not use a symlink")
            for candidate in (directory / project).glob(f"session-{session}-*.md"):
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                parsed = nf.parse_frontmatter(candidate.read_text(encoding="utf-8"))
                if parsed and isinstance(ids := parsed[0].get("turn_ids"), list) and turn in ids:
                    return {"path": str(candidate), "project": project, "duplicate": True}
        path = nf.within(root, f"{project}/{name}")
        if (root / project / f"{name}.md").is_symlink():
            raise nf.UnsafePath("capture file must not use a symlink")
        if path.exists():
            parsed = nf.parse_frontmatter(path.read_text(encoding="utf-8"))
            if not parsed or any(parsed[0].get(key) != value for key, value in meta.items()):
                raise ValueError("capture draft metadata changed")
            fields, raw, body = parsed
            items = [(key, value) for key, value in fields.items() if key != "turn_ids"]
            items.append(("turn_ids", [*fields["turn_ids"], turn]))
            front = nf.dump_frontmatter(items, orig=fields, raw=raw)
        else:
            front = nf.dump_frontmatter([("title", f"{project} 会话草稿"), ("project", project),
                                         ("origin", "turn-end"), *meta.items(), ("time", at), ("turn_ids", [turn])])
            body = f"\n# {project} 会话草稿\n"
        block = f"\n<!-- hinddian:turn {turn} {at} -->\n\n{text}\n"
        nf.write_atomic(path, front + "\n" + body.rstrip("\n") + "\n" + block)
    return {"path": str(path), "project": project, "duplicate": False}


def write_draft(
    root: Path, *, vault: Path, project: str, title: str, body: str, meta: dict | None = None,
) -> dict:
    """Atomically replace the draft for the same session and keep the original session ID."""
    paths.check_draft_root(root, vault)
    project = nf.safe_project(project)
    if project == "holdout":
        project = "通用-未定"
    title = nf.safe_title(title)
    meta = meta or {}
    sid = str(meta.get("session_id") or "").strip()
    if sid:
        safe_sid = "".join(char if char.isalnum() or char in "-_" else "_" for char in sid)[:80]
        if safe_sid != sid:
            safe_sid = f"{safe_sid[:63]}-{hashlib.sha256(sid.encode()).hexdigest()[:16]}"
        name = f"session-{safe_sid}"
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"{stamp}-{nf.slugify(title)[:40]}"
    today = dt.date.today().isoformat()
    items: list[tuple[str, Any]] = [
        ("title", title),
        ("project", project),
        ("origin", str(meta.get("origin") or ("session-finalize" if sid else "turn-end"))[:120]),
        ("created", today),
        ("updated", today),
    ]
    for key, value in meta.items():
        if key in ("title", "project", "body", "origin", "created", "updated") or not _META_KEY.fullmatch(key):
            continue
        if isinstance(value, (str, int, float, bool)):
            items.append((key, str(value)))
    text = nf.dump_frontmatter(items) + f"\n\n# {title}\n\n" + body.strip() + "\n"
    with nf.vault_lock():
        path = nf.within(root, f"{project}/{name}")
        paths.check_draft_root(path, vault)
        if (root / project).is_symlink() or (root / project / f"{name}.md").is_symlink():
            raise nf.UnsafePath("draft path must not use a symlink")
        nf.write_atomic(path, text)
    return {"ok": True, "path": str(path), "project": project,
            "session_id": sid or None, "jev_source": meta.get("jev_source"), "upsert": bool(sid)}
