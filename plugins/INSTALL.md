# 安装 hinddian 插件（Claude Code / Codex）

三步，不需要让 AI 帮你配置：

1. 装插件
2. 运行一次 `setup.py`（写入服务器地址和 token，并自检）
3. 新开一个会话

## 一包装什么

| 组件 | Claude Code | Codex CLI / 桌面 |
|------|-------------|------------------|
| MCP `hinddian-memory` | 是：本地 stdio 桥 `scripts/mcp_bridge.py`，转发到你的服务器 | 是：同一个桥（`.codex-plugin/mcp.json`） |
| Hooks：SessionStart（注入记忆路由块）、UserPromptSubmit（按消息自动召回）、Stop（会话草稿） | 是 | 是，但需在 Codex 里 **trust** 插件 hooks |
| Skills：`memory`（何时读/写）、`recall`、`remember`、`doctor`、`setup` | 是（`/hinddian:recall` 等） | 是 |

MCP 走插件内置的本地桥，所以插件配置里**不写任何服务器地址**；地址和 token 只存在你本机的
`~/.config/hinddian/config.json`（权限 600），hooks 和 MCP 共用这一份。

## 1. 装插件

**Claude Code**

```bash
claude plugin marketplace add wyq0x55/hinddian
claude plugin install hinddian@hinddian-plugins
```

**Codex**

```bash
codex plugin marketplace add wyq0x55/hinddian
codex plugin add hinddian@hinddian-plugins
# 启用后在 Codex 里审查并 trust 插件 hooks
```

## 2. 配置（一次）

插件装好后，新会话开头会直接打印要运行的完整命令（带插件的实际路径）。也可以自己找：

```bash
# Claude Code
python3 ~/.claude/plugins/cache/hinddian-plugins/hinddian/*/scripts/setup.py
# Codex
python3 ~/.codex/plugins/cache/hinddian-plugins/hinddian/*/scripts/setup.py
```

不带参数会交互式询问地址和 token（token 不回显）；也可以一行写完：

```bash
python3 …/scripts/setup.py --url https://<host>:8444/hinddian --token <HINDDIAN_MCP_TOKEN>
# 服务器用自签证书时加：--ca /path/to/fullchain.pem
```

**注意**：必须是 **`https` + 端口 `8444`**。不要填 `http://<host>/hinddian`（旧 `:80` 入口已关闭，会返回 **HTTP 410**）。
仪表盘是 `:8443`（mTLS），Agent/MCP 才是 `:8444`。

它会写配置并逐项自检：

```
  [ok]   服务器地址 https://<host>:8444/hinddian
  [ok]   连通（服务端版本 0.6.0）
  [ok]   鉴权通过（3 个项目）
  [ok]   MCP 工具 8 个
全部就绪。新开一个会话即生效。
```

之后随时可以 `setup.py --check` 只自检。两台以上电脑：每台各跑一次，或者把
`~/.config/hinddian/config.json` 拷过去。


## 排错

- **写入了 `https://…:8444/hinddian` 但自检仍显示 `http://…/hinddian`（无端口）**：
  `HINDDIAN_MEMORY_URL` 或 Claude 插件选项覆盖了配置文件。PowerShell：
  `Remove-Item Env:HINDDIAN_MEMORY_URL -ErrorAction SilentlyContinue`
  并在 Windows「环境变量」/ Claude 插件设置里删掉旧 URL，再重跑 `setup.py`。

- **`/api/health` 返回 HTTP 410**：只有旧明文 `:80 /hinddian` 会 410；`:8444` 本身不会。 若你填的已是 `https://…:8444/hinddian` 仍报 410，看输出里的「实际请求」——多半是环境变量 `HINDDIAN_MEMORY_URL`（或 `CLAUDE_PLUGIN_OPTION_HINDDIAN_MEMORY_URL`）仍指向旧 `http://…/hinddian`，覆盖了配置文件。 `unset HINDDIAN_MEMORY_URL` 后重跑 `setup.py`，或把该变量改成带 `:8444` 的 https 地址。
- **鉴权失败 401/403**：token 必须是服务端的 `HINDDIAN_MCP_TOKEN`，不是仪表盘 `AUTH_TOKEN`。
- **证书错误**：加 `--ca /path/to/fullchain.pem`。
- **Codex**：审查并 **trust** 插件 hooks。

## 3. 新开会话

- Claude Code：`/mcp` 里能看到 `plugin:hinddian:hinddian-memory` 已连接
- Codex：会话里能调用 `routing_global` / `recall`

## 自动召回

每条用户消息会按内容去服务端 recall，命中的相关笔记（最多 3 条、每条一行）附在**该条消息末尾**；
会话开头只注入一段固定不变的规则 + 项目名，所以不破坏提示词缓存。短消息（「好的」「继续」等）、`/` 命令跳过；
同一会话不重复注入；3 秒超时就跳过。

- 关闭：`HINDDIAN_AUTO_RECALL=0`，或在 `~/.config/hinddian/config.json` 写 `"auto_recall": false`
- 调节：`HINDDIAN_RECALL_MIN_CHARS`（默认 8）、`HINDDIAN_RECALL_MAX_ITEMS`（3）、`HINDDIAN_RECALL_MIN_SCORE`（0.5）

## 进阶

- 也可以用环境变量覆盖配置文件：`HINDDIAN_MEMORY_URL`、`HINDDIAN_MCP_TOKEN`、`HINDDIAN_CA_FILE`
- Claude Code 启用插件时填写的 plugin options（同名）也会被读取
- hooks 拒绝向非本机地址发明文 http（会话正文 + token）；本机调试可用 `http://127.0.0.1:8787`
- 本地开发：`claude --plugin-dir ./plugins/hinddian`；`claude plugin validate ./plugins/hinddian`

## 可选 Magpie 宿主

产品不依赖 Magpie。若需要：见仓库 [`adapters/magpie/README.md`](../adapters/magpie/README.md)。
