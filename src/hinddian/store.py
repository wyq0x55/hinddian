"""Filesystem/SQLite status store for the pipeline dashboard."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import Settings, get_settings
from .models import (
    DistillJob,
    FilterResult,
    InboxItem,
    JobStatus,
    MergeEvent,
    PipelineStats,
    TopicDocStatus,
)
from .topics import TopicResolver

_REASON_RE = re.compile(
    rb'"(?:quarantine_reason|filter_reason|skip_reason)"\s*:\s*"([^"\\]+)"'
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


class StatusStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    project TEXT,
                    title TEXT,
                    target_document_ids TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    error TEXT,
                    note TEXT
                );
                CREATE TABLE IF NOT EXISTS merges (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    session_id TEXT,
                    summary TEXT,
                    at TEXT,
                    status TEXT
                );
                CREATE TABLE IF NOT EXISTS topic_meta (
                    document_id TEXT PRIMARY KEY,
                    pending_merges INTEGER DEFAULT 0,
                    last_merged_at TEXT,
                    last_synced_to_hindsight TEXT,
                    hindsight_state TEXT DEFAULT 'unknown'
                );
                CREATE TABLE IF NOT EXISTS filter_counts (
                    reason TEXT PRIMARY KEY,
                    count INTEGER DEFAULT 0,
                    examples TEXT
                );
                """
            )

    def upsert_job(self, job: DistillJob) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, status, project, title, target_document_ids,
                                  created_at, updated_at, error, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  status=excluded.status,
                  project=excluded.project,
                  title=excluded.title,
                  target_document_ids=excluded.target_document_ids,
                  updated_at=excluded.updated_at,
                  error=excluded.error,
                  note=excluded.note
                """,
                (
                    job.id,
                    job.status.value,
                    job.project,
                    job.title,
                    json.dumps(job.target_document_ids, ensure_ascii=False),
                    _iso(job.created_at),
                    _iso(job.updated_at or _utcnow()),
                    job.error,
                    job.note,
                ),
            )

    def list_jobs(self, limit: int = 50) -> list[DistillJob]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY COALESCE(updated_at, created_at) DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_job(r) for r in rows]

    def _row_job(self, r: sqlite3.Row) -> DistillJob:
        return DistillJob(
            id=r["id"],
            status=JobStatus(r["status"]),
            project=r["project"],
            title=r["title"],
            target_document_ids=json.loads(r["target_document_ids"] or "[]"),
            created_at=_parse_dt(r["created_at"]),
            updated_at=_parse_dt(r["updated_at"]),
            error=r["error"],
            note=r["note"],
        )

    def list_merges(self, limit: int = 40) -> list[MergeEvent]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM merges ORDER BY at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            MergeEvent(
                id=r["id"],
                document_id=r["document_id"],
                session_id=r["session_id"],
                summary=r["summary"],
                at=_parse_dt(r["at"]) or _utcnow(),
                status=r["status"] or "pending",
            )
            for r in rows
        ]

    def add_merge(self, event: MergeEvent) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO merges
                  (id, document_id, session_id, summary, at, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.document_id,
                    event.session_id,
                    event.summary,
                    _iso(event.at),
                    event.status,
                ),
            )

    def filter_results(self) -> list[FilterResult]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT reason, count, examples FROM filter_counts ORDER BY count DESC"
            ).fetchall()
        out: list[FilterResult] = []
        for r in rows:
            examples = json.loads(r["examples"] or "[]")
            out.append(FilterResult(reason=r["reason"], count=r["count"], examples=examples))
        return out

    def set_filter_count(self, reason: str, count: int, examples: list[str] | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO filter_counts (reason, count, examples) VALUES (?, ?, ?)
                ON CONFLICT(reason) DO UPDATE SET count=excluded.count, examples=excluded.examples
                """,
                (reason, count, json.dumps(examples or [], ensure_ascii=False)),
            )

    def topic_meta(self, document_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM topic_meta WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        if not row:
            return {}
        return dict(row)

    def upsert_topic_meta(
        self,
        document_id: str,
        *,
        pending_merges: int | None = None,
        last_merged_at: datetime | None = None,
        last_synced_to_hindsight: datetime | None = None,
        hindsight_state: str | None = None,
    ) -> None:
        meta = self.topic_meta(document_id)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO topic_meta
                  (document_id, pending_merges, last_merged_at, last_synced_to_hindsight, hindsight_state)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                  pending_merges=excluded.pending_merges,
                  last_merged_at=excluded.last_merged_at,
                  last_synced_to_hindsight=excluded.last_synced_to_hindsight,
                  hindsight_state=excluded.hindsight_state
                """,
                (
                    document_id,
                    pending_merges if pending_merges is not None else meta.get("pending_merges", 0),
                    _iso(last_merged_at) if last_merged_at else meta.get("last_merged_at"),
                    _iso(last_synced_to_hindsight)
                    if last_synced_to_hindsight
                    else meta.get("last_synced_to_hindsight"),
                    hindsight_state if hindsight_state is not None else meta.get("hindsight_state", "unknown"),
                ),
            )


def _count_files(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    n = 0
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    n += 1
    except OSError:
        return 0
    return n


def scan_inbox(settings: Settings | None = None, limit: int = 30) -> list[InboxItem]:
    settings = settings or get_settings()
    inbox = settings.inbox_dir
    if not inbox.is_dir():
        return []
    items: list[InboxItem] = []
    try:
        files = sorted(
            (Path(e.path) for e in os.scandir(inbox) if e.is_file(follow_symlinks=False)),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return []
    for p in files:
        project = title = source = agent = session_id = None
        try:
            if p.suffix == ".json":
                data = json.loads(p.read_text(encoding="utf-8", errors="replace")[:200_000])
                if isinstance(data, dict):
                    project = data.get("project")
                    title = data.get("title")
                    source = data.get("source")
                    agent = data.get("agent")
                    session_id = data.get("session_id") or data.get("document_id") or data.get(
                        "otlp_session_key"
                    )
        except Exception:
            pass
        st = p.stat()
        items.append(
            InboxItem(
                id=p.name,
                source=source,
                agent=agent,
                project=project,
                title=title or p.stem,
                path=str(p),
                bytes=st.st_size,
                received_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
                session_id=session_id,
            )
        )
        if len(items) >= limit:
            break
    return items


def scan_quarantine_filters(
    settings: Settings | None = None,
    *,
    max_examples: int = 3,
) -> list[FilterResult]:
    """Derive filter reasons from quarantine JSON metadata (regex, no full parse)."""
    settings = settings or get_settings()
    qdir = settings.quarantine_dir
    if not qdir.is_dir():
        return []
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    try:
        entries = list(os.scandir(qdir))
    except OSError:
        return []
    for entry in entries:
        if not entry.is_file(follow_symlinks=False):
            continue
        name = entry.name
        reason = "(unspecified)"
        try:
            with open(entry.path, "rb") as f:
                data = f.read()
            m = _REASON_RE.search(data)
            if m:
                reason = m.group(1).decode("utf-8", errors="replace")
        except OSError:
            reason = "(read_error)"
        counts[reason] += 1
        if len(examples[reason]) < max_examples:
            examples[reason].append(name)
    return [
        FilterResult(reason=r, count=c, examples=examples.get(r, []))
        for r, c in counts.most_common()
    ]


def collect_filters(settings: Settings | None = None) -> list[FilterResult]:
    """Prefer live quarantine scan; fall back to sqlite filter_counts."""
    settings = settings or get_settings()
    live = scan_quarantine_filters(settings)
    if live:
        return live
    return StatusStore(settings.status_db).filter_results()


def build_topic_statuses(settings: Settings | None = None) -> list[TopicDocStatus]:
    settings = settings or get_settings()
    store = StatusStore(settings.status_db)
    vault = settings.vault_root if settings.vault_root else Path("/nonexistent-vault")
    resolver = TopicResolver(
        vault,
        projects_dirname=settings.projects_dirname,
        agent_tips_relpath=settings.agent_tips_relpath,
    )
    out: list[TopicDocStatus] = []
    for ref in resolver.list_known_topics():
        meta = store.topic_meta(ref.document_id)
        out.append(
            TopicDocStatus(
                document_id=ref.document_id,
                title=ref.title,
                vault_relpath=ref.vault_relpath,
                kind=ref.kind,
                pending_merges=int(meta.get("pending_merges") or 0),
                last_merged_at=_parse_dt(meta.get("last_merged_at")),
                last_synced_to_hindsight=_parse_dt(meta.get("last_synced_to_hindsight")),
                hindsight_state=meta.get("hindsight_state") or "unknown",
            )
        )
    return out


def compute_stats(settings: Settings | None = None) -> PipelineStats:
    settings = settings or get_settings()
    store = StatusStore(settings.status_db)
    jobs = store.list_jobs(limit=500)
    by = {s: 0 for s in JobStatus}
    for j in jobs:
        by[j.status] = by.get(j.status, 0) + 1
    topics = build_topic_statuses(settings)
    pending_ingests = sum(t.pending_merges for t in topics)
    return PipelineStats(
        inbox_count=_count_files(settings.inbox_dir),
        quarantine_count=_count_files(settings.quarantine_dir),
        processed_count=_count_files(settings.processed_dir),
        failed_count=_count_files(settings.failed_dir),
        jobs_pending=by.get(JobStatus.pending, 0),
        jobs_running=by.get(JobStatus.running, 0),
        jobs_done=by.get(JobStatus.done, 0),
        jobs_failed=by.get(JobStatus.failed, 0),
        topics_tracked=len(topics),
        pending_ingests=pending_ingests,
        demo=False,
        extras={
            "inbox_dir": str(settings.inbox_dir),
            "vault_mounted": bool(settings.vault_root and settings.vault_root.is_dir()),
        },
    )
