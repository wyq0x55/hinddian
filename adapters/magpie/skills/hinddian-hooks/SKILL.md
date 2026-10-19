---
name: hinddian-hooks
description: Optional Magpie adapter — install hinddian-memory MCP + local Library Hooks. hinddian core is host-agnostic (Claude/Codex first). WebDAV does not sync Hooks.
---

# hinddian Magpie adapter（可选）

> **hinddian 产品本身与 Magpie 无关。** 本 skill 仅给仍使用 Magpie 的机器装 hooks。首选安装见仓库 `plugins/hinddian/`（Claude/Codex）。

## 硬限制（上游）

Magpie **WebDAV / 备份 Bundle 不同步 Hooks**（`library.Bundle` 无 Hooks 字段）。  
Skills / MCP / instructions 会同步；**Hooks 必须每台电脑本地写一次**。

插件市场（`magpie plugin add`）装的是网关/工具插件，**不会**在启用时自动写入 Library Hooks。

## 像插件市场一样装（推荐）

### A. Magpie Library → Skills（官方技能市场路径）

1. 打开 Magpie → **Library → Skills**
2. 粘贴 GitHub：`wyq0x55/hinddian`（或本仓库 URL）→ Probe → 安装 **hinddian-hooks**
3. Windows 再跑一次安装器（写入 Hooks 面板）：

```powershell
magpie webdav now
& "$env:USERPROFILE\.config\magpie\library\skills\hinddian-hooks\install.ps1"
magpie library sync
```

私有仓库：Magpie Settings 里填 GitHub token。

### B. Magpie Plugins（Discover / plugin add）

```powershell
magpie plugin add github:wyq0x55/hinddian
```

然后对任意已挂 **Magpie tools** MCP 的 Agent 说：**安装 hinddian**（调用 `hinddian_install`），或仍跑上面的 `install.ps1`。

侧边栏会出现 **Hindian** 说明页。

### C. WebDAV 已拉到 skill（无 GitHub）

```powershell
magpie webdav now
& "$env:USERPROFILE\.config\magpie\library\skills\hinddian-hooks\install.ps1"
```

## Agent 应做什么

若用户说「安装 hinddian / 装记忆 hooks」：

1. 优先调用工具 `hinddian_install`（若 Magpie 插件已启用）
2. 否则在本机执行本 skill 目录下的 `install.ps1`（Windows）或 `install.py`（Linux/macOS）
3. 再 `magpie library sync`
4. 确认 Library → Hooks 有 `hinddian-session-start`、`hinddian-turn-end`；MCP 有 `hinddian-memory`

## 装好后的行为

- **session-start**：结束上一会话缓冲（Jev keep → 一次 `push_draft`）；注入固定的记忆路由块
- **turn-end**：白名单抽取（用户话 + 最终回复）→ 会话缓冲（不按回合推草稿）
- **Jev**：本机 Magpie `127.0.0.1:3425/v1/systemone` → 可选云端 → 都失败则不写（`source=none`）


## Agent 修正记忆（门控 upsert）

- **可直写**：`tip` / `preference` / `lesson` → `upsert_note`（可用 `auto_verdict`）
- **须仪表盘批准**：凡新增、修改、取代或作废 `decision` 的写入，一律进「Agent 修正」队列，由用户在仪表盘批准；`user_confirmed` / `face_correction` 只作为说明展示给审批人，不能绕过
- **禁止**：硬删、Hindsight `retain`；只用 `supersede` / `obsolete`
- Obsidian 为真相源；同步层跟随笔记状态

## 不要

- 不要在非 vault 主机器跑 `apply_library.py`
- 不要指望只跑 `magpie webdav now` 就填满 Hooks 面板
