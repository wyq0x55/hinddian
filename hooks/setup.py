"""Configure local capture or opt into the HTTP collector."""
from __future__ import annotations

import argparse
import sys
import urllib.error
from pathlib import Path

import hookcfg
import jev
import paths


def check() -> bool:
    if problem := hookcfg.capture_problem():
        print(problem, file=sys.stderr)
        return False
    if hookcfg.capture_mode() == "local":
        vault, drafts, processed = paths.vault_dir(), paths.drafts_dir(), paths.processed_dir()
        try:
            for directory in (drafts, processed):
                paths.check_draft_root(directory, vault)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return False
        for label, value in (("笔记库", vault), ("草稿", drafts), ("已处理", processed), ("状态", paths.state_dir())):
            print(f"{label} {value}")
        print("Jev " + ("已配置端点，等待会话 finalize 时连接" if jev.available() else "未配置端点"))
        return jev.available()
    try:
        hookcfg.req("GET", "/api/memory/gates/backend", timeout=10)
    except urllib.error.HTTPError as exc:
        print(f"采集服务返回 HTTP {exc.code}，请检查地址和采集令牌。", file=sys.stderr)
        return False
    except (OSError, ValueError) as exc:
        print(f"采集服务无法连接（{type(exc).__name__}）。", file=sys.stderr)
        return False
    print(f"HTTP 采集服务已连接 {hookcfg.memory_url()}")
    return True


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--local", action="store_true", help="Use local draft storage")
    transport.add_argument("--url", help="Use an HTTP collector at this base URL")
    parser.add_argument("--token", help="HTTP collector token (or use HINDDIAN_MCP_TOKEN)")
    parser.add_argument("--ca", help="Additional CA certificate for the HTTP collector")
    parser.add_argument("--allow-insecure", action="store_true")
    parser.add_argument("--check", action="store_true", help="Check effective settings without writing them")
    args = parser.parse_args(argv)
    if args.check or not argv:
        return 0 if check() else 1

    config = hookcfg.load_config()
    url = args.url.strip().rstrip("/").removesuffix("/mcp") if args.url else None
    if args.local:
        config["capture_mode"] = "local"
    if url:
        config["url"] = url
        if config.get("capture_mode") == "local":
            config["capture_mode"] = "http"
    if args.token:
        config["token"] = args.token
    if args.ca:
        config["ca_file"] = str(Path(args.ca).expanduser().resolve())
    if args.allow_insecure:
        config["allow_insecure"] = True
    print(f"已写入 {hookcfg.save_config(config)}")
    if url and hookcfg.memory_url() != url:
        print("HINDDIAN_MEMORY_URL 或插件选项覆盖了配置文件中的地址。")
        return 1
    if (url and hookcfg.capture_mode() != "http") or (args.local and hookcfg.capture_mode() != "local"):
        print("HINDDIAN_CAPTURE_MODE 或插件选项覆盖了配置文件中的模式。")
        return 1
    return 0 if check() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
