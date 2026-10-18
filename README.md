# hinddian

Obsidian **原子笔记**为人读唯一真相源（SoT）；Agent 只经 **hinddian-memory MCP** 路由 / 召回 / 门控写入；**Hindsight** 只做最后一层检索索引（由定时同步喂入，Agent **禁止** `retain`）。

| 层 | 职责 |
|----|------|
| Magpie / Claude / Codex hooks | 会话桶缓冲 + Jev keep → `push_draft` |
| hinddian-memory MCP | 路由、recall、门控 `upsert_note` / `suggest_correction` |
| DMIT 批处理 | 草稿 → 原子笔记（新项目需仪表盘批准） |
| Obsidian vault | 人读 SoT |
| Hindsight bank `wanwan` | 索引；`hinddian-hindsight-sync.timer` 对齐 |

## 文档地图

| 文档 | 内容 |
|------|------|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 流水线、Jev、会话桶、门控、组件 |
| [`docs/DASHBOARD.md`](docs/DASHBOARD.md) | 仪表盘：图谱 / 批准项目 / Agent 修正 |
| [`docs/MAGPIE-MCP.md`](docs/MAGPIE-MCP.md) | Magpie 只挂 hinddian-memory（现行） |
| [`docs/PIPELINE.md`](docs/PIPELINE.md) | 一轮会话如何进笔记（简版） |
| [`plugins/INSTALL.md`](plugins/INSTALL.md) | Claude Code / Codex 插件市场安装 |
| [`deploy/huawei/DEPLOY.md`](deploy/huawei/DEPLOY.md) | 华为部署与组件 |
| [`classify/README.md`](classify/README.md) | DMIT 批处理 / 原子笔记 |

Log: vault 里旧笔记「双管线 / 直连 Hindsight」已废弃；以本仓库 `docs/` 为准。

---

## Agent 插件安装（Claude Code / Codex）— 首选

包路径：`plugins/hinddian/`（MCP + SessionStart/Stop hooks + skills）。

| 市场 | MCP + Hooks 同包？ | 安装 |
|------|-------------------|------|
| **Claude Code** | **是** | marketplace add → install |
| **Codex CLI / 桌面** | **是**（hooks 需用户 **trust**；公开目录拒收带 hooks 的包） | marketplace add → plugin add |
| Magpie Library Hooks | WebDAV **不同步** Hooks | 见下方 Magpie：`install.ps1` |

### Claude Code

```bash
claude plugin marketplace add wyq0x55/hinddian
# 会话内：
# /plugin install hinddian@hinddian-plugins

# 或本地：
claude --plugin-dir ./plugins/hinddian
claude plugin validate ./plugins/hinddian
```

### Codex

```bash
codex plugin marketplace add wyq0x55/hinddian
codex plugin add hinddian@hinddian-plugins
# 启用后审查并 trust 插件 hooks
```

私有仓库：先登录 GitHub，或克隆后：

```bash
claude --plugin-dir /path/to/hinddian/plugins/hinddian
codex plugin marketplace add /path/to/hinddian
codex plugin add hinddian@hinddian-plugins
```

细节：[`plugins/INSTALL.md`](plugins/INSTALL.md)。

---

## Magpie 安装（Windows / 各机）

**硬限制**：上游 Magpie WebDAV / 备份 `Bundle` **不携带 Hooks**（只同步 Instructions / MCP / Skills / Icons / settings 等）。`magpie plugin add` 装的是网关/工具，**不会**自动写入 Library Hooks。

### Windows（唯一推荐路径）

Skill 到位后（WebDAV 或 Library → Skills 从 GitHub 装 `hinddian-hooks`），在 PowerShell：

```powershell
magpie webdav now
& "$env:USERPROFILE\.config\magpie\library\skills\hinddian-hooks\install.ps1"
```

装完验收：

- **Library → Hooks**：`hinddian-session-start`、`hinddian-turn-end`
- **Library → MCP**：`hinddian-memory`

可选：`magpie plugin add github:wyq0x55/hinddian` 后让 Agent 调 `hinddian_install`（底层仍写本机 Hooks）。私有仓库需 Magpie Settings 填 GitHub token。

**不要**在非 DMIT 机器跑 `apply_library.py`。

### Linux / macOS Magpie

```bash
magpie webdav now
python3 "$HOME/.config/magpie/library/skills/hinddian-hooks/install.py"
```

（Windows 请用上面的 `install.ps1`，不要再用旧的 `install.py` + `magpie library sync` 文档路径。）

### Skill 源码 SoT

| 路径 | 角色 |
|------|------|
| **`skills/hinddian-hooks/`** | **仓库权威副本（SoT）** |
| `deploy/magpie/skill-hinddian-hooks/` | 部署镜像；`apply_library.py`（仅 DMIT）灌进 Magpie library |
| 各机 `~/.config/magpie/library/skills/hinddian-hooks/` | WebDAV 拉到的运行副本 |

改 hooks / 安装器：先改 `skills/hinddian-hooks/`，再同步到 `deploy/magpie/skill-hinddian-hooks/`，DMIT `apply_library` + `magpie webdav now`。

当前 hooks 版本见 `skills/hinddian-hooks/HOOKS_VERSION`。

---

## 华为 Quick start

```bash
cp .env.example .env   # HINDSIGHT_API_KEY；Jev 优先本机 Magpie :3425（可选 TYPESAFE_API_KEY）
pip install -e .
uvicorn hinddian.api:app --host 127.0.0.1 --port 8787
```

- MCP：`POST http://127.0.0.1:8787/mcp`（Bearer）
- 公网：`http://<huawei>/hinddian/mcp`（Caddy）；对外基址 env：`HINDDIAN_MEMORY_URL`

完整部署：[`deploy/huawei/DEPLOY.md`](deploy/huawei/DEPLOY.md)。

---

## 记忆怎么写（摘要）

1. **turn-end**：只抽 **用户话 + 最终助手回复** → 本机会话缓冲（不按回合推草稿）。
2. **session-start / 空闲约 30 分钟 / 换项目**：Jev keep → 一次 `push_draft`（`session-<id>`）。
3. **Jev 写路径**：本机 Magpie `127.0.0.1:3425/v1/systemone` → 可选云端 TypeSafe → 都失败则 **`source=none`、本轮不记**（无松弛 LLM 自动 keep）。
4. **批处理**：新项目草稿满阈值（默认 20 **会话草稿**）→ 仪表盘批准；已批准增量自动；技巧可自动。
5. **Agent 修正（门控 upsert）**：`tip`/`preference`/当面纠错可直写；`decision` 须你确认或进仪表盘 **「Agent 修正」**；禁止硬删（`supersede`/`obsolete`）；禁止 Hindsight `retain`。

仪表盘操作见 [`docs/DASHBOARD.md`](docs/DASHBOARD.md)。

---

## Jev

- URL：`POST http://127.0.0.1:3425/v1/systemone`（`JEV_BASE_URL` / `MAGPIE_JEV_URL`）
- Auth：`Bearer magpie`（或 `MAGPIE_GATEWAY_KEY`）
- Model：`typesafe/jev-latest`（Magpie：`magpie provider add typesafe <key>` 并 expose）
- 华为：`magpie-tunnel.service` 把本机 `:3425` 转到 DMIT Magpie
- 可选云端：`TYPESAFE_API_KEY` → `api.typesafe.ai`
- 写失败策略：**不写**（漏记优于脏记）
