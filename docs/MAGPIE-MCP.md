# Magpie MCP（现行）

> 权威说明在本仓库。Vault 旧笔记若仍写「直连 hindsight MCP / retain」一律以本文为准。

## Library 应挂的 MCP

| 名 | URL | 用途 |
|----|-----|------|
| **`hinddian-memory`** | `http://124.70.90.224/hinddian/mcp` | Agent 唯一记忆入口：路由 / recall / 门控写入 / push_draft |

Header：`Authorization: Bearer <HINDDIAN_MCP_TOKEN>`（常与 Hindsight tenant key 同源；只放 secrets，勿进笔记）。

## 禁止 / 已移除

| 项 | 说明 |
|----|------|
| 原生 **`hindsight` MCP** | **不要**再挂进 Magpie Library；Agent 不得 `retain` |
| 旧 **`obsidian-vault` MCP** | 已从 Library 移除；人读用 Obsidian App / LiveSync |
| OTLP 作为主记忆路径 | `otel.enabled=false`；主路径是 hinddian hooks |

Hindsight bank `wanwan` 仍由华为 **`hinddian-hindsight-sync.timer`** 从 Obsidian active 笔记同步索引；Agent 只经 hinddian-memory 的 `recall`。

## Hooks（不随 WebDAV）

上游 Bundle **不同步 Hooks**。装法见根 README「Magpie 安装」：`skills/hinddian-hooks` + **`install.ps1`（Windows）**。

装好后应有：

- Hooks：`hinddian-session-start`、`hinddian-turn-end`
- MCP：`hinddian-memory`

## 同步注意

Library 是**整文件** WebDAV（LWW）。DMIT 改完：`magpie webdav now`。其他电脑先 pull 再改，且**不要**在非 DMIT 跑 `apply_library.py`。
