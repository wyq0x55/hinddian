---
id: proj/笔记系统/readme
type: state
project: 笔记系统
tags: [笔记系统, hub]
status: active
updated: 2026-10-18
---
# 笔记系统

> 项目枢纽页：当前状态（覆盖写）+ 全部决策/经验链接。上级：[[00-系统/INDEX|INDEX]]  
> 产品权威文档：GitHub [wyq0x55/hinddian](https://github.com/wyq0x55/hinddian)（`README` / `ARCHITECTURE` / `docs/`）。

## 当前焦点
- **Obsidian 原子笔记 = 人读 SoT**；Agent 只走 **hinddian-memory** MCP（禁止原生 Hindsight retain）。
- Hindsight bank `wanwan` **仅索引**：`hinddian-hindsight-sync` 从 active 笔记同步。
- Magpie：hooks 会话桶 + Jev keep → `push_draft`；WebDAV **不同步 Hooks**（Windows 用 `install.ps1`）。

## 进行中
- 门控 upsert：tip/preference/当面纠错可直写；decision → 仪表盘「Agent 修正」或口头确认。
- Claude/Codex 可用插件市场装 `hinddian`；Magpie 另装 skill hooks。

## 阻塞 / 待跟进
- （无文档缺口；各机需确认 Hooks 面板非空）

## 下一步
- 新主题复制 `项目/_模板/`，再写入 INDEX。
- Agent 挂 `hinddian-memory`，不要挂 `obsidian-vault` / 原生 `hindsight`。

## 已知环境（无密钥）
- Vault：`/srv/obsidian/vault`
- MCP：`hinddian-memory` → `http://124.70.90.224/hinddian/mcp`（Bearer 仅 secrets）
- 仪表盘：`https://124.70.90.224:8443/`（Magpie 同款 mTLS）
- 同步：CouchDB + LiveSync（人读）；勿放密钥进笔记
- 说明：[[项目/笔记系统/MAGPIE-MCP|MAGPIE-MCP]] · [[项目/笔记系统/Hindsight与Obsidian双管线|SoT+索引]] · [[项目/笔记系统/会话提炼说明|会话→笔记]]

## 决策
- [[项目/笔记系统/决策/低成本子代理走外部 claude -p + magpie 网关|低成本子代理走外部 claude -p + magpie 网关]]
- [[项目/笔记系统/决策/借鉴 Orbital 约定，不部署 Orbital 本体|借鉴 Orbital 约定，不部署 Orbital 本体]]
- [[项目/笔记系统/决策/双管线：Obsidian 供人读，Hindsight 供 Agent 召回|双管线：Obsidian 供人读，Hindsight 供 Agent 召回]]
- [[项目/笔记系统/决策/按项目分目录，SessionStart 只读 INDEX+ASKS|按项目分目录，SessionStart 只读 INDEX+ASKS]]
- [[项目/笔记系统/决策/笔记同步选 LiveSync，不用 Tailscale|笔记同步选 LiveSync，不用 Tailscale]]
- [[项目/笔记系统/决策/Agent 读写走 MCP，人机共用同一 Vault|Agent 读写走 MCP，人机共用同一 Vault]]
- [[项目/笔记系统/决策/Magpie 笔记 MCP 用公网 HTTPS|Magpie 笔记 MCP 用公网 HTTPS]]
- [[项目/笔记系统/决策/Magpie 记忆 MCP 改用 Hindsight Recall|Magpie 记忆 MCP 改用 Hindsight Recall]]

> 上表部分决策标题仍写「Hindsight Recall / 双管线」：现行落地是 **hinddian-memory 包一层**（recall 经 Hindsight，写入只动 Obsidian）。细节见 [[项目/笔记系统/Hindsight与Obsidian双管线]]。

## 经验
（见 `经验/` 目录原子笔记；INDEX/链接由脚本维护时可在此补）
