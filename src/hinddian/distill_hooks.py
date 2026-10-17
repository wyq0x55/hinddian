"""Stub: how distill should upsert into topic docs (never default per-session notes)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .topics import GLOBAL_AGENT_TIPS_ID, TopicRef, TopicResolver


@dataclass
class MergeProposal:
    """One distill output unit destined for a topic document."""

    document_id: str
    vault_relpath: str
    section_title: str
    markdown_body: str
    session_id: str | None = None
    rationale: str = ""


@dataclass
class DistillPlan:
    session_id: str | None
    project: str | None
    proposals: list[MergeProposal] = field(default_factory=list)
    skip_reason: str | None = None


def plan_merges(
    *,
    project: str | None,
    session_id: str | None,
    distilled_sections: dict[str, str],
    vault_root: Path | str,
    always_agent_tips: bool = True,
) -> DistillPlan:
    """Map LLM section outputs → topic merge proposals.

    Expected keys in distilled_sections (convention, not enforced yet):
      - agent_tips: fragments for topic/agent-usage-tips
      - project_memory: fragments for the project topic
      - (other keys ignored in stub)

    Never creates a per-session note path.
    """
    resolver = TopicResolver(vault_root)
    targets = resolver.resolve_for_session(
        project=project,
        always_include_agent_tips=always_agent_tips,
    )
    by_id = {t.document_id: t for t in targets}
    proposals: list[MergeProposal] = []

    tips = distilled_sections.get("agent_tips") or distilled_sections.get("agent使用技巧")
    if tips and GLOBAL_AGENT_TIPS_ID in by_id:
        ref = by_id[GLOBAL_AGENT_TIPS_ID]
        proposals.append(
            MergeProposal(
                document_id=ref.document_id,
                vault_relpath=ref.vault_relpath,
                section_title="来自会话",
                markdown_body=tips.strip(),
                session_id=session_id,
                rationale="通用 agent 使用技巧 → 固定全局主题",
            )
        )

    proj_body = distilled_sections.get("project_memory") or distilled_sections.get("项目记忆")
    if project and proj_body:
        ref = resolver.project_topic(project)
        proposals.append(
            MergeProposal(
                document_id=ref.document_id,
                vault_relpath=ref.vault_relpath,
                section_title="来自会话",
                markdown_body=proj_body.strip(),
                session_id=session_id,
                rationale=f"项目「{project}」主题 upsert",
            )
        )

    if not proposals:
        return DistillPlan(
            session_id=session_id,
            project=project,
            proposals=[],
            skip_reason="no_topic_sections",
        )
    return DistillPlan(session_id=session_id, project=project, proposals=proposals)


def apply_merge_stub(proposal: MergeProposal, vault_root: Path | str) -> str:
    """Append proposal body under a session heading. Stub — does not write yet."""
    path = Path(vault_root) / proposal.vault_relpath
    return f"STUB would append to {path} (document_id={proposal.document_id})"


def forbidden_session_note_path(session_id: str) -> None:
    """Explicitly document what we refuse to do by default."""
    raise RuntimeError(
        f"Refusing per-session note for {session_id!r}. "
        "Merge into topic documents instead (see plan_merges)."
    )
