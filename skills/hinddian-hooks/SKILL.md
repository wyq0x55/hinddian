---
name: hinddian-hooks
description: Install hinddian Magpie MCP + session-start/turn-end Library Hooks on this computer. WebDAV does not sync Hooks. Marketplace-style install via Magpie Library Skills (GitHub) or plugin tools.
---

# hinddian（Magpie 安装）

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

- **session-start**：结束上一会话缓冲（Jev keep → 一次 `push_draft`）；注入路由；should-recall
- **turn-end**：白名单抽取（用户话 + 最终回复）→ 会话缓冲（不按回合推草稿）
- **Jev**：本机 Magpie `127.0.0.1:3425/v1/systemone` → 可选云端 → 都失败则不写（`source=none`）

## 不要

- 不要在非 DMIT 机器跑 `apply_library.py`
- 不要指望只跑 `magpie webdav now` 就填满 Hooks 面板
