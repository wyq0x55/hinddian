"""One-time setup + self-check for hinddian hooks and MCP bridge (stdlib only).

  python3 setup.py                                  # interactive: asks URL and token
  python3 setup.py --url https://host:8444/hinddian --token XXX [--ca server.pem]
  python3 setup.py --check                          # diagnose only, change nothing

Writes ~/.config/hinddian/config.json (mode 600), then verifies TLS, auth and the MCP tools.
Exit code 0 = everything required works.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hookcfg  # noqa: E402


def _ok(msg: str) -> None:
    print(f"  [ok]   {msg}")


def _bad(msg: str, fix: str = "") -> None:
    print(f"  [fail] {msg}" + (f"\n         → {fix}" if fix else ""))


def _norm_url(u: str) -> str:
    u = u.strip().rstrip("/")
    return u[: -len("/mcp")] if u.endswith("/mcp") else u


def check() -> bool:
    print("hinddian 自检")
    cfg_p = hookcfg.config_path()
    if cfg_p.is_file():
        mode = cfg_p.stat().st_mode & 0o777
        _ok(f"配置文件 {cfg_p}" + ("" if os.name == "nt" or mode == 0o600 else f"（权限 {oct(mode)}，建议 600）"))
    else:
        print(f"  [info] 无配置文件 {cfg_p}（仅用环境变量）")

    why = hookcfg.transport_problem()
    if why:
        _bad(why, f"python3 \"{Path(__file__).resolve()}\" --url https://<host>/hinddian --token <token>")
        return False
    _ok(f"服务器地址 {hookcfg.memory_url()}")

    try:
        h = hookcfg.req("GET", "/api/health", timeout=10)
        _ok(f"连通（服务端版本 {h.get('version', '?')}）")
    except urllib.error.HTTPError as e:
        _bad(f"/api/health 返回 HTTP {e.code}", "确认 URL 包含 /hinddian 前缀，且反向代理放行 /api/health")
        return False
    except Exception as e:  # noqa: BLE001
        hint = "自签证书请加 --ca <server.pem>" if "CERTIFICATE" in str(e).upper() else "检查地址、端口与防火墙"
        _bad(f"连不上：{type(e).__name__}: {str(e)[:160]}", hint)
        return False

    if not hookcfg.token():
        _bad("没有 token", "加 --token <HINDDIAN_MCP_TOKEN>")
        return False
    try:
        g = hookcfg.req("GET", "/api/memory/routing/global", timeout=20)
        _ok(f"鉴权通过（{len(g.get('projects') or [])} 个项目）")
    except urllib.error.HTTPError as e:
        _bad(f"鉴权失败 HTTP {e.code}", "token 应为服务端的 HINDDIAN_MCP_TOKEN（不是仪表盘 AUTH_TOKEN）")
        return False
    except Exception as e:  # noqa: BLE001
        _bad(f"读取路由失败：{str(e)[:160]}", "服务端连不上 vault 主机？看服务端日志")
        return False

    try:
        out = hookcfg.req("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=20)
        n = len((out.get("result") or {}).get("tools") or [])
        _ok(f"MCP 工具 {n} 个") if n else _bad("MCP 没有返回工具")
    except Exception as e:  # noqa: BLE001
        _bad(f"MCP 调用失败：{str(e)[:160]}")
        return False

    try:
        import jev

        info = jev.backend_info()
        print(f"  [info] Jev 闸门：{json.dumps(info, ensure_ascii=False)[:160]}（可选；不可用时会话草稿会稍后重试）")
    except Exception as e:  # noqa: BLE001
        print(f"  [info] Jev 闸门未检测：{type(e).__name__}")
    print("全部就绪。新开一个会话即生效。")
    return True


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="hinddian setup")
    ap.add_argument("--url", help="服务端基址，含 /hinddian，例如 https://host:8444/hinddian")
    ap.add_argument("--token", help="HINDDIAN_MCP_TOKEN")
    ap.add_argument("--ca", help="自签证书（server fullchain.pem）路径")
    ap.add_argument("--allow-insecure", action="store_true", help="允许明文 http 到非本机地址（不推荐）")
    ap.add_argument("--check", action="store_true", help="只自检，不改配置")
    a = ap.parse_args(argv)
    if a.check:
        return 0 if check() else 1

    cfg = hookcfg.load_config()
    url = a.url or (input(f"服务器地址 [{cfg.get('url', '')}]: ").strip() if sys.stdin.isatty() else "") or cfg.get("url", "")
    tok = a.token or (getpass.getpass("Token（输入不回显，回车保留原值）: ").strip() if sys.stdin.isatty() else "") or cfg.get("token", "")
    if not url or not tok:
        print("需要 --url 和 --token（或在终端里交互输入）", file=sys.stderr)
        return 2
    cfg.update(url=_norm_url(url), token=tok)
    if a.ca:
        cfg["ca_file"] = str(Path(a.ca).expanduser().resolve())
    if a.allow_insecure:
        cfg["allow_insecure"] = True
    print(f"已写入 {hookcfg.save_config(cfg)}")
    return 0 if check() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
