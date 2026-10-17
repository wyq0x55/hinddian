"""Stub: push Obsidian topic docs to Hindsight retain/forget by document_id.

Authority stays in Obsidian. Call retain after human confirms a topic note;
call forget when the note is deleted. Do not write vault from Hindsight.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import Settings, get_settings
from .topics import TopicRef

log = logging.getLogger("hinddian.sync_hindsight")


class HindsightClient(Protocol):
    def retain(self, document_id: str, content: str, *, metadata: dict | None = None) -> None: ...
    def forget(self, document_id: str) -> None: ...


@dataclass
class StubHindsightClient:
    """No-op / log-only client for local scaffold."""

    base_url: str
    api_key: str | None = None

    def retain(self, document_id: str, content: str, *, metadata: dict | None = None) -> None:
        log.info(
            "STUB retain document_id=%s bytes=%d meta=%s → %s",
            document_id,
            len(content.encode("utf-8")),
            metadata,
            self.base_url,
        )

    def forget(self, document_id: str) -> None:
        log.info("STUB forget document_id=%s → %s", document_id, self.base_url)


def read_topic_markdown(vault_root: Path, ref: TopicRef) -> str | None:
    path = vault_root / ref.vault_relpath
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def sync_topic_to_hindsight(
    ref: TopicRef,
    *,
    settings: Settings | None = None,
    client: HindsightClient | None = None,
) -> str:
    """Retain topic markdown under its document_id. Returns status string."""
    settings = settings or get_settings()
    client = client or StubHindsightClient(
        base_url=settings.hindsight_base_url,
        api_key=settings.hindsight_api_key,
    )
    content = read_topic_markdown(settings.vault_root, ref)
    if content is None:
        return "missing_vault_file"
    client.retain(
        ref.document_id,
        content,
        metadata={"title": ref.title, "kind": ref.kind, "vault_relpath": ref.vault_relpath},
    )
    return "retained_stub"


def forget_topic(
    document_id: str,
    *,
    settings: Settings | None = None,
    client: HindsightClient | None = None,
) -> str:
    settings = settings or get_settings()
    client = client or StubHindsightClient(
        base_url=settings.hindsight_base_url,
        api_key=settings.hindsight_api_key,
    )
    client.forget(document_id)
    return "forgotten_stub"
