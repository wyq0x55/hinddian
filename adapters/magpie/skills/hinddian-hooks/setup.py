"""Check local capture settings without writing configuration."""
from __future__ import annotations

import argparse
import sys

from capture import settings
import paths


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.parse_args(argv)
    try:
        fallback, limit = settings()
        vault = paths.vault_dir()
        drafts, processed = paths.drafts_dir(), paths.processed_dir()
        for directory in (drafts, processed):
            paths.check_draft_root(directory, vault)
    except (OSError, ValueError) as exc:
        print(f"hinddian 配置错误（{type(exc).__name__}）", file=sys.stderr)
        return 1
    for label, path in (("笔记库", vault), ("草稿", drafts), ("已处理", processed), ("状态", paths.state_dir())):
        print(f"{label} {path}")
    print(f"无四段回复 {fallback}（摘要上限 {limit} 字）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
