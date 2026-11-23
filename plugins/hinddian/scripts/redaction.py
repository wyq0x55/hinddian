"""Text redaction shared by the vault and the host recorder."""
from __future__ import annotations

import re

PRIVATE_RE = re.compile(r"<private>.*?(?:</private>|\Z)", re.S | re.I)
SECRET_RE = [
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|bearer)\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]{12,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(ghp|gho|github_pat)_[A-Za-z0-9_]{20,}"),
]


def redact(text: str) -> str:
    text = PRIVATE_RE.sub("[private]", text)
    for pattern in SECRET_RE:
        text = pattern.sub("[REDACTED]", text)
    return text
