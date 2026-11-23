"""Read the host's final visible reply and extract the four closing sections."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

HEADINGS = ("原行为", "改进", "取舍", "验证")
_NAMES = "|".join(HEADINGS)
_HEADING = re.compile(
    rf"^[ \t\u3000]{{0,3}}(?:#{{1,6}}[ \t\u3000]+)?"
    rf"(?:\*\*[ \t\u3000]*(?P<bold>{_NAMES})[ \t\u3000]*[:：]?[ \t\u3000]*\*\*|(?P<plain>{_NAMES}))"
    r"(?:[ \t\u3000]*[:：][ \t\u3000]*|[ \t\u3000]+|(?<=\*\*)|$)(?P<body>.*)$"
)
_OTHER_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t\u3000]+")
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})(.*)$")


def closing(text: str) -> str:
    sections = {}
    active = None
    fence = ""
    for line in text.splitlines():
        if mark := _FENCE.match(line):
            run, tail = mark.groups()
            if not fence:
                fence = run
            elif run.startswith(fence) and not tail.strip():
                fence = ""
            if active:
                sections[active].append(line)
            continue
        heading = _HEADING.match(line) if not fence else None
        if heading:
            active = heading["bold"] or heading["plain"]
            if active in sections:
                sections = {}
            value = re.sub(r"[ \t\u3000]+#+[ \t\u3000]*$", "", heading["body"]).strip()
            sections[active] = [value] if value else []
        elif not fence and _OTHER_HEADING.match(line) and active:
            active = None
        elif active:
            sections[active].append(line)
    if set(sections) != set(HEADINGS) or any(not any(line.strip() for line in lines) for lines in sections.values()):
        return ""
    return "\n\n".join("## " + heading + "\n" + "\n".join(sections[heading]).strip() for heading in HEADINGS)


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part if isinstance(part, str) else part["text"] for part in content
                         if isinstance(part, str) or (isinstance(part, dict)
                            and part.get("type") in (None, "text", "output_text")
                            and isinstance(part.get("text"), str)))
    return ""


def _last_assistant(messages) -> str:
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("isMeta"):
            continue
        role = message.get("role") or message.get("type")
        if role in ("user", "human"):
            break
        if role not in ("assistant", "model", "ai", "bot"):
            continue
        if message.get("phase") not in ("analysis", "commentary") and message.get("stop_reason") != "tool_use":
            content = message.get("content") or message.get("text")
            if text := _text(content):
                return text
    return ""


def _transcript(path: Path) -> str:
    with path.open("rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        start = max(0, size - 2_000_000)
        stream.seek(start)
        if start:
            stream.readline()
        raw = stream.read(2_000_000).decode("utf-8")
    messages = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("isMeta"):
            continue
        if event.get("type") in ("user", "assistant"):
            message = event.get("message")
        elif event.get("type") == "response_item":
            message = event.get("payload")
            if not isinstance(message, dict) or message.get("type") != "message":
                continue
        else:
            continue
        if isinstance(message, dict):
            messages.append(message)
    return _last_assistant(messages)


def final_reply(payload: dict) -> str:
    for key in ("last_assistant_message", "assistant_message", "response", "completion", "output"):
        if text := _text(payload.get(key)):
            return text
    if path := payload.get("transcript_path") or payload.get("transcriptPath"):
        return _transcript(Path(path))
    if text := _last_assistant(payload.get("messages")):
        return text
    turn = os.environ.get("MAGPIE_TURN_TEXT") or payload.get("turn_text") or payload.get("transcript")
    if isinstance(turn, list):
        return _last_assistant(turn)
    if isinstance(turn, str):
        if turn.lstrip().startswith(("{", "[")):
            try:
                envelope = json.loads(turn)
            except ValueError:
                return ""
            return final_reply(envelope) if isinstance(envelope, dict) else _last_assistant(envelope)
        role = re.compile(r"(?im)^(user|human|assistant|model|tool|system|developer)\s*[:：][ \t]*")
        matches = list(role.finditer(turn))
        if matches and matches[-1][1].lower() in ("assistant", "model"):
            return turn[matches[-1].end():]
    return ""
