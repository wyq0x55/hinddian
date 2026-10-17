# classify · 待入库 → pi 归类 → Obsidian 主题笔记

跑在 **DMIT**（vault 所在机）。华为 worker 提炼出的 `项目/*/待入库/*.md` 草稿，由 **pi 1.x**（`@earendil-works/pi-coding-agent`，非 pi-durable）逐条归类，合并进主题笔记——**永不一会话一笔记**。

## 流程（Mode B）

```
待入库草稿 ──pi(-p, --no-session)──► JSON 合并方案 ──► runner 校验
   ├─ topic/agent-usage-tips（00-系统/agent使用技巧.md）  → 自动写入（备份 + 原子替换 + 文件锁）
   ├─ 项目主题（项目/<名>/DECISIONS|LESSONS|PROJECT_STATE.md）→ 待确认建议（proposals/），确认后才写
   └─ ignore                                               → 归档并记原因
源草稿处理完即移出 vault → /var/lib/hinddian-classify/archive/<日期>/{classified,ignored,failed}/
```

- agent使用技巧 自动写入的条件：置信度 ≥ 0.6 且未命中密钥正则；否则也转成待确认建议。
- 项目类建议可以指向新项目（例如 `项目/ut-agent/…`）；确认时按 `_模板` 建文件。
- 草稿 10 分钟内被改过的先跳过（worker 可能还在 upsert 同一 document_id）。
- pi 失败 3 次的条目移到 `archive/…/failed/`。

## pi 配置（只在 DMIT，本地、不进 Magpie Library）

- 运行时：`/opt/node22`（私有 Node 22，系统 node 仍是 v20）；`/usr/local/bin/pi` 包装器 → `/opt/pi`。
- `PI_CODING_AGENT_DIR=/opt/hinddian-classify/pi-agent`（独立 agent 目录，不碰 `~/.pi`，Magpie 不会同步它）
  - `models.json`：provider `magpie` → `http://127.0.0.1:3425/v1`，模型 `group/auto-flash`
  - `mcp.json`：`hindsight` → `http://124.70.90.224/hindsight/mcp/wanwan/`，`Authorization: Bearer ${HINDSIGHT_API_KEY}`；只暴露 `recall`（其余工具 hidden）
  - `AGENTS.md`：归类铁律
- skill：`/opt/hinddian-classify/skills/topic-merge/SKILL.md`，prompt 首行 `/skill:topic-merge …` 展开
- pi 只给 `--tools mcp__hindsight__recall`：没有 bash / read / write，写入全部由 runner 做。目标笔记全文由 runner 内联进 prompt。
- 密钥：`/etc/hinddian-classify/secrets.env`（root 600，`HINDSIGHT_API_KEY=`），不进 git。

## 命令

```bash
hinddian-classify run [--limit 5] [--item 项目/笔记系统/待入库/doc-xxx.md] [--dry-run]
hinddian-classify stats --json
hinddian-classify proposals --json [--status pending|applied|rejected|all]
hinddian-classify recent --json
hinddian-classify approve <id>
hinddian-classify reject <id> --reason '…'
```

## 定时

`hinddian-classify.timer`：每 15 分钟一次，每次最多 5 条（`MemoryMax=600M`，单个 pi 进程约 100MB RSS，单条约 5–15 秒）。日志 `/var/log/hinddian-classify.log`。

## 确认流程（华为 hinddian ↔ DMIT）

hinddian 后端用华为已有的 root SSH 信任（与 session-distill worker 同一把 key、同一个 `dmit-vps` 别名）调用 `ssh dmit-vps hinddian-classify …`（ControlMaster 复用连接，读接口缓存 15s）。不开新公网端口、不加新 token。前端 POST 必须带 `X-Hinddian: 1` 头（防跨站请求），整站仍由 Caddy mTLS（Magpie 同一张客户端证书）守门。

## 状态目录 `/var/lib/hinddian-classify`（700）

`proposals/*.json` · `ledger.jsonl` · `archive/` · `backups/`（写入前的旧版本，不放 vault，避免 .bak 被 LiveSync 同步）· `attempts.json` · `last_run.json`

## 安装

```bash
# 在 DMIT
tar … → /opt/hinddian-classify/src && bash /opt/hinddian-classify/src/deploy/install-dmit.sh
systemctl enable --now hinddian-classify.timer
cp deploy/logrotate.conf /etc/logrotate.d/hinddian-classify
```
