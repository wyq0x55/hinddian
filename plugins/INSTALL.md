# 安装 hinddian 插件（Claude Code / Codex）

三步，不需要让 AI 帮你配置：

1. 装插件
2. 运行一次 `setup.py`（写入服务器地址和 token，并自检）
3. 新开一个会话

## 一包装什么

| 组件 | Claude Code | Codex CLI / 桌面 |
|------|-------------|------------------|
| MCP `hinddian-memory` | 是：本地 stdio 桥 `scripts/mcp_bridge.py`，转发到你的服务器 | 是：同一个桥（`.codex-plugin/mcp.json`） |
| Hooks SessionStart + Stop | 是 | 是，但需在 Codex 里 **trust** 插件 hooks |
| Skills（`setup`、`memory`） | 是 | 是 |

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

## 3. 新开会话

- Claude Code：`/mcp` 里能看到 `plugin:hinddian:hinddian-memory` 已连接
- Codex：会话里能调用 `routing_global` / `recall`

## 进阶

- 也可以用环境变量覆盖配置文件：`HINDDIAN_MEMORY_URL`、`HINDDIAN_MCP_TOKEN`、`HINDDIAN_CA_FILE`
- Claude Code 启用插件时填写的 plugin options（同名）也会被读取
- hooks 拒绝向非本机地址发明文 http（会话正文 + token）；本机调试可用 `http://127.0.0.1:8787`
- 本地开发：`claude --plugin-dir ./plugins/hinddian`；`claude plugin validate ./plugins/hinddian`

## 可选 Magpie 宿主

产品不依赖 Magpie。若需要：见仓库 [`adapters/magpie/README.md`](../adapters/magpie/README.md)。
