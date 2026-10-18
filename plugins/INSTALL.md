# Install hinddian as an agent plugin (Claude Code / Codex)

这是 **Claude Code / Codex Agent Plugins** 市场安装，**不是** Magpie 自己的 Library 插件市场。

## 一包装什么

| 组件 | Claude Code | Codex CLI / 桌面 |
|------|-------------|------------------|
| MCP `hinddian-memory`（HTTP） | 是（`.mcp.json`） | 是（`.mcp.json` / `mcp.json`） |
| Lifecycle hooks SessionStart + Stop | 是 | 是，但须用户 **trust hooks**；带 hooks 的包不能上 Codex 公开目录 |
| Skills（`setup`、`memory`） | 是 | 是 |

默认 MCP URL：`http://124.70.90.224/hinddian/mcp`。需要 Bearer 时在客户端 MCP 配置里加 `Authorization`（勿把 token 写进仓库）。

## Claude Code

```bash
claude plugin marketplace add wyq0x55/hinddian
# 会话内：
# /plugin marketplace add wyq0x55/hinddian
# /plugin install hinddian@hinddian-plugins

claude --plugin-dir ./plugins/hinddian
claude plugin validate ./plugins/hinddian
```

## Codex

```bash
codex plugin marketplace add wyq0x55/hinddian
codex plugin add hinddian@hinddian-plugins
# 本地：
codex plugin marketplace add ./   # 仓库根含 .agents/plugins/marketplace.json
```

启用后在 Codex 设置里 **审查/trust** 捆绑 hooks。公开目录拒收 lifecycle-hook 插件 — 用 marketplace / 桌面 / CLI。

## Magpie（另一套宿主）

Magpie WebDAV **不同步 Library Hooks**。用仓库 `skills/hinddian-hooks` + **Windows `install.ps1`**（或 Unix `install.py`）。见根 README「Magpie 安装」。不要用本文件里的 Claude/Codex 命令代替 Magpie hooks 安装。

## Windows 钩子运行时

Claude/Codex 插件内的 hook 脚本需要 PATH 上有 `python3` 或 `py -3`。
