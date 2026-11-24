"""Atomic-note format shared by the collector, batch engine and dashboard.

One implementation of: frontmatter parse/dump (unknown keys and unchanged values round-trip
verbatim), body sections (sections we don't manage survive a re-render), link resolution,
path safety, the vault write lock and a content-keyed parse cache.

Stdlib only, shared by hooks and the local batch engine.
"""
from __future__ import annotations

import contextlib
import copy
import errno
import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import tempfile
import threading
import time
from typing import Any, Iterator

if __package__:
    from . import paths
else:
    import paths

if os.name == "nt":
    import msvcrt
else:
    import fcntl

SKIP_DIRS = (".obsidian", "_归档", ".git", ".trash", "_模板")
FOLDER = {"decision": "决策", "lesson": "经验"}
NOTE_TYPES = ("tip", "decision", "lesson")

WIKI = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")

# Frontmatter keys render() owns; everything else in a note's frontmatter is carried through.
MANAGED_KEYS = (
    "id", "type", "project", "tags", "status", "related", "sources", "updated", "legacy_code", "origin",
)
FIELD_SECTIONS = {"场景": "scene", "做法": "practice", "理由": "reason", "影响 / 推广": "extra"}
GENERATED_PREAMBLE = "> 所属："
_H2 = re.compile(r"^## ([^\n]+)(?:\n|\Z)", re.M)
_CODE_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})(.*)$")


class VaultBusy(RuntimeError):
    pass


class UnsafePath(ValueError):
    pass


# ------------------------------------------------------------------ text helpers
_BAD_SEG = re.compile(r'[\\/:*?"<>|#\[\]^\x00-\x1f\x7f]')


def safe_segment(s: Any, fallback: str) -> str:
    """One path segment: no separators, no control chars, no leading/trailing dots ('..' → fallback)."""
    s = re.sub(r"\.{2,}", "-", _BAD_SEG.sub("-", str(s or ""))).strip(" .-\t")
    return s[:80] or fallback


def safe_title(t: Any) -> str:
    return safe_segment(t, "未命名")


def safe_project(p: Any, fallback: str = "通用-未定") -> str:
    return safe_segment(p, fallback)


def slugify(s: Any) -> str:
    """ASCII slug for ids / file names. Text with non-ASCII letters (Chinese titles) gets a short
    content hash, so different titles never collapse to the same id ("note", "https", …)."""
    s = str(s or "").strip()
    ascii_part = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:52]
    if not re.search(r"[^\x00-\x7f]", s):
        return ascii_part or "note"
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()[:6]
    return f"{ascii_part}-{h}" if ascii_part else f"n-{h}"


def unwiki(t: str) -> str:
    """Neutralise wikilinks in machine-written text (agent / LLM output) before it enters a note."""
    return WIKI.sub(lambda m: f"`{m.group(2) or m.group(1)}`", t or "")


def guard_field(t: str) -> str:
    """Field text must not open a new top-level/section heading, or the next parse splits it."""
    return re.sub(r"(?m)^#{1,2}(?=\s)", "###", (t or "").strip())


def within(root: pathlib.Path, rel: str) -> pathlib.Path:
    """`root/rel.md`, refusing anything that resolves outside root."""
    base = root.resolve()
    p = (root / (rel + ".md")).resolve()
    if base != p and base not in p.parents:
        raise UnsafePath(f"path escapes vault: {rel!r}")
    return p


# ------------------------------------------------------------------ frontmatter
def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        try:
            return json.loads(v)
        except ValueError:
            return v[1:-1]
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def _split_inline(s: str) -> list[str]:
    items, cur, quote, depth, esc = [], "", None, 0, False
    for ch in s:
        if quote:
            cur += ch
            if esc:
                esc = False
            elif ch == "\\" and quote == '"':
                esc = True
            elif ch == quote:
                quote = None
        elif ch in "\"'" and not cur.strip():
            quote = ch
            cur += ch
        elif ch == "[":
            depth += 1
            cur += ch
        elif ch == "]":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            items.append(cur)
            cur = ""
        else:
            cur += ch
    items.append(cur)
    return [_unquote(x) for x in items if x.strip()]


