# 一轮会话如何进笔记

## 自动路径（host hooks）

1. **开会话（session-start）**
   - Finalize 上一会话 / 空闲缓冲：Jev `keep` → 一次 `push_draft`（或丢弃）
   - 注入全局/项目路由表
   - Jev `should-recall`：仅决定是否提示 `recall`（不写记忆）

2. **每回合结束（turn-end）**
   - 白名单：用户话 + 最终助手回复
   - 追加到本机 `session_id` 缓冲
   - **不**远程写草稿

3. **Finalize 触发**
   - 新开会话、空闲约 30 分钟、或切换项目
   - Jev：本机 System One（`JEV_BASE_URL`）→ 云端 TypeSafe → 失败则 `source=none` **不记**

4. **草稿**
   - API 主机/vault 主机：`/var/lib/hinddian/drafts/<项目>/…`
   - 脱敏；尚不是笔记

5. **蒸馏 / 批处理（vault 主机）**
   - 新项目：满阈值（默认 20 会话草稿）+ 仪表盘批准
   - 已批准：增量自动；技巧可自动
   - 产出原子笔记（add/update/supersede）

6. **索引**
   - `hinddian-hindsight-sync`：active → retain；删除/非 active → 删索引

## 显式旁路

- `upsert_note`（门控）或 `suggest_correction` → 仪表盘「Agent 修正」
- Obsidian 仍为 SoT；Hindsight 跟同步

## 常见进不了笔记

| 原因 | 现象 |
|------|------|
| Host hooks 未装 / 未 trust | turn-end 未跑 → 无缓冲 |
| Jev `keep=false` 或 `source=none` | 会话被丢弃 |
| 新项目未满阈值且未批准 | 草稿堆积在 drafts |
| 白名单抽空 | 本轮几乎无用户/助手正文 |
