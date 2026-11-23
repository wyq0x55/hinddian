"""Append-only hook events and resumable, redacted transcript ingestion."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import time
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

if __package__:
    from .redaction import redact
else:
    from redaction import redact

_BLOCK = re.compile(
    r"<(/?)(private|system(?:[-_]reminder)?|environment_context|hinddian_[\w-]+|"
    r"user_instructions|developer(?:_instructions)?|permissions|skills_instructions|collaboration_mode|"
    r"local-command-[\w-]+|command-(?:name|message|args)|"
    r"think(?:ing)?|analysis|reasoning|tool(?:_call|_use|_result)?|function_(?:call|result))(?:\s[^>]*)?>",
    re.I,
)
_ROLE = re.compile(
    r"(?im)^(?:#{1,3}[ \t]+)?\[?(user|human|assistant|model|system|developer|tool|function|thinking|reasoning)"
    r"(?:[ \t]+(?:message|role))?\]?[:：][ \t]*"
)
_VISIBLE = {"user", "assistant"}
_TEXT_TYPES = {"text", "input_text", "output_text"}
_LEGACY_TRANSCRIPT_BYTES = 2_000_000
_CREDENTIAL = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)|"
    r"(?i:\bbearer[ \t]+[A-Za-z0-9_.=-]{12,})", re.S,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def write_text(path: Path, text: str, *, replace: bool = True) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        try:
            handle.write(text)
            handle.close()
            if replace:
                os.replace(temp, path)
            else:
                try:
                    os.link(temp, path)
                except FileExistsError:
                    pass
        finally:
            temp.unlink(missing_ok=True)


def write_json(path: Path, data: object, *, replace: bool = True) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False) + "\n", replace=replace)


def visible(message: dict) -> tuple[str, str] | None:
    role = message.get("role")
    if role not in _VISIBLE or message.get("phase") not in (None, "commentary", "final_answer"):
        return None
    text = message.get("content")
    if isinstance(text, list):
        text = "\n".join(part["text"] for part in text if isinstance(part, dict)
                         and part.get("type") in _TEXT_TYPES and isinstance(part.get("text"), str))
    if isinstance(text, str) and text.strip():
        return role, text
    return None


def clean(text: str, hidden: list[str]) -> str:
    parts = []
    end = 0
    for match in _BLOCK.finditer(text):
        if not hidden:
            parts.append(text[end:match.start()])
        end = match.end()
        name = match[2].lower()
        if match[1]:
            if hidden and hidden[-1] == name:
                hidden.pop()
        else:
            if not hidden and name == "private":
                parts.append("[private]")
            hidden.append(name)
    if not hidden:
        parts.append(text[end:])
    return redact(_CREDENTIAL.sub("[REDACTED]", "".join(parts))).strip()


def inline_messages(data: dict, supplied_turn: str = "") -> list[dict]:
    pairs = []
    turn = supplied_turn or data.get("turn_text") or data.get("transcript")
    messages = data.get("messages")
    if isinstance(messages, list) and not supplied_turn:
        pairs = [pair for item in messages if isinstance(item, dict) and (pair := visible(item))]
    elif isinstance(turn, str) and turn:
        turn = clean(turn, [])
        markers = list(_ROLE.finditer(turn))
        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(turn)
            role = marker[1].lower()
            role = {"human": "user", "model": "assistant"}.get(role, role)
            pairs.append((role, turn[marker.end():end]))
    else:
        pairs = [
            ("user", data.get("prompt") or data.get("user_prompt") or data.get("last_user_message") or data.get("user_message")),
            ("assistant", data.get("last_assistant_message") or data.get("assistant_message") or data.get("response")
             or data.get("completion")),
        ]
    hidden: list[str] = []
    records = []
    for role, text in pairs:
        if role in _VISIBLE and isinstance(text, str) and (text := clean(text, hidden)):
            records.append({"role": role, "text": text})
    return records


def capture(root: Path, session_id: str, cwd: str, data: dict, supplied_turn: str = "", *, legacy: bool = False) -> Path | None:
    transcript = data.get("transcript_path") or data.get("transcriptPath")
    origin = None
    if isinstance(transcript, str) and transcript:
        path = Path(transcript).absolute()
        try:
            info = path.stat()
            if stat.S_ISREG(info.st_mode):
                origin = {"path": str(path), "end": info.st_size, "device": info.st_dev, "inode": info.st_ino}
        except OSError:
            pass
    messages = inline_messages(data, supplied_turn) if legacy or not origin else []
    if not (origin or messages):
        return None
    turn_id = data.get("turn_id") or data.get("turnId")
    captured = time.time_ns()
    event = f"turn-{digest(str(turn_id))}" if turn_id else f"{captured}-{uuid4().hex}"
    if origin:
        event = "source-" + digest(f"{origin['path']}:{origin['device']}:{origin['inode']}:{origin['end']}")
    path = root / ("session-" + digest(session_id)) / "events" / (event + ".json")
    if not path.exists():
        write_json(path, {"session_id": session_id, "project": clean(Path(cwd).name, []), "captured": captured,
                          "origin": origin, "messages": messages}, replace=False)
    return path


def _transcript_message(row: dict) -> tuple[str, str] | None:
    if row.get("type") == "response_item":
        row = row.get("payload")
        if not isinstance(row, dict):
            return None
    if row.get("type") == "message":
        return visible(row)
    if row.get("type") in _VISIBLE and not any(row.get(flag) for flag in ("isMeta", "isSidechain", "isCompactSummary")):
        message = row.get("message")
        if isinstance(message, dict):
            return visible(message)
    return None


def transcript_records(origin: dict, cursor: dict) -> Iterator[tuple[int, str, str]]:
    with Path(origin["path"]).open("rb") as handle:
        info = os.fstat(handle.fileno())
        if (info.st_dev, info.st_ino) != (origin["device"], origin["inode"]) or info.st_size < origin["end"]:
            raise ValueError("captured transcript was replaced or shortened")
        handle.seek(cursor["offset"])
        while handle.tell() < origin["end"]:
            offset = handle.tell()
            line = handle.readline(origin["end"] - offset)
            if not line:
                raise ValueError("captured transcript was shortened during reading")
            try:
                row = json.loads(line) if line.strip() else None
            except ValueError:
                if not line.endswith(b"\n"):
                    break
                raise
            cursor["offset"] = handle.tell()
            pair = _transcript_message(row) if isinstance(row, dict) else None
            if pair and (text := clean(pair[1], cursor["hidden"])):
                yield offset, pair[0], text


def legacy_messages(event: dict) -> list[dict]:
    origin = event["origin"]
    if event["messages"] or not origin or origin["end"] >= _LEGACY_TRANSCRIPT_BYTES:
        return event["messages"]
    recent: deque[dict] = deque(maxlen=2)
    for _, role, text in transcript_records(origin, {"offset": 0, "hidden": []}):
        recent.append({"role": role, "text": text})
    return list(recent)


def materialize(session: Path) -> tuple[str, str, list[dict]]:
    """Persist visible records before they reach the model. Offsets refer to host JSONL bytes."""
    events = sorted(((path.stem, json.loads(path.read_text(encoding="utf-8")))
                     for path in (session / "events").glob("*.json")), key=lambda pair: (pair[1]["captured"], pair[0]))
    if not events:
        raise ValueError("session has no captured events")
    meta = events[0][1]
    state_path = session / "source.json"
    previous = state_path.read_text(encoding="utf-8") if state_path.is_file() else ""
    state = json.loads(previous) if previous else {}
    records = state.get("records", {})
    cursors = state.get("cursors", {})
    for event_id, event in events:
        origin = event["origin"]
        if not origin:
            for index, message in enumerate(event["messages"], 1):
                position = f"{event_id}.{index}"
                records.setdefault(position, message)
            continue
        key = digest(f'{origin["path"]}:{origin["device"]}:{origin["inode"]}')
        cursor = cursors.setdefault(key, {"stream": len(cursors) + 1, "offset": 0, "hidden": []})
        if cursor["offset"] >= origin["end"]:
            continue
        for offset, role, text in transcript_records(origin, cursor):
            records[f"jsonl-{cursor['stream']}-{offset}"] = {"role": role, "text": text}
    updated = {"session_id": meta["session_id"], "records": records, "cursors": cursors}
    snapshot = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    if snapshot != previous:
        write_text(state_path, snapshot)
    return meta["session_id"], meta["project"], [dict(message, position=position) for position, message in records.items()]