_KEY = re.compile(r"""^("(?:\\.|[^"\\])*"|'(?:''|[^'])*'|[^\s#?:][^:]*?):(?:[ \t]+(.*))?$""")
_BLOCK_ITEM = re.compile(r"^-(?:[ \t]|$)")


def yaml_comment(line: str) -> tuple[str, str]:
    quote = ""
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif quote == '"' and char == "\\":
            escaped = True
        elif char == quote:
            quote = ""
        elif not quote and char in "\"'" and (not index or line[index - 1] in " \t[:,"):
            quote = char
        elif not quote and char == "#" and (not index or line[index - 1].isspace()):
            value = line[:index].rstrip()
            return value, line[len(value):]
    return line, ""


def parse_frontmatter(text: str) -> tuple[dict[str, Any], dict[str, str], str] | None:
    """→ (values, raw_lines_per_key, body). Values are str or list[str]; structures we don't
    understand (nested maps, multi-line scalars) are kept only as raw text."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 3)
    if end < 0:
        if text.rstrip().endswith("\n---"):
            end = text.rstrip().rfind("\n---")
        else:
            return None
    lines = text[4:end].split("\n") if end > 3 else []
    body = text[end + 5 :]
    fm: dict[str, Any] = {}
    raw: dict[str, str] = {}
    i = 0
    while i < len(lines):
        m = _KEY.match(lines[i])
        if not m:
            i += 1
            continue
        key = _unquote(m.group(1).rstrip())
        val = yaml_comment(m.group(2) or "")[0].strip()
        j = i + 1
        while j < len(lines) and (lines[j].startswith((" ", "\t", "#"))
                                 or _BLOCK_ITEM.match(lines[j]) or not lines[j].strip()):
            j += 1
        while j > i + 1 and not lines[j - 1].strip():
            j -= 1
        block = lines[i:j]
        raw[key] = "\n".join(block)
        cont = [x for x in block[1:] if yaml_comment(x)[0].strip()]
        if not val and cont and all(x.lstrip().startswith("- ") or x.strip() == "-" for x in cont):
            fm[key] = [_unquote(yaml_comment(x.lstrip()[1:])[0]) for x in cont if x.lstrip()[1:].strip()]
        elif cont:
            fm[key] = None  # opaque; raw[key] carries it
        elif val.startswith("[") and val.endswith("]"):
            fm[key] = _split_inline(val[1:-1])
        else:
            fm[key] = _unquote(val)
        i = j
    return fm, raw, body


_PLAIN = re.compile(r"^[^\s\-?:,\[\]{}#&*!|>'\"%@`][^:#,\[\]{}\x00-\x1f\x7f]*$")
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~"}


def _q(v: Any) -> str:
    s = "" if v is None else str(v)
    if s and _PLAIN.match(s) and not s.endswith(" ") and s.lower() not in _RESERVED:
        return s
    return json.dumps(s, ensure_ascii=False)


def dump_value(key: str, v: Any) -> str:
    if isinstance(v, (list, tuple)):
        return f"{key}: [" + ", ".join(_q(x) for x in v) + "]"
    return f"{key}: {_q(v)}"


def dump_frontmatter(items: list[tuple[str, Any]], *, orig: dict | None = None, raw: dict | None = None) -> str:
    """Emit `---` block. A key whose value is unchanged from `orig` is written back verbatim."""
    out = ["---"]
    for k, v in items:
        if orig is not None and raw is not None and k in raw and orig.get(k, object()) == v:
            out.append(raw[k])
        else:
            out.append(dump_value(k, v))
    out.append("---")
    return "\n".join(out)


# ------------------------------------------------------------------ body
def unfenced_lines(body: str) -> Iterator[tuple[int, str]]:
    """Yield the source offset and text of each line outside fenced code."""
    start = 0
    fence = ""
    for line in body.splitlines(keepends=True):
        if mark := _CODE_FENCE.match(line):
            run, tail = mark.groups()
            if not fence:
                fence = run
            elif run.startswith(fence) and not tail.strip():
                fence = ""
        elif not fence:
            yield start, line
        start += len(line)


def section_parts(body: str) -> list[str]:
    """Split at level-two headings outside fenced code, retaining the complete input."""
    offsets = [0, *(start for start, line in unfenced_lines(body) if _H2.match(line))]
    return [body[left:right] for left, right in zip(offsets, [*offsets[1:], len(body)])]


def split_body(body: str) -> tuple[str | None, list[str], list[tuple[str, str, str]]]:
    """Return the title, preamble and sections with their original Markdown."""
    head, *parts = section_parts(body)
    title = None
    pre: list[str] = []
    for line in head.splitlines():
        if title is None and line.startswith("# "):
            title = line[2:].strip()
            continue
        if not line.startswith(GENERATED_PREAMBLE):
            pre.append(line)
    sections = []
    for markdown in parts:
        heading = _H2.match(markdown)
        sections.append((heading[1].strip(), markdown[heading.end():], markdown))
    return title, pre, sections


def parse_note(p: pathlib.Path, vault: pathlib.Path, *, text: str | None = None) -> dict | None:
    if text is None:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
    t = text
    parsed = parse_frontmatter(t)
    if not parsed:
        return None
    fm, raw, body = parsed
    if not isinstance(fm.get("id"), str) or not fm["id"]:
        return None
    title, pre, sections = split_body(body)

    def lst(v: Any) -> list[str]:
        if isinstance(v, list):
            return [str(x) for x in v if str(x).strip()]
        v = str(v or "").strip()
        return re.findall(r"\[\[[^\]]+\]\]", v) or ([v] if v else [])

    def s(k: str) -> str:
        v = fm.get(k)
        return v if isinstance(v, str) else ""

    try:
        rel = p.relative_to(vault).as_posix()[:-3]
    except ValueError:
        rel = str(p)[:-3]
    secd = {h: c.strip() for h, c, _ in sections}
    n = {
        "path": rel,
        "id": fm["id"],
        "type": s("type"),
        "project": s("project"),
        "tags": lst(fm.get("tags")),
        "status": s("status") or "active",
        "sources": lst(fm.get("sources")),
        "related_raw": lst(fm.get("related")),
        "legacy_code": s("legacy_code"),
        "origin": s("origin"),
        "updated": s("updated"),
        "title": title or p.stem,
        "text": t,
        "_fm": fm,
        "_raw": raw,
        "_preamble": "\n".join(pre).strip("\n").split("\n") if any(line.strip() for line in pre) else [],
        "_sections": [markdown for h, _, markdown in sections if h not in FIELD_SECTIONS and h != "相关"],
        "_related_body": "".join(markdown for h, _, markdown in sections if h == "相关"),
    }
    for h, k in FIELD_SECTIONS.items():
        n[k] = secd.get(h, "")
        if n[k] == "（待补）":
            n[k] = ""
    return n


def link_target(link: str) -> str:
    m = re.match(r"\[\[([^\]|]+)", link or "")
    return m.group(1) if m else (link or "")


def link_of(n: dict) -> str:
    return f"[[{n['path']}|{n['title']}]]"


def resolve_links(notes: dict[str, dict]) -> None:
    """Fill related note IDs from the raw links in each note.
    Links we can't resolve are kept verbatim so a re-render never silently drops them."""
    bypath = {n["path"]: n["id"] for n in notes.values()}

    def one(raw: str) -> str:
        if raw in notes:
            return raw
        return bypath.get(link_target(raw), raw)

    for n in notes.values():
        n["related"] = list(dict.fromkeys(one(r) for r in n.get("related_raw") or []))


