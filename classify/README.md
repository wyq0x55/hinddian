# classify · 会话草稿 → 原子笔记（DMIT）

跑在 **DMIT**（vault 所在机）。hooks / MCP `push_draft` 产生的**会话桶草稿**落在 `/var/lib/hinddian/drafts/<项目>/`，由 **`hinddian_batch.py`**（及可选 pi 归类）合并进 Obsidian **原子笔记**——**永不一会话一笔记**，也不再写 `DECISIONS.md` / `LESSONS.md` 大文件。

## 现行主路径（v0.5+）

```
Host hooks (Claude/Codex; optional Magpie adapter)
  turn-end：白名单 → 会话缓冲
  finalize：Jev keep → push_draft
       ↓
/var/lib/hinddian/drafts/<project>/session-*.md
       ↓
hinddian-batch（timer）
  ├─ 未批准项目：满阈值(20) → 仪表盘「开始批量分析」
  ├─ 已批准项目：增量自动
  └─ 技巧 / 通用：可自动
       ↓
原子笔记（项目/*/决策|经验|…、技巧/*.md）
       ↓
华为 hinddian-hindsight-sync → Hindsight 索引
```

Agent 查重 / 召回只用 **`mcp__hinddian-memory__recall`**（及 `list_notes` / `get_note`），**不要** `mcp__hindsight__recall`，**不要**写旧三件套路径。

## 历史 Mode B（pi 逐条 · 仍可用）

早期「待入库 md + pi JSON 建议」路径仍留在本目录工具中，但产品主叙事是上面的 **session drafts + batch**。若跑 pi：

- `PI_CODING_AGENT_DIR=/opt/hinddian-classify/pi-agent`
- `mcp.json`：**仅** `hinddian-memory` → `http://124.70.90.224/hinddian/mcp`
- 已移除原生 Hindsight MCP；AGENTS 铁律见 `classify/AGENTS.md`

### 过滤要点

默认 **ignore**。预过滤空/流水账；置信度门槛；本地 bigram 去重；`approve` / `reject` / `approve-batch`。

### 命令

```bash
hinddian-batch run [--limit N] [--dry-run]
hinddian-batch run-force   # 已批准项目草稿不足阈值也分析
hinddian-classify run|stats|proposals|approve|reject|…   # 若仍启用 pi 路径
```

定时：`hinddian-classify.timer` / batch service（见 deploy）；日志 `/var/log/hinddian-classify.log`。

## 与华为仪表盘

华为 hinddian 经 SSH `dmit-vps` 调 CLI：统计、批准项目、**Agent 修正**（`list_corrections` / `decide_correction`）。  
前端写操作带 `X-Hinddian: 1`；公网 mTLS。

## 状态目录

| 路径 | 内容 |
|------|------|
| `/var/lib/hinddian/drafts/` | 会话草稿 |
| `/var/lib/hinddian/agent_corrections/` | Agent 修正队列 |
| `/var/lib/hinddian-classify/` | proposals / ledger / archive / backups |
| `/var/lib/hinddian/hindsight-sync*.json` | 同步状态（华为侧为主） |

## 安装（DMIT）

```bash
tar … → /opt/hinddian-classify/src && bash /opt/hinddian-classify/src/deploy/install-dmit.sh
systemctl enable --now hinddian-classify.timer
```

## 版本摘要

| 版 | 要点 |
|----|------|
| v0.4 | 原子笔记；草稿不进 vault；batch 阈值+批准；hindsight-sync |
| v0.5 | hinddian-memory；Jev hooks；禁止 Agent retain；OTLP 关 |
| v0.5+ | 会话桶 + 白名单；Jev 写失败不记；门控 upsert / Agent 修正队列 |
