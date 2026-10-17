"""Filesystem/SQLite status store for the pipeline dashboard."""

from __future__ import annotations

import json
import sqlite3
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
    return sum(1 for p in directory.iterdir() if p.is_file())


def scan_inbox(settings: Settings | None = None, limit: int = 30) -> list[InboxItem]:
    settings = settings or get_settings()
    inbox = settings.inbox_dir
    if not inbox.is_dir():
        return []
    items: list[InboxItem] = []
    files = sorted(inbox.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files:
        if not p.is_file():
            continue
        project = title = source = agent = session_id = None
        try:
            if p.suffix == ".json":
                data = json.loads(p.read_text(encoding="utf-8", errors="replace")[:200_000])
                if isinstance(data, dict):
                    project = data.get("project")
                    title = data.get("title")
                    source = data.get("source")
                    agent = data.get("agent")
                    session_id = data.get("session_id") or data.get("document_id")
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


def build_topic_statuses(settings: Settings | None = None) -> list[TopicDocStatus]:
    settings = settings or get_settings()
    store = StatusStore(settings.status_db)
    resolver = TopicResolver(
        settings.vault_root,
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
    )


def seed_demo_if_empty(settings: Settings | None = None) -> bool:
    """Populate demo rows when USE_DEMO_DATA and store has no jobs."""
    settings = settings or get_settings()
    if not settings.use_demo_data:
        return False
    store = StatusStore(settings.status_db)
    if store.list_jobs(limit=1):
        return False

    now = _utcnow()
    demo_jobs = [
        DistillJob(
            id="job-demo-001",
            status=JobStatus.done,
            project="笔记系统",
            title="OTLP 去重与 flush 规则",
            target_document_ids=["topic/project/笔记系统", "topic/agent-usage-tips"],
            created_at=now,
            updated_at=now,
            note="已合并到主题「笔记系统」+ agent使用技巧",
        ),
        DistillJob(
            id="job-demo-002",
            status=JobStatus.running,
            project="hinddian",
            title="仪表盘骨架",
            target_document_ids=["topic/project/hinddian", "topic/agent-usage-tips"],
            created_at=now,
            updated_at=now,
        ),
        DistillJob(
            id="job-demo-003",
            status=JobStatus.pending,
            project="WorkBuddy签到",
            title="刷新失败排查片段",
            target_document_ids=["topic/project/workbuddy签到"],
            created_at=now,
            updated_at=now,
        ),
        DistillJob(
            id="job-demo-004",
            status=JobStatus.failed,
            project=None,
            title="过短会话",
            target_document_ids=[],
            created_at=now,
            updated_at=now,
            error="content_too_short",
        ),
    ]
    for j in demo_jobs:
        store.upsert_job(j)

    store.set_filter_count("smoke_test_title", 12, ["冒烟-勿合并", "concurrent-test-3"])
    store.set_filter_count("content_too_short", 8, ["sess-aa11"])
    store.set_filter_count("distill_prompt_echo", 3, [])
    store.set_filter_count("duplicate_1h", 5, ["otlp-dup-…"])

    store.add_merge(
        MergeEvent(
            id="merge-demo-1",
            document_id="topic/agent-usage-tips",
            session_id="sess-magpie-42",
            summary="Magpie Library 用 Hindsight Recall MCP，人读仍走 Obsidian",
            at=now,
            status="applied",
        )
    )
    store.add_merge(
        MergeEvent(
            id="merge-demo-2",
            document_id="topic/project/笔记系统",
            session_id="sess-otlp-9",
            summary="flush-on-receive：按 session.id 立刻写 inbox",
            at=now,
            status="pending",
        )
    )
    store.upsert_topic_meta(
        "topic/agent-usage-tips",
        pending_merges=1,
        last_merged_at=now,
        hindsight_state="dirty",
    )
    store.upsert_topic_meta(
        "topic/project/笔记系统",
        pending_merges=2,
        last_merged_at=now,
        last_synced_to_hindsight=now,
        hindsight_state="synced",
    )
    return True


def demo_inbox() -> list[InboxItem]:
    now = _utcnow()
    return [
        InboxItem(
            id="demo-inbox-1.json",
            source="otlp",
            agent="magpie@dmit",
            project="hinddian",
            title="主题记忆讨论",
            bytes=18420,
            received_at=now,
            session_id="sess-demo-1",
        ),
        InboxItem(
            id="demo-inbox-2.json",
            source="grok-export",
            agent="grok@box",
            project="笔记系统",
            title="Hindsight MCP 握手",
            bytes=9200,
            received_at=now,
            session_id="sess-demo-2",
        ),
        InboxItem(
            id="demo-inbox-3.json",
            source="otlp",
            agent="cursor@home",
            project=None,
            title="(未标项目)",
            bytes=2100,
            received_at=now,
        ),
    ]


def demo_topics() -> list[TopicDocStatus]:
    now = _utcnow()
    return [
        TopicDocStatus(
            document_id="topic/agent-usage-tips",
            title="agent使用技巧",
            vault_relpath="00-系统/agent使用技巧.md",
            kind="global",
            pending_merges=1,
            last_merged_at=now,
            hindsight_state="dirty",
        ),
        TopicDocStatus(
            document_id="topic/project/笔记系统",
            title="笔记系统",
            vault_relpath="项目/笔记系统/记忆.md",
            kind="project",
            pending_merges=2,
            last_merged_at=now,
            last_synced_to_hindsight=now,
            hindsight_state="synced",
        ),
        TopicDocStatus(
            document_id="topic/project/hinddian",
            title="hinddian",
            vault_relpath="项目/hinddian/记忆.md",
            kind="project",
            pending_merges=0,
            hindsight_state="unknown",
        ),
    ]


def demo_stats() -> PipelineStats:
    return PipelineStats(
        inbox_count=3,
        quarantine_count=28,
        processed_count=140,
        failed_count=2,
        jobs_pending=1,
        jobs_running=1,
        jobs_done=1,
        jobs_failed=1,
        topics_tracked=3,
        pending_ingests=3,
        demo=True,
        extras={"note": "演示数据 — 接上真实 INBOX_DIR 后自动切换"},
    )