def _links(ids: list[str], notes: dict[str, dict]) -> list[str]:
    out = []
    for i in ids or []:
        if i in notes:
            out.append(link_of(notes[i]))
        elif str(i).startswith("[["):
            out.append(str(i))  # dangling human link: keep, don't invent
    return out


def render(n: dict, notes: dict[str, dict], *, today: str) -> str:
    fm_items: list[tuple[str, Any]] = [
        ("id", n["id"]),
        ("type", n.get("type") or ""),
        ("project", n.get("project") or "global"),
        ("tags", list(n.get("tags") or [])),
        ("status", n.get("status") or "active"),
        ("related", _links(n.get("related") or [], notes)),
        ("sources", list(n.get("sources") or [])),
        ("updated", n.get("updated") or today),
    ]
    for k in ("legacy_code", "origin"):
        if n.get(k):
            fm_items.append((k, n[k]))
    for k, v in (n.get("_fm") or {}).items():
        if k not in MANAGED_KEYS:
            fm_items.append((k, v))
    orig = n.get("_fm")
    raw = n.get("_raw")
    # opaque keys (value None) can only be written back raw
    fm_text = dump_frontmatter(fm_items, orig=orig, raw=raw)

    typ = n.get("type")
    hub = f"[[项目/{n['project']}/README|{n['project']}]]" if typ != "tip" else "[[技巧/技巧|agent使用技巧]]"
    srcs = n.get("sources") or []
    b = [f"# {n['title']}", "", f"> 所属：{hub}" + (f" · 归纳自 {len(srcs)} 个会话" if srcs else "")]
    b += list(n.get("_preamble") or [])
    for h, k in FIELD_SECTIONS.items():
        val = (n.get(k) or "").strip()
        if k == "extra" and not val:
            continue
        b += ["", f"## {h}", val or "（待补）"]
    text = fm_text + "\n" + "\n".join(b) + "\n"
    if sections := n.get("_sections"):
        text += "\n" + "".join(sections)
    rel = _links(n.get("related") or [], notes)
    related_body = n.get("_related_body", "")
    if related_body or rel:
        separator = "" if text.endswith("\n\n") else "\n" if text.endswith("\n") else "\n\n"
        text += separator + (related_body or "## 相关\n")
        existing = {link_target(link[0]) for link in WIKI.finditer(related_body)}
        additions = [link for link in rel if link_target(link) not in existing]
        if additions:
            text += ("" if text.endswith("\n") else "\n") + "".join(f"- {link}\n" for link in additions)
    return text


