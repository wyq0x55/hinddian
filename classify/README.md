# classify · 会话草稿 → 原子笔记（vault 主机）

跑在 **vault 主机**（vault 所在机）。hooks / MCP `push_draft` 产生的**会话桶草稿**落在 `/var/lib/hinddian/drafts/<项目>/`，由 **`hinddian_batch.py`** 合并进 Obsidian **原子笔记**——**永不一会话一笔记**，也不再写 `DECISIONS.md` / `LESSONS.md` 大文件。

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
API 主机 hinddian-hindsight-sync → Hindsight 索引
```

Agent 查重 / 召回只用 **`mcp__hinddian-memory__recall`**（及 `list_notes` / `get_note`），**不要** `mcp__hindsight__recall`，**不要**写旧三件套路径。

## 命令

```bash
hinddian-batch run [--limit N] [--dry-run]
hinddian-batch run-force   # 已批准项目草稿不足阈值也分析
hinddian-batch gate --json            # 各项目草稿数 / 状态（仪表盘用）
hinddian-batch approve <project>      # 等同仪表盘「开始批量分析」
```

定时：`hinddian-classify.timer`（每 15 分钟 `hinddian-batch run`；单元名沿用旧名）与 `hinddian-batch-force.timer`（每日 `run-force`）；日志 `/var/log/hinddian-classify.log`。

## 与 API 主机 仪表盘

API 主机经 SSH（`CLASSIFY_SSH_HOST`）调 `hinddian-batch`（闸门 / 批准项目）与 `hinddian-memory-cli`（笔记、Agent 修正）。
API 直接跑在 vault 主机上（设 `VAULT_ROOT`）时全部本地执行。界面说明见 [`docs/DASHBOARD.md`](../docs/DASHBOARD.md)。

## 状态目录

| 路径 | 内容 |
|------|------|
| `/var/lib/hinddian/drafts/` | 会话草稿 |
| `/var/lib/hinddian/agent_corrections/` | Agent 修正队列 |
| `/var/lib/hinddian/processed/` | 已合并的草稿 |
| `/var/lib/hinddian/gate.json` · `batch-ledger.jsonl` | 项目批准状态 · 批处理记录 |
| `/var/lib/hinddian/hindsight-sync*.json` | 同步状态（API 主机 侧为主） |

## 安装（vault 主机）

`classify/hinddian_batch.py` 与 `deploy/vault-host/hinddian-memory-cli` 在仓库里是 **100755**。`/usr/local/bin/hinddian-batch`（及 `hinddian-memory-cli`）由安装脚本写成 **755 的 python3 包装**（不再依赖软链目标的 +x）。`git pull` / `rsync` 之后若未重跑安装脚本，会出现 `Permission denied`（rc=126）或旧包装指向过期路径。

```bash
git clone https://github.com/wyq0x55/hinddian /opt/hinddian   # 之后用 git pull / rsync 更新
# 每次同步代码后必须重跑（chmod 目标文件 + 刷新 /usr/local/bin 包装与 timer）：
bash /opt/hinddian/classify/deploy/install-vault-host.sh

# 从旧版升级：旧的 pi 归类（Mode B）已删除，如还装着可清理：
rm -f /usr/local/bin/hinddian-classify; rm -rf /opt/hinddian-classify/pi-agent /opt/hinddian-classify/skills
```

## 版本摘要

| 版 | 要点 |
|----|------|
| v0.4 | 原子笔记；草稿不进 vault；batch 阈值+批准；hindsight-sync |
| v0.5 | hinddian-memory；Jev hooks；禁止 Agent retain；OTLP 关 |
| v0.5+ | 会话桶 + 白名单；Jev 写失败不记；门控 upsert / Agent 修正队列 |
