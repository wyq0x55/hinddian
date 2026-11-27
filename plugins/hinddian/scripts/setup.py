"""Check local capture settings without writing configuration."""
from __future__ import annotations

import argparse
import sys

from capture import settings
from extract import MarkdownParserUnavailable, markdown_parser
import paths


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.parse_args(argv)
    try:
        markdown_parser()
        fallback, limit = settings()
        vault = paths.vault_dir()
        drafts, processed = paths.drafts_dir(), paths.processed_dir()
        for directory in (drafts, processed):
            paths.check_draft_root(directory, vault)
    except MarkdownParserUnavailable as exc:
        print(f"hinddian 缺少采集依赖（{exc}）", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"hinddian 配置错误（{type(exc).__name__}）", file=sys.stderr)
        return 1
    for label, path in (("笔记库", vault), ("草稿", drafts), ("已处理", processed), ("状态", paths.state_dir())):
        print(f"{label} {path}")
    print(f"无四段回复 {fallback}（摘要上限 {limit} 字）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