def new_note(**kw: Any) -> dict:
    n = {
        "type": "lesson", "project": "", "tags": [], "status": "active", "sources": [], "related": [],
        "legacy_code": "", "origin": "", "updated": "",
        "scene": "", "practice": "", "reason": "", "extra": "", "_fm": {}, "_raw": {},
        "_preamble": [], "_sections": [],
    }
    n.update(kw)
    return n


# ------------------------------------------------------------------ files
def write_atomic(path: pathlib.Path, text: str | bytes, *, create: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as fh:
        temporary = pathlib.Path(fh.name)
        try:
            fh.write(text.encode("utf-8") if isinstance(text, str) else text)
            fh.close()
            if create:
                os.link(temporary, path)
            else:
                os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def write_note_file(vault: pathlib.Path, rel: str, text: str, *, owner: str | None = None,
                    create: bool = False) -> pathlib.Path:
    p = within(vault, rel)
    previous_mode = stat.S_IMODE(p.stat().st_mode) if p.is_file() and not create else None
    write_atomic(p, text, create=create)
    if previous_mode is not None:
        os.chmod(p, previous_mode)
    if owner:
        with contextlib.suppress(Exception):
            shutil.chown(p, owner, owner)
            os.chmod(p, 0o664)
        d = p.parent
        base = vault.resolve()
        while d != base and base in d.parents:
            with contextlib.suppress(Exception):
                shutil.chown(d, owner, owner)
            d = d.parent
    return p


class NoteCache:
    """Read vault files every scan; cache parsing by content fingerprint.

    mtime/size alone miss same-size edits on coarse filesystems or sync clients
    that preserve timestamps. The content is always authoritative.
    """

    def __init__(self) -> None:
        self._c: dict[pathlib.Path, tuple[bytes, dict | None]] = {}
        self._lock = threading.Lock()

    def load(self, vault: pathlib.Path) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if not vault.is_dir():
            return out
        seen = set()
        with self._lock:
            for p in vault.rglob("*.md"):
                if p.is_symlink() or any(x in p.relative_to(vault).parts for x in SKIP_DIRS):
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                key = hashlib.sha256(text.encode("utf-8")).digest()
                hit = self._c.get(p)
                if hit and hit[0] == key:
                    n = hit[1]
                else:
                    n = parse_note(p, vault, text=text)
                    self._c[p] = (key, n)
                seen.add(p)
                if n:
                    out[n["id"]] = copy.deepcopy(n)
            for p in [x for x in self._c if x not in seen]:
                del self._c[p]
        resolve_links(out)
        return out


# ------------------------------------------------------------------ lock
_tls = threading.local()
_proc_lock = threading.RLock()


def default_lock_path() -> pathlib.Path:
    env = os.environ.get("HINDDIAN_VAULT_LOCK")
    if env:
        return pathlib.Path(env).expanduser()
    return paths.state_dir() / "vault.lock"


@contextlib.contextmanager
def private_append(path: pathlib.Path, mode: str):
    """Open an append file without following links or waiting on special files."""
    with contextlib.suppress(FileNotFoundError):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise UnsafePath(f"unsafe append file: {path}")
    flags = (os.O_RDWR if "+" in mode else os.O_WRONLY) | os.O_APPEND | os.O_CREAT
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags, 0o600), mode) as stream:
        info = os.fstat(stream.fileno())
        named = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not stat.S_ISREG(named.st_mode) or not os.path.samestat(info, named)):
            raise UnsafePath(f"unsafe append file: {path}")
        yield stream, info


