"""One-time setup + self-check for hinddian hooks and MCP bridge (stdlib only).

  python3 setup.py                                  # interactive: asks URL and token
  python3 setup.py --url https://host:8444/hinddian --token XXX [--ca server.pem]
  python3 setup.py --check                          # diagnose only, change nothing

Writes ~/.config/hinddian/config.json (mode 600), then verifies TLS, auth and the MCP tools.
Exit code 0 = everything required works.

Note: env HINDDIAN_MEMORY_URL / HINDDIAN_MCP_TOKEN override the config file. setup.py
exports the values it just wrote into this process so the self-check hits the URL you typed.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
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


def _host_from_url(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or "host"


def _has_agent_port(url: str) -> bool:
    u = urllib.parse.urlsplit(url)
    return u.port == 8444


def _retired_80_fix(url: str = "", requested: str = "") -> str:
    """Hint when the request got HTTP 410 (Caddy :80 /hinddian is Gone)."""
    host = _host_from_url(url) if url else "host"
    correct = f"https://{host}:8444/hinddian"
    lines = [
        f"HTTP 410 来自已停用的明文 :80 /hinddian，不是鉴权失败。"
        f" Agent API 请用 {correct}（必须 https + 端口 8444），不要用 http://{host}/hinddian。"
        f" You hit the retired :80 entry; use {correct} (https + port 8444),"
        f" not http://{host}/hinddian."
    ]
    if requested:
        lines.append(f" 实际请求：{requested}")
    if url and _has_agent_port(url):
        lines.append(
            " 你配置里已有 :8444，但仍收到 410 → 多半是环境变量 HINDDIAN_MEMORY_URL"
            "（或 CLAUDE_PLUGIN_OPTION_HINDDIAN_MEMORY_URL）覆盖了配置文件，仍指向旧 http://…/hinddian。"
            " 请 unset 该变量，或改成上述 https://…:8444/hinddian 后再跑 setup.py --check。"
            " (:8444 itself never returns 410; only :80 does.)"
        )
    return "".join(lines)


def _warn_suspect_url(url: str) -> None:
    u = urllib.parse.urlsplit(url)
    host = u.hostname or ""
    if u.scheme == "http" and host not in hookcfg.LOOPBACK:
        print(
            f"  [warn] 明文 http 到非本机；生产 Agent API 请用 "
            f"https://{host or '<host>'}:8444/hinddian（或加 --allow-insecure 仅调试）"
        )
    if u.scheme in ("http", "https") and u.port is None and "/hinddian" in (u.path or ""):
        print(
            f"  [warn] URL 未写端口，容易打到旧 :80/:443。"
            f"正确基址是 https://{host or '<host>'}:8444/hinddian"
        )



def _override_fix(written: str, effective: str, who: list[str] | None = None) -> str:
    """How to clear env / plugin-option overrides (Windows PowerShell + Unix)."""
    bits = [
        f"配置文件已写 {written}，但 hookcfg 实际用 {effective}。",
        ("覆盖来源：" + "；".join(who) + "。") if who else "",
        "请清掉旧地址后重跑 setup（PowerShell）：",
        "  Remove-Item Env:HINDDIAN_MEMORY_URL -ErrorAction SilentlyContinue",
        "  Remove-Item Env:HINDDIAN_ALLOW_INSECURE -ErrorAction SilentlyContinue",
        "  # 若在「系统/用户环境变量」或 Claude 插件选项里也填过旧 URL，一并删掉或改成 https://<host>:8444/hinddian",
        "  python3 …/setup.py --url https://<host>:8444/hinddian --token <HINDDIAN_MCP_TOKEN>",
        "Unix: unset HINDDIAN_MEMORY_URL HINDDIAN_ALLOW_INSECURE",
        "Claude Code: clear plugin option HINDDIAN_MEMORY_URL (userConfig), then re-run setup.",
    ]
    return " ".join(x for x in bits if x)


def _warn_env_overrides_config() -> str | None:
    """Env wins over config.json. Return a fix hint if they disagree, else None."""
    cfg = hookcfg.load_config()
    cfg_url = _norm_url(str(cfg.get("url") or ""))
    who: list[str] = []
    for key in ("HINDDIAN_MEMORY_URL", "CLAUDE_PLUGIN_OPTION_HINDDIAN_MEMORY_URL"):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        env_url = _norm_url(raw)
        if cfg_url and env_url != cfg_url:
            print(
                f"  [warn] {key}={raw} 覆盖配置文件 url={cfg_url}；"
                f"自检/hooks 实际走环境变量。"
            )
            who.append(f"{key}={raw}")
        elif not cfg_url:
            print(f"  [info] 使用环境变量 {key}={raw}")
    if who and cfg_url:
        return _override_fix(cfg_url, _norm_url(who[0].split("=", 1)[1]), who)
    return None


def _apply_runtime(url: str, token: str, ca_file: str | None = None, allow_insecure: bool | None = None) -> None:
    """Make this process use the values we just wrote (env otherwise shadows config)."""
    os.environ["HINDDIAN_MEMORY_URL"] = url
    os.environ["HINDDIAN_MCP_TOKEN"] = token
    if ca_file:
        os.environ["HINDDIAN_CA_FILE"] = ca_file
    if allow_insecure is True:
        os.environ["HINDDIAN_ALLOW_INSECURE"] = "1"
    elif allow_insecure is False:
        os.environ.pop("HINDDIAN_ALLOW_INSECURE", None)


def check() -> bool:
    print("hinddian 自检")
    cfg_p = hookcfg.config_path()
    if cfg_p.is_file():
        mode = cfg_p.stat().st_mode & 0o777
        _ok(f"配置文件 {cfg_p}" + ("" if os.name == "nt" or mode == 0o600 else f"（权限 {oct(mode)}，建议 600）"))
    else:
        print(f"  [info] 无配置文件 {cfg_p}（仅用环境变量）")

    override_fix = _warn_env_overrides_config()
    if override_fix:
        _bad("环境变量/插件选项中的 URL 与配置文件不一致", override_fix)
        return False

    why = hookcfg.transport_problem()
    if why:
        _bad(
            why,
            f"python3 \"{Path(__file__).resolve()}\" --url https://<host>:8444/hinddian --token <token>",
        )
        return False
    url = hookcfg.memory_url()
    _warn_suspect_url(url)
    _ok(f"服务器地址 {url}")

    health_url = url + "/api/health"
    try:
        h = hookcfg.req("GET", "/api/health", timeout=10)
        _ok(f"连通（服务端版本 {h.get('version', '?')}）")
    except urllib.error.HTTPError as e:
        if e.code == 410:
            _bad(f"/api/health 返回 HTTP 410", _retired_80_fix(url, health_url))
        else:
            _bad(
                f"/api/health 返回 HTTP {e.code}（{health_url}）",
                "确认 URL 为 https://<host>:8444/hinddian（含 /hinddian 前缀与端口 8444）",
            )
        return False
    except Exception as e:  # noqa: BLE001
        hint = "自签证书请加 --ca <server.pem>" if "CERTIFICATE" in str(e).upper() else "检查地址、端口与防火墙"
        _bad(f"连不上 {health_url}：{type(e).__name__}: {str(e)[:160]}", hint)
        return False

    if not hookcfg.token():
        _bad("没有 token", "加 --token <HINDDIAN_MCP_TOKEN>")
        return False
    routing_url = url + "/api/memory/routing/global"
    try:
        g = hookcfg.req("GET", "/api/memory/routing/global", timeout=20)
        _ok(f"鉴权通过（{len(g.get('projects') or [])} 个项目）")
    except urllib.error.HTTPError as e:
        if e.code == 410:
            _bad(f"鉴权请求返回 HTTP 410", _retired_80_fix(url, routing_url))
        else:
            _bad(
                f"鉴权失败 HTTP {e.code}（{routing_url}）",
                "token 应为服务端的 HINDDIAN_MCP_TOKEN（不是仪表盘 AUTH_TOKEN）",
            )
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
    url = _norm_url(url)
    _warn_suspect_url(url)
    cfg.update(url=url, token=tok)
    ca_file = None
    if a.ca:
        ca_file = str(Path(a.ca).expanduser().resolve())
        cfg["ca_file"] = ca_file
    if a.allow_insecure:
        cfg["allow_insecure"] = True
    saved = hookcfg.save_config(cfg)
    print(f"已写入 {saved}")
    print(f"  写入 url = {url}")
    effective = hookcfg.memory_url()
    print(f"  生效 url = {effective}（env / 插件选项优先于配置文件）")
    if _norm_url(effective) != url:
        who = []
        for key in ("HINDDIAN_MEMORY_URL", "CLAUDE_PLUGIN_OPTION_HINDDIAN_MEMORY_URL"):
            v = (os.environ.get(key) or "").strip()
            if v and _norm_url(v) == _norm_url(effective):
                who.append(f"{key}={v}")
        _bad(
            "写入的 URL 与生效 URL 不一致——环境变量或 Claude 插件选项覆盖了刚写入的配置",
            _override_fix(url, effective, who),
        )
        return 1
    # Align this process with the saved config (in case only config exists, no env).
    _apply_runtime(url, tok, ca_file=ca_file or cfg.get("ca_file"), allow_insecure=bool(cfg.get("allow_insecure")))
    return 0 if check() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
