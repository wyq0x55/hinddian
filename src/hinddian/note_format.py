"""Atomic-note file format shared by the MCP vault ops (notes.py) and the vault host batch engine.

One implementation of: frontmatter parse/dump (unknown keys and unchanged values round-trip
verbatim), body sections (sections we don't manage survive a re-render), link resolution,
path safety, the vault write lock and an mtime-keyed parse cache.

Stdlib only — the batch engine runs under the system python on the vault host.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import pathlib
import re
import shutil
import threading
import time
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover — Windows dev boxes; vault writes only run on the vault host
    fcntl = None  # type: ignore[assignment]

SKIP_DIRS = (".obsidian", "_归档", ".git", ".trash", "_模板")
FOLDER = {"decision": "决策", "lesson": "经验"}
NOTE_TYPES = ("tip", "decision", "lesson")

SECRET_RE = [
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|bearer)\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]{12,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(ghp|gho|github_pat)_[A-Za-z0-9_]{20,}"),
]
WIKI = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")

# Frontmatter keys render() owns; everything else in a note's frontmatter is carried through.
MANAGED_KEYS = (
    "id", "type", "project", "tags", "status", "supersedes", "related", "sources",
    "updated", "superseded_by", "legacy_code", "origin",
)
FIELD_SECTIONS = {"场景": "scene", "做法": "practice", "理由": "reason", "影响 / 推广": "extra"}
LINK_SECTIONS = ("取代", "相关")
GENERATED_PREAMBLE = ("> 所属：", "> ⚠️ 已被")


class VaultBusy(RuntimeError):
    pass


class UnsafePath(ValueError):
    pass


# ------------------------------------------------------------------ text helpers
def redact(t: str) -> str:
    for r in SECRET_RE:
        t = r.sub("[REDACTED]", t)
    return t


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
        elif ch in "\"'":
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


_KEY = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_\-]*):(?:\s+(.*))?$")


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
        key, val = m.group(1), (m.group(2) or "").strip()
        j = i + 1
        while j < len(lines) and (lines[j].startswith((" ", "\t", "-")) or not lines[j].strip()) and not _KEY.match(lines[j]):
            j += 1
        while j > i + 1 and not lines[j - 1].strip():
            j -= 1
        block = lines[i:j]
        raw[key] = "\n".join(block)
        cont = [x for x in block[1:] if x.strip()]
        if not val and cont and all(x.lstrip().startswith("- ") or x.strip() == "-" for x in cont):
            fm[key] = [_unquote(x.lstrip()[1:]) for x in cont if x.lstrip()[1:].strip()]
        elif cont:
            fm[key] = None  # opaque; raw[key] carries it
        elif val.startswith("[") and val.endswith("]"):
            fm[key] = _split_inline(val[1:-1])
        else:
            fm[key] = _unquote(val)
        i = j
    return fm, raw, body


_PLAIN = re.compile(r"^[^\s\-?:,\[\]{}#&*!|>'\"%@`][^:#\n]*$")
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
def split_body(body: str) -> tuple[str | None, list[str], list[tuple[str, str]]]:
    """→ (title, preamble lines after title, [(section heading, content)])."""
    first = re.search(r"^## ", body, re.M)
    head = body[: first.start()] if first else body
    rest = body[first.start() :] if first else ""
    title = None
    pre: list[str] = []
    for line in head.split("\n"):
        if title is None and line.startswith("# "):
            title = line[2:].strip()
            continue
        if title is not None:
            pre.append(line)
    sections = [(h.strip(), c) for h, c in re.findall(r"^## (.+?)\n(.*?)(?=^## |\Z)", rest, re.M | re.S)]
    return title, pre, sections


def parse_note(p: pathlib.Path, vault: pathlib.Path) -> dict | None:
    try:
        t = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
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
    secd = {h: c.strip() for h, c in sections}
    n = {
        "path": rel,
        "id": fm["id"],
        "type": s("type"),
        "project": s("project"),
        "tags": lst(fm.get("tags")),
        "status": s("status") or "active",
        "sources": lst(fm.get("sources")),
        "related_raw": lst(fm.get("related")),
        "supersedes_raw": lst(fm.get("supersedes")),
        "superseded_by_raw": s("superseded_by"),
        "legacy_code": s("legacy_code"),
        "origin": s("origin"),
        "updated": s("updated"),
        "title": title or p.stem,
        "text": t,
        "_fm": fm,
        "_raw": raw,
        "_preamble": [x for x in pre if x.strip() and not x.startswith(GENERATED_PREAMBLE)],
        "_sections": [(h, c.strip()) for h, c in sections if h not in FIELD_SECTIONS and h not in LINK_SECTIONS],
    }
    for h, k in FIELD_SECTIONS.items():
        n[k] = secd.get(h, "")
        if n[k] == "（待补）":
            n[k] = ""
    if not n["superseded_by_raw"]:
        m = re.search(r"^> ⚠️ 已被 (\[\[[^\]]+\]\])", "\n".join(pre), re.M)
        if m:
            n["superseded_by_raw"] = m.group(1)
    return n


def link_target(link: str) -> str:
    m = re.match(r"\[\[([^\]|]+)", link or "")
    return m.group(1) if m else (link or "")


def link_of(n: dict) -> str:
    return f"[[{n['path']}|{n['title']}]]"


def resolve_links(notes: dict[str, dict]) -> None:
    """Fill related / supersedes / superseded_by (note ids) from the raw links in each note.
    Links we can't resolve are kept verbatim so a re-render never silently drops them."""
    bypath = {n["path"]: n["id"] for n in notes.values()}

    def one(raw: str) -> str:
        if raw in notes:
            return raw
        return bypath.get(link_target(raw), raw)

    for n in notes.values():
        n["related"] = list(dict.fromkeys(one(r) for r in n.get("related_raw") or []))
        n["supersedes"] = list(dict.fromkeys(one(r) for r in n.get("supersedes_raw") or []))
        sb = n.get("superseded_by_raw") or ""
        n["superseded_by"] = one(sb) if sb else ""


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
        ("supersedes", _links(n.get("supersedes") or [], notes)),
        ("related", _links(n.get("related") or [], notes)),
        ("sources", list(n.get("sources") or [])),
        ("updated", n.get("updated") or today),
    ]
    sb = n.get("superseded_by") or ""
    if n.get("status") == "superseded" and sb:
        fm_items.append(("superseded_by", link_of(notes[sb]) if sb in notes else sb))
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
    if n.get("status") == "superseded" and sb in notes:
        b.append(f"> ⚠️ 已被 {link_of(notes[sb])} 取代")
    b += list(n.get("_preamble") or [])
    for h, k in FIELD_SECTIONS.items():
        val = (n.get(k) or "").strip()
        if k == "extra" and not val:
            continue
        b += ["", f"## {h}", val or "（待补）"]
    for h, c in n.get("_sections") or []:
        b += ["", f"## {h}", c]
    sup = _links(n.get("supersedes") or [], notes)
    if sup:
        b += ["", "## 取代", *[f"- {x}" for x in sup]]
    rel = _links(n.get("related") or [], notes)
    if rel:
        b += ["", "## 相关", *[f"- {x}" for x in rel]]
    return redact(fm_text + "\n" + "\n".join(b) + "\n")


