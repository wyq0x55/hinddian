# Install hinddian as an agent plugin (Claude Code / Codex)

这是 **Claude Code / Codex Agent Plugins** 市场安装（hinddian 首选宿主）。

## 一包装什么

| 组件 | Claude Code | Codex CLI / 桌面 |
|------|-------------|------------------|
| MCP `hinddian-memory`（HTTP） | 是（`.mcp.json`，展开 `${VAR}`） | **否**——Codex 不展开插件 MCP URL 里的 `${VAR}`，需用 `codex mcp add` 自行登记（见下） |
| Lifecycle hooks SessionStart + Stop | 是 | 是，但须用户 **trust hooks**；带 hooks 的包不能上 Codex 公开目录 |
| Skills（`setup`、`memory`） | 是 | 是 |

**没有内置服务器地址**。安装前设置环境变量（勿把 token 写进仓库）：

| 变量 | 用途 |
|------|------|
| `HINDDIAN_MEMORY_URL` | https 基址，含 `/hinddian`，如 `https://<host>:8444/hinddian`；MCP 地址为 `${HINDDIAN_MEMORY_URL}/mcp` |
| `HINDDIAN_MCP_TOKEN` | Agent 通道 Bearer（服务器 `HINDDIAN_MCP_TOKEN`） |
| `HINDDIAN_CA_FILE` / `NODE_EXTRA_CA_CERTS` | 服务器是自签证书时，分别给 hooks（Python）与 MCP 客户端（Node） |

hooks 拒绝向非本机地址发明文 http（会话正文 + token）；本机调试可用 `http://127.0.0.1:8787`。
Claude Code 的 `.mcp.json` 会展开 `${VAR}`。Codex（实测 0.163.0）不会：插件里写 `${HINDDIAN_MEMORY_URL}/mcp` 会报 `relative URL without a base`，所以 Codex 插件只带 hooks + skills，MCP 由用户登记。

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
# MCP（token 从环境变量读，不写进 config.toml）：
codex mcp add hinddian-memory --url https://<host>:8444/hinddian/mcp --bearer-token-env-var HINDDIAN_MCP_TOKEN
# 本地：
codex plugin marketplace add ./   # 仓库根含 .agents/plugins/marketplace.json
```

启用后在 Codex 设置里 **审查/trust** 捆绑 hooks。公开目录拒收 lifecycle-hook 插件 — 用 marketplace / 桌面 / CLI。

## 可选 Magpie 宿主

产品不依赖 Magpie。若需要：见仓库 [`adapters/magpie/README.md`](../adapters/magpie/README.md)。
