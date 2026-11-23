"""Read pipeline counts and draft details for the human dashboard."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import draft_store, note_format as nf, paths

_cache = nf.NoteCache()


def vault_stats() -> dict:
    vault = paths.vault_dir()
    notes = _cache.load(vault).values()
    active = [note for note in notes if note["status"] == "active"]
    return {"projects": len(draft_store.project_names(vault)),
            **{f"{kind}s": sum(note["type"] == kind for note in active) for kind in nf.NOTE_TYPES}}


def _draft_roots() -> dict[str, Path]:
    vault = paths.vault_dir()
    roots = {"pending": paths.drafts_dir(), "processed": paths.processed_dir()}
    for root in roots.values():
        paths.check_draft_root(root, vault)
    return roots


def batch_status() -> dict:
    roots = _draft_roots()
    pending, processed = roots["pending"], roots["processed"]
    projects = set(draft_store.pending_projects(pending)) | set(draft_store.pending_projects(processed))
    return {
        "projects": [{"project": project, "drafts": len(draft_store.draft_files(pending, project)),
                      "processed": len(draft_store.draft_files(processed, project))}
                     for project in sorted(projects)],
        "holdout": {project: len(draft_store.draft_files(pending / "holdout", project))
                    for project in draft_store.pending_projects(pending / "holdout")}
                   if not (pending / "holdout").is_symlink() else {},
    }


def list_drafts(*, project: str | None = None, status: str = "pending", limit: int = 100) -> list[dict]:
    limit = max(1, min(int(limit or 100), 500))
    rows = []
    for state, root in _draft_roots().items():
        if status not in (state, "all"):
            continue
        projects = [project] if project else draft_store.pending_projects(root)
        for name in projects:
            for path in draft_store.draft_files(root, name):
                if row := _draft_row(name, path, state):
                    rows.append(row)
    rows.sort(key=lambda row: row["mtime"], reverse=True)
    return rows[:limit]


def get_draft(draft_id: str) -> dict | None:
    if draft_id.count("/") != 1:
        return None
    project, name = draft_id.split("/")
    if not draft_store.valid_project(project) or not name or name.startswith(".") or "\\" in name:
        return None
    name = name.removesuffix(".md") + ".md"
    for status, root in _draft_roots().items():
        for path in draft_store.draft_files(root, project):
            if path.name == name:
                return _draft_row(project, path, status, detail=True)
    return None


def _draft_row(project: str, path: Path, status: str, *, detail: bool = False) -> dict | None:
    try:
        stat = path.stat()
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    parsed = nf.parse_frontmatter(text)
    fm, _, body = parsed if parsed else ({}, {}, text)
    title = str(fm.get("title") or "").strip()
    if not title:
        title = next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), path.stem)
    row = {"id": f"{project}/{path.name}", "project": project, "name": path.name, "title": title,
           "mtime": dt.datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
           "status": status, "snippet": " ".join(body.split())[:220], "bytes": stat.st_size}
    for key in ("session_id", "jev_source", "origin", "created"):
        row[key] = str(fm.get(key) or "").strip() or None
    if detail:
        row["body"] = body.strip()
    return row