def new_note(**kw: Any) -> dict:
    n = {
        "type": "lesson", "project": "", "tags": [], "status": "active", "sources": [], "related": [],
        "supersedes": [], "superseded_by": "", "legacy_code": "", "origin": "", "updated": "",
        "scene": "", "practice": "", "reason": "", "extra": "", "_fm": {}, "_raw": {},
        "_preamble": [], "_sections": [],
    }
    n.update(kw)
    return n


# ------------------------------------------------------------------ files
def write_note_file(vault: pathlib.Path, rel: str, text: str, *, owner: str | None = None) -> pathlib.Path:
    p = within(vault, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)
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
    """Parse each note file once; re-parse only when its (mtime, size) changes."""

    def __init__(self) -> None:
        self._c: dict[pathlib.Path, tuple[tuple[int, int], dict | None]] = {}
        self._lock = threading.Lock()

    def load(self, vault: pathlib.Path) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if not vault.is_dir():
            return out
        seen = set()
        with self._lock:
            for p in vault.rglob("*.md"):
                if any(x in p.parts for x in SKIP_DIRS):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                key = (st.st_mtime_ns, st.st_size)
                hit = self._c.get(p)
                if hit and hit[0] == key:
                    n = hit[1]
                else:
                    n = parse_note(p, vault)
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
        return pathlib.Path(env)
    return pathlib.Path(os.environ.get("HB_BASE") or "/var/lib/hinddian") / "vault.lock"


@contextlib.contextmanager
def vault_lock(path: pathlib.Path | None = None, timeout: float = 60.0) -> Iterator[None]:
    """Exclusive, re-entrant (per thread) lock around every read-modify-write of the vault.
    Shared by MCP upserts and the batch engine so neither overwrites the other."""
    depth = getattr(_tls, "depth", 0)
    if depth:
        _tls.depth = depth + 1
        try:
            yield
        finally:
            _tls.depth -= 1
        return
    path = path or default_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    if not _proc_lock.acquire(timeout=timeout):
        raise VaultBusy("vault busy (in-process)")
    try:
        with open(path, "a") as fh:
            if fcntl is not None:
                while True:
                    try:
                        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() > deadline:
                            raise VaultBusy(f"vault busy: {path}") from None
                        time.sleep(0.1)
            _tls.depth = 1
            try:
                yield
            finally:
                _tls.depth = 0
                if fcntl is not None:
                    fcntl.flock(fh, fcntl.LOCK_UN)
    finally:
        _proc_lock.release()


# ------------------------------------------------------------------ search
def grams(t: str) -> set[str]:
    t = re.sub(r"\s+", "", (t or "").lower())
    return {t[i : i + 2] for i in range(len(t) - 1)} or ({t} if t else set())


def jaccard(a: set, b: set) -> float:
    return len(a & b) / (len(a | b) or 1)


def similarity(title: str, practice: str, n: dict) -> float:
    """How likely a new (title, practice) is the same topic as note n: title Jaccard + title/practice
    Jaccard, 0..2. Shared by the batch engine's dedupe and the agent upsert check."""
    return jaccard(grams(title), grams(n.get("title") or "")) + jaccard(
        grams((title or "") + (practice or "")), grams((n.get("title") or "") + (n.get("practice") or "")))


def score(query: str, n: dict) -> float:
    """Bigram overlap — works for Chinese (no spaces) as well as English."""
    q = grams(query)
    if not q:
        return 0.0
    title = grams(n.get("title") or "")
    body = grams((n.get("scene") or "") + (n.get("practice") or "") + (n.get("reason") or ""))
    return (2 * len(q & title) + len(q & body)) / len(q)
