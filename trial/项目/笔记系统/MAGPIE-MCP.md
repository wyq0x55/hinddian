---
id: proj/笔记系统/magpie-mcp
type: state
project: 笔记系统
tags: [笔记系统, magpie, mcp]
status: active
updated: 2026-10-18
---

# Magpie MCP（现行）

> **已改写（2026-10-18）**。旧文「Library 挂 hindsight、Agent retain」作废。权威副本：仓库 [`docs/MAGPIE-MCP.md`](https://github.com/wyq0x55/hinddian/blob/main/docs/MAGPIE-MCP.md)。

## 只挂

| 名 | URL | 用途 |
|----|-----|------|
| `hinddian-memory` | `https://<api-host>:8444/hinddian/mcp` | 路由 / recall / 门控写入 / push_draft |

Bearer 只放 secrets，勿写进本笔记。

## 不要挂

- 原生 `hindsight` MCP（Agent **禁止 retain**）
- 旧 `obsidian-vault` MCP（人读用 Obsidian / LiveSync）

索引由 API 主机 `hinddian-hindsight-sync` 从本 vault 的 active 笔记同步进 Hindsight bank。

## Hooks

WebDAV **不同步 Hooks**。Windows：`skills/hinddian-hooks` + `install.ps1`。详见 hinddian README。
