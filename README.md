# hinddian

Host-agnostic memory product: **Obsidian 原子笔记**为人读唯一真相源（SoT）；Agent 只经 **hinddian-memory MCP** 路由 / 召回 / 门控写入；**Hindsight** 只做最后一层检索索引（定时同步喂入，Agent **禁止** `retain`）。

**与 Magpie 无关。** Magpie 若仍在用，见可选适配器 [`adapters/magpie/`](adapters/magpie/README.md)。

| 层 | 职责 |
|----|------|
| Host hooks（Claude / Codex / 可选 Magpie adapter） | 会话桶缓冲 + Jev keep → `push_draft` |
| hinddian-memory MCP | 路由、recall、门控 `upsert_note` / `suggest_correction` |
| DMIT 批处理 | 草稿 → 原子笔记（新项目需仪表盘批准） |
| Obsidian vault | 人读 SoT |
| Hindsight bank `wanwan` | 索引；`hinddian-hindsight-sync.timer` 对齐 |

## 文档地图

| 文档 | 内容 |
|------|------|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 流水线、Jev、会话桶、门控、组件 |
| [`docs/DASHBOARD.md`](docs/DASHBOARD.md) | 仪表盘：图谱 / 批准项目 / Agent 修正 |
| [`docs/MEMORY-MCP.md`](docs/MEMORY-MCP.md) | Agent 只挂 hinddian-memory（现行） |
| [`docs/PIPELINE.md`](docs/PIPELINE.md) | 一轮会话如何进笔记 |
| [`plugins/INSTALL.md`](plugins/INSTALL.md) | Claude Code / Codex 插件市场安装（首选） |
| [`adapters/magpie/README.md`](adapters/magpie/README.md) | **可选** Magpie 宿主适配器 |
| [`deploy/huawei/DEPLOY.md`](deploy/huawei/DEPLOY.md) | 华为部署与组件 |
| [`classify/README.md`](classify/README.md) | DMIT 批处理 / 原子笔记 |

---

## Agent 插件安装（Claude Code / Codex）— 首选

包路径：`plugins/hinddian/`（MCP + SessionStart/Stop hooks + skills）。

| 市场 | MCP + Hooks 同包？ | 安装 |
|------|-------------------|------|
| **Claude Code** | **是** | marketplace add → install |
| **Codex CLI / 桌面** | **是**（hooks 需用户 **trust**；公开目录拒收带 hooks 的包） | marketplace add → plugin add |

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

## 可选：Magpie 宿主

产品 **不依赖** Magpie。若某台机器仍跑 Magpie，用适配器（WebDAV **不同步** Library Hooks）：

见 [`adapters/magpie/README.md`](adapters/magpie/README.md)。SoT：`adapters/magpie/skills/hinddian-hooks/`。不要在非 DMIT 机跑 `apply_library.py`。

---

## 华为 Quick start

```bash
cp .env.example .env   # HINDSIGHT_API_KEY、HINDDIAN_MCP_TOKEN、AUTH_TOKEN（两者不同）；Jev 用 JEV_BASE_URL
pip install -e .
uvicorn hinddian.api:app --host 127.0.0.1 --port 8787
```

- MCP：`POST http://127.0.0.1:8787/mcp`（Bearer `HINDDIAN_MCP_TOKEN`）；本地开发用 `scripts/run_dev.sh`（未设 token 时自动 `HINDDIAN_ALLOW_NO_AUTH`）
- 公网：`https://<huawei>:8444/hinddian/mcp`（Caddy TLS，只暴露 Agent 通道）；hooks 基址 env：`HINDDIAN_MEMORY_URL`
- 仪表盘：`https://<huawei>:8443/`（mTLS；Caddy 注入 `AUTH_TOKEN`）

## 开发

```bash
pip install -e '.[dev]'
pytest                          # 门控 / 路径 / 笔记格式往返 / hooks / API 双通道
python tools/sync_hooks.py      # 改了 hooks/ 或 src/hinddian/jev.py 后重新生成各副本（CI 用 --check 校验）
```

源码位置：hook 运行时 `hooks/`；Jev `src/hinddian/jev.py`；笔记文件格式 `src/hinddian/note_format.py`（MCP 与 DMIT batch 共用）。
`plugins/hinddian/scripts/`、`skills/hinddian-hooks/`、`adapters/magpie/skills/hinddian-hooks/` 里的脚本是生成物，不要手改。

完整部署：[`deploy/huawei/DEPLOY.md`](deploy/huawei/DEPLOY.md)。

---

## 记忆怎么写（摘要）

1. **turn-end**：只抽 **用户话 + 最终助手回复** → 本机会话缓冲（不按回合推草稿）。
2. **session-start / 空闲约 30 分钟 / 换项目**：Jev keep → 一次 `push_draft`（`session-<id>`）。
3. **Jev 写路径**：本机 System One（`JEV_BASE_URL`，默认 `127.0.0.1:3425/v1/systemone`）→ 可选云端 TypeSafe → 都失败则**暂不记、退避重试**（不会用松弛 LLM 自动保留）。
4. **批处理**：新项目草稿满阈值（默认 20 **会话草稿**）→ 仪表盘批准；已批准增量自动；技巧可自动。
5. **Agent 修正（门控 upsert）**：`tip`/`preference`/`lesson` 可直写；凡涉及 `decision` 的写入一律进仪表盘 **「Agent 修正」**，只有你能批准（Agent 的 token 调不到批准接口）；禁止硬删（`supersede`/`obsolete`）；禁止 Hindsight `retain`。

仪表盘：[`docs/DASHBOARD.md`](docs/DASHBOARD.md)。

---

## Jev（System One，可选）

- URL：`POST http://127.0.0.1:3425/v1/systemone`（**`JEV_BASE_URL`**；旧别名 `MAGPIE_JEV_URL`）
- Auth：`Bearer` + **`JEV_API_KEY`**（旧别名 `MAGPIE_GATEWAY_KEY`；默认 token 字符串与部分本机网关约定有关，**不是**产品绑定 Magpie）
- Model：`JEV_MODEL`（默认 `typesafe/jev-latest`）
- 华为可选：SSH 隧道把远端 System One 映到本机 `:3425`（infra，见 `deploy/huawei`）
- 可选云端：`TYPESAFE_API_KEY` → `api.typesafe.ai`
- 写失败策略：**不写**（漏记优于脏记）；日志 `source=jev:local|cloud|none`
