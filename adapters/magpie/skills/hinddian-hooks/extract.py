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
    r"(?:#{1,6}[ \t\u3000]*\u3000[ \t\u3000]*)?"
    rf"(?:\*\*[ \t\u3000]*(?P<bold>{_NAMES})[ \t\u3000]*[:：]?[ \t\u3000]*\*\*|(?P<plain>{_NAMES}))"
    r"(?:[ \t\u3000]*[:：][ \t\u3000]*|[ \t\u3000]+|(?<=\*\*)|$)(?P<body>.*)$"
)
_BREAKS = ("softbreak", "hardbreak")


class MarkdownParserUnavailable(ImportError):
    pass


def _located_break(rule, newline_offset):
    """Keep the source offset of parser-emitted breaks without changing Markdown semantics."""
    def locate(state, silent):
        start = state.pos
        matched = rule(state, silent)
        if matched and not silent and state.tokens[-1].type in _BREAKS:
            state.tokens[-1].meta["after_newline"] = start + newline_offset + 1
        return matched

    return locate


@lru_cache(maxsize=1)
def markdown_parser():
    try:
        from markdown_it import MarkdownIt
        from markdown_it.rules_inline import escape, newline
    except ImportError as exc:
        raise MarkdownParserUnavailable("markdown-it-py is unavailable") from exc
    parser = MarkdownIt("commonmark").disable("inline")
    parser.inline.ruler.at("newline", _located_break(newline, 0))
    parser.inline.ruler.at("escape", _located_break(escape, 1))
    return parser


def _visible_text(tokens):
    parts = []
    for token in tokens:
        if token.type in ("text", "text_special", "code_inline"):
            parts.append(token.content)
        elif token.type == "image":
            parts.append(_visible_text(token.children or ()))
    return "".join(parts)


def _leading_emphasis(tokens):
    for start, token in enumerate(tokens):
        if token.type not in ("em_open", "strong_open"):
            continue
        if _visible_text(tokens[:start]).strip():
            break
        closing_type = token.type.replace("_open", "_close")
        for end in range(start + 1, len(tokens)):
            if tokens[end].type == closing_type and tokens[end].level == token.level:
                lead = _visible_text(tokens[start + 1:end]).strip().rstrip("：:")
                return lead, _visible_text(tokens[end + 1:]).strip()
        break
    return "", ""


def _other_heading(tokens, markup):
    """Recognize appendix titles and preserve prose after an emphasized ATX lead."""
    lead, suffix = _leading_emphasis(tokens)
    if lead == "其他":
        return True
    if markup:
        label = _visible_text(tokens).strip().rstrip("：:")
        if markup.startswith("#") and lead and suffix.endswith(("。", "！", "？", "!", "?")):
            return False
        return label == "其他" or "附录" in label
    return "附录" in lead and not suffix and not any(token.type in _BREAKS for token in tokens)


def _paragraph_lines(inline, lines):
    """Use exposed breaks to locate source lines within a fully parsed paragraph."""
    row, end = inline.map
    while row < end and not lines[row].strip():
        row += 1
    offset = group_start = 0
    children = inline.children
    for index, token in enumerate(children):
        if token.type not in _BREAKS or token.level:
            continue
        after_offset = token.meta["after_newline"]
        after_row = row + inline.content.count("\n", offset, after_offset)
        yield row, after_row, lines[row] if after_row == row + 1 else "", children[group_start:index], ""
        row, offset, group_start = after_row, after_offset, index + 1
    after_row = row + inline.content.count("\n", offset) + 1
    yield row, after_row, lines[row] if after_row == row + 1 else "", children[group_start:], ""


def _candidate_blocks(parser, text, lines):
    env = {}
    blocks = parser.parse(text, env)
    for index, block in enumerate(blocks):
        if block.level or block.type not in ("heading_open", "paragraph_open"):
            continue
        inline = blocks[index + 1]
        start, end = inline.map
        if block.type == "heading_open":
            if end == start + 1:
                parser.inline.parse(inline.content, parser, env, inline.children)
                yield start, block.map[1], inline.content, inline.children, block.markup
        elif (any(_HEADING.match(line) for line in lines[start:end])
              or (("*" in inline.content or "_" in inline.content)
                  and any(hint in inline.content for hint in ("附", "其", "&", "%")))):
            parser.inline.parse(inline.content, parser, env, inline.children)
            yield from _paragraph_lines(inline, lines)


def closing(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    sections = {}
    active = None
    content_start = 0
    for start, end, source, inline, markup in _candidate_blocks(markdown_parser(), text, lines):
        heading = _HEADING.match(source)
        if not heading and (active is None or not _other_heading(inline, markup)):
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
