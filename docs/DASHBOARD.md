# 仪表盘（hinddian）

入口（手机 / 桌面，既有 mTLS 客户端证书（若仪表盘启用 mTLS））：

`https://124.70.90.224:8443/`

本机调试：`http://127.0.0.1:8787/`（无公网证书）。

## 图谱（顶部流水线）

从左到右示意：

**收件箱 → 隔离 → 草稿·按项目 → 分析 → Obsidian → Hindsight**

| 节点 | 含义 |
|------|------|
| 收件箱 | 华为原始会话（历史 OTLP/inbox；现行主写入是 hooks 草稿） |
| 隔离 | 过滤掉的会话及原因 |
| 草稿·按项目 | `/var/lib/hinddian/drafts` 按项目计数（会话桶草稿） |
| 分析 | DMIT batch：批量（需批准）/ 增量（自动）/ 技巧（自动） |
| Obsidian | 原子笔记总数（真相源） |
| Hindsight | 已同步索引数；状态来自 sync timer |

连线「分析 → 技巧」等为示意；刷新异常时硬刷新缓存。

## 分批分析（按项目）

- **未批准项目**：草稿达到阈值（默认 20）后点「开始批量分析」
- **已批准项目**：之后新草稿走增量，可不点批准
- 批准只影响该项目后续自动化，不代替「Agent 修正」队列

## Agent 修正

卡片 **「Agent 修正」**：Agent 对 `decision` 等提交的 `suggest_correction`。

- **确认**：按建议写入 Obsidian（upsert/supersede）
- **拒绝**：记录原因，不写笔记

队列文件：DMIT `/var/lib/hinddian/agent_corrections/ac-*.json`。

政策摘要：

- tip / preference / 当面纠错 → Agent 可直写，不一定出现在此队列
- decision → 应出现在此或等你口头 `user_confirmed`

## 其他卡片

| 卡片 | 作用 |
|------|------|
| 待确认建议 | 旧/并行 classify proposals（按目标文件确认） |
| 归类记录 | 最近会话→主题合并记录 |
| 收件箱最近 / 主题 | 运维浏览 |

## API（同源，需会话/mTLS）

常用：`/api/health`、`/api/stats`、`/api/corrections?status=pending`、`POST /api/corrections/{id}/approve|reject`、项目批准相关 `/api/…`（见 `web/app.js`）。

写操作前端带 `X-Hinddian: 1` 防 CSRF；公网靠 Caddy mTLS。
