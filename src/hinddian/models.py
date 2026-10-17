from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"


class InboxItem(BaseModel):
    id: str
    source: str | None = None
    agent: str | None = None
    project: str | None = None
    title: str | None = None
    path: str | None = None
    bytes: int | None = None
    received_at: datetime | None = None
    session_id: str | None = None


class FilterResult(BaseModel):
    reason: str
    count: int
    examples: list[str] = Field(default_factory=list)


class DistillJob(BaseModel):
    id: str
    status: JobStatus
    project: str | None = None
    title: str | None = None
    target_document_ids: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    error: str | None = None
    note: str | None = None


class TopicDocStatus(BaseModel):
    document_id: str
    title: str
    vault_relpath: str
    kind: str
    pending_merges: int = 0
    last_merged_at: datetime | None = None
    last_synced_to_hindsight: datetime | None = None
    hindsight_state: str = "unknown"  # unknown | synced | dirty | forgotten


class MergeEvent(BaseModel):
    id: str
    document_id: str
    session_id: str | None = None
    summary: str
    at: datetime
    status: str = "pending"  # pending | applied | rejected


class PipelineStats(BaseModel):
    inbox_count: int = 0
    quarantine_count: int = 0
    processed_count: int = 0
    failed_count: int = 0
    jobs_pending: int = 0
    jobs_running: int = 0
    jobs_done: int = 0
    jobs_failed: int = 0
    topics_tracked: int = 0
    pending_ingests: int = 0
    demo: bool = False
    extras: dict[str, Any] = Field(default_factory=dict)