@contextlib.contextmanager
def vault_lock(path: pathlib.Path | None = None, timeout: float = 60.0, *, private: bool = False) -> Iterator[None]:
    """Exclusive, re-entrant (per thread) lock around a vault read-modify-write."""
    path = path or default_lock_path()
    path = path.absolute() if private else path.resolve()
    held = getattr(_tls, "held", set())
    if path in held:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    if not _proc_lock.acquire(timeout=timeout):
        raise VaultBusy("vault busy (in-process)")
    try:
        with contextlib.ExitStack() as stack:
            if private:
                fh, _ = stack.enter_context(private_append(path, "a+b"))
            else:
                fh = stack.enter_context(path.open("a+b"))
            fh.seek(0)
            while True:
                try:
                    if os.name == "nt":
                        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise VaultBusy(f"vault busy: {path}") from None
                    time.sleep(min(0.1, remaining))
            _tls.held = held
            held.add(path)
            try:
                yield
            finally:
                held.remove(path)
                if os.name == "nt":
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fh, fcntl.LOCK_UN)
    finally:
        _proc_lock.release()


# ------------------------------------------------------------------ similarity
def grams(t: str) -> set[str]:
    t = re.sub(r"\s+", "", (t or "").lower())
    return {t[i : i + 2] for i in range(len(t) - 1)} or ({t} if t else set())


def jaccard(a: set, b: set) -> float:
    return len(a & b) / (len(a | b) or 1)


def similarity(title: str, practice: str, n: dict) -> float:
    """How likely a new (title, practice) is the same topic as note n: title Jaccard + title/practice
    Jaccard, 0..2."""
    return jaccard(grams(title), grams(n.get("title") or "")) + jaccard(
        grams((title or "") + (practice or "")), grams((n.get("title") or "") + (n.get("practice") or "")))
