"""TopicResolver: vault project paths ↔ Hindsight document_id."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Fixed global topic — every session/project may contribute.
GLOBAL_AGENT_TIPS_ID = "topic/agent-usage-tips"
GLOBAL_AGENT_TIPS_TITLE = "agent使用技巧"

# Preferred vault path; alias checked on resolve.
DEFAULT_AGENT_TIPS_RELPATH = "00-系统/agent使用技巧.md"
AGENT_TIPS_ALIASES = (
    "00-系统/agent使用技巧.md",
    "Agent使用技巧.md",
    "agent使用技巧.md",
)


def slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", s, flags=re.UNICODE)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "unnamed"


@dataclass(frozen=True)
class TopicRef:
    document_id: str
    title: str
    vault_relpath: str
    kind: str  # "global" | "project"

    @property
    def is_global(self) -> bool:
        return self.kind == "global"


class TopicResolver:
    """Map project directory names to topic document_ids and vault note paths."""

    def __init__(
        self,
        vault_root: Path | str,
        *,
        projects_dirname: str = "项目",
        agent_tips_relpath: str = DEFAULT_AGENT_TIPS_RELPATH,
    ) -> None:
        self.vault_root = Path(vault_root)
        self.projects_dirname = projects_dirname
        self.agent_tips_relpath = agent_tips_relpath

    def agent_tips(self) -> TopicRef:
        rel = self.agent_tips_relpath
        for alias in AGENT_TIPS_ALIASES:
            if (self.vault_root / alias).exists():
                rel = alias
                break
        return TopicRef(
            document_id=GLOBAL_AGENT_TIPS_ID,
            title=GLOBAL_AGENT_TIPS_TITLE,
            vault_relpath=rel,
            kind="global",
        )

    def project_topic(self, project_name: str) -> TopicRef:
        slug = slugify(project_name)
        base = Path(self.projects_dirname) / project_name
        # Prefer 记忆.md, then PROJECT.md
        for name in ("记忆.md", "PROJECT.md", "记忆/README.md"):
            candidate = base / name
            if (self.vault_root / candidate).exists():
                rel = str(candidate)
                break
        else:
            rel = str(base / "记忆.md")
        return TopicRef(
            document_id=f"topic/project/{slug}",
            title=project_name,
            vault_relpath=rel,
            kind="project",
        )

    def resolve_for_session(
        self,
        *,
        project: str | None = None,
        always_include_agent_tips: bool = True,
    ) -> list[TopicRef]:
        """Topics a distill pass should consider merging into."""
        out: list[TopicRef] = []
        if always_include_agent_tips:
            out.append(self.agent_tips())
        if project and project.strip():
            out.append(self.project_topic(project.strip()))
        return out

    def list_known_topics(self) -> list[TopicRef]:
        topics = [self.agent_tips()]
        projects_root = self.vault_root / self.projects_dirname
        if projects_root.is_dir():
            for p in sorted(projects_root.iterdir()):
                if p.is_dir() and not p.name.startswith("."):
                    topics.append(self.project_topic(p.name))
        return topics
