# 安装会话采集插件

插件包含 `SessionStart` 和 `Stop` hooks。需要 Python 3.11 或更新版本，并且宿主进程要能通过 PATH 找到 `python3`。Magpie 的 Windows 适配器也支持 `py` 和 `python`。

## Claude Code

在 Claude Code 中从项目 marketplace 安装 `hinddian`。

```text
/plugin marketplace add wyq0x55/hinddian
/plugin install hinddian@hinddian-plugins
```

从本地 checkout 安装时，marketplace 地址可使用仓库的本地路径。

## Codex

从仓库的 `.agents/plugins/marketplace.json` 所声明的 marketplace 安装 `hinddian`。插件自带 `.codex-plugin/hooks.json`，按宿主提示启用和信任 hooks。插件入口在 `plugins/hinddian`。

## 确认采集模式

在 checkout 根目录检查当前用户的有效设置。

```sh
python3 plugins/hinddian/scripts/setup.py --check
```

无采集地址时，hooks 默认在本机使用 Jev，并把草稿写到 `~/Obsidian/drafts`。如果旧配置里已有远端地址，可运行 `setup.py --local`，或给宿主进程设置 `HINDDIAN_CAPTURE_MODE=local`。可选的 HTTP 采集器使用 `setup.py --url https://<host>:8444/hinddian`，令牌可通过 `HINDDIAN_MCP_TOKEN` 提供。

开两个会话验证采集。第一个会话完成一轮后打开另一个会话，观察 `hooks/finalize.log` 和配置的草稿目录。只有 Jev 选择保留的会话会写草稿。
