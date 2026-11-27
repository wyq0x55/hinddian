"""Read the host's final visible reply and extract the four closing sections."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

HEADINGS = ("原行为", "改进", "取舍", "验证")
_NAMES = "|".join(HEADINGS)
_HEADING = re.compile(
    rf"^[ \t\u3000]{{0,3}}"
    rf"(?:\*\*[ \t\u3000]*(?P<bold>{_NAMES})[ \t\u3000]*[:：]?[ \t\u3000]*\*\*|(?P<plain>{_NAMES}))"
    r"(?:[ \t\u3000]*[:：][ \t\u3000]*|[ \t\u3000]+|(?<=\*\*)|$)(?P<body>.*)$"
)


class MarkdownParserUnavailable(ImportError):
    pass


@lru_cache(maxsize=1)
def _markdown():
    try:
        from markdown_it import MarkdownIt
    except ImportError as exc:
        raise MarkdownParserUnavailable("markdown-it-py is unavailable") from exc
    return MarkdownIt("commonmark")


def _visible_text(tokens):
    parts = []
    for token in tokens:
        if token.type in ("text", "code_inline"):
            parts.append(token.content)
        elif token.type == "image":
            parts.append(_visible_text(token.children or ()))
    return "".join(parts)


def _other_heading(tokens, *, heading):
    for start, token in enumerate(tokens):
        if token.type not in ("em_open", "strong_open"):
            continue
        if _visible_text(tokens[:start]).strip():
            break
        closing_type = token.type.replace("_open", "_close")
        for end in range(start + 1, len(tokens)):
            if tokens[end].type == closing_type and tokens[end].level == token.level:
                label = _visible_text(tokens[start + 1:end]).strip().rstrip("：:")
                return label == "其他" or ("附录" in label and not _visible_text(tokens[end + 1:]).strip())
        break
    if heading:
        label = _visible_text(tokens).strip().rstrip("：:")
        return label == "其他" or "附录" in label
    return False


def _candidate_lines(tokens, lines):
    for block, inline in zip(tokens, tokens[1:]):
        if block.level != 0 or block.type not in ("heading_open", "paragraph_open") or inline.type != "inline":
            continue
        start, end = inline.map
        children = inline.children or []
        if block.type == "heading_open":
            if end == start + 1:
                yield start, block.map[1], inline.content, children, True
            continue
        groups = []
        group = []
        row = start
        group_start = start
        continued = False
        opaque_rows = []
        for token in children:
            if token.type in ("softbreak", "hardbreak"):
                if not (continued or token.level):
                    groups.append((group_start, row + 1, group))
                row += 1
                group_start, group, continued = row, [], bool(token.level)
            else:
                group.append(token)
                if token.type == "html_inline":
                    row += token.content.count("\n")
                elif token.type in ("code_inline", "link_open", "link_close", "image"):
                    opaque_rows.append(group_start)
        if not continued:
            groups.append((group_start, row + 1, group))
        gap = end - (row + 1)
        if gap < 0 or (gap and not opaque_rows):
            continue
        for begin, after, group in groups:
            if gap:
                if opaque_rows[0] <= begin <= opaque_rows[-1]:
                    continue
                if begin > opaque_rows[-1]:
                    begin += gap
                    after += gap
            source = lines[begin] if after == begin + 1 else ""
            yield begin, after, source, group, False


def closing(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    tokens = _markdown().parse(text)
    sections = {}
    active = None
    content_start = 0
    for start, end, source, inline, is_heading in _candidate_lines(tokens, lines):
        heading = _HEADING.match(source)
        if not heading and (active is None or not _other_heading(inline, heading=is_heading)):
            continue
        if active:
            sections[active].extend(lines[content_start:start])
        if heading:
            active = heading["bold"] or heading["plain"]
            if active in sections:
                sections = {}
            value = heading["body"].strip()
            sections[active] = [value] if value else []
        else:
            active = None
        content_start = end
    if active:
        sections[active].extend(lines[content_start:])
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


def _last_assistant(messages) -> tuple[str, str]:
    if not isinstance(messages, list):
        return "", ""
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
                message_id = next((message[key] for key in ("id", "message_id", "uuid")
                                   if isinstance(message.get(key), str) and message[key].strip()), "")
                return text, message_id
    return "", ""


def _transcript(path: Path) -> tuple[str, str]:
    if not path.is_file():
        raise ValueError("transcript must be a regular file")
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
            if event.get("uuid") and not message.get("uuid"):
                message = {**message, "uuid": event["uuid"]}
            messages.append(message)
    return _last_assistant(messages)


def final_reply(payload: dict) -> str:
    return final_message(payload)[0]


def final_message(payload: dict) -> tuple[str, str]:
    path = payload.get("transcript_path") or payload.get("transcriptPath")
    for key in ("last_assistant_message", "assistant_message", "response", "completion", "output"):
        message = payload.get(key)
        if isinstance(message, dict):
            text, message_id = _last_assistant([{**message, "role": "assistant"}])
        else:
            text, message_id = _text(message), ""
        if not text:
            continue
        if message_id or any(isinstance(payload.get(field), str) and payload[field].strip()
                             for field in ("turn_id", "turnId", "message_id")):
            return text, message_id
        lines = text.strip().splitlines()
        message_text, message_id = _last_assistant(payload.get("messages"))
        if message_id and message_text.strip().splitlines() == lines:
            return text, message_id
        if path:
            try:
                transcript_text, message_id = _transcript(Path(path))
            except (OSError, TypeError, ValueError):
                pass
            else:
                if transcript_text.strip().splitlines() == lines:
                    return text, message_id
        return text, ""
    if path:
        return _transcript(Path(path))
    result = _last_assistant(payload.get("messages"))
    if result[0]:
        return result
    turn = os.environ.get("MAGPIE_TURN_TEXT") or payload.get("turn_text") or payload.get("transcript")
    if isinstance(turn, list):
        return _last_assistant(turn)
    if isinstance(turn, str):
        if turn.lstrip().startswith(("{", "[")):
            try:
                envelope = json.loads(turn)
            except ValueError:
                return "", ""
            return final_message(envelope) if isinstance(envelope, dict) else _last_assistant(envelope)
        role = re.compile(r"(?im)^(user|human|assistant|model|tool|system|developer)\s*[:：][ \t]*")
        matches = list(role.finditer(turn))
        if matches and matches[-1][1].lower() in ("assistant", "model"):
            return turn[matches[-1].end():], ""
    return "", ""
