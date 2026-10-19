# 一轮会话如何进笔记

## 自动路径（host hooks）

1. **开会话（session-start）**
   - Finalize 上一会话 / 空闲缓冲：Jev `keep` → 一次 `push_draft`（或丢弃）
   - 注入固定的记忆路由块（不含数量/日期，保证提示词缓存前缀稳定）
   - 之后每条用户消息由 UserPromptSubmit hook 自动 recall，命中才附 ≤3 条短摘要（`HINDDIAN_AUTO_RECALL=0` 关闭）

2. **每回合结束（turn-end）**
   - 白名单：用户话 + 最终助手回复
   - 追加到本机 `session_id` 缓冲
   - **不**远程写草稿

3. **Finalize 触发**
   - 新开会话、空闲约 30 分钟、或切换项目
   - Jev：本机 System One（`JEV_BASE_URL`）→ 云端 TypeSafe → 都失败则**暂不记**，缓冲保留、退避重试

4. **草稿**
   - API 主机/vault 主机：`/var/lib/hinddian/drafts/<项目>/…`
   - 脱敏；尚不是笔记

5. **蒸馏 / 批处理（vault 主机）**
   - 新项目：满阈值（默认 20 会话草稿）+ 仪表盘批准
   - 已批准：增量自动；技巧可自动。**增量运行里涉及决策的改动**（新建 / 改写 / 取代决策）不直接写，
     进仪表盘「Agent 修正」（标「批处理增量」）等你批准；经验、技巧照旧自动写。首次批量（你点「开始」）可直接写决策
   - 产出原子笔记（add/update/supersede）；新建遇到同 id 自动加后缀，不会覆盖已有笔记

6. **索引**
   - `hinddian-hindsight-sync`：active → retain；删除/非 active → 删索引
   - 送进索引的是「标题 + 人写的引用行 + 场景/做法/理由 + 人写的段落」，不含 frontmatter 和自动生成的
     所属/相关/取代链接；是否需要重新 retain 只看这部分内容，重建链接或改日期不会触发
     （升级后第一次同步会把全部笔记重新 retain 一遍，每轮最多 `HS_MAX_RETAIN` 条）

## 显式旁路

- `upsert_note`（门控）或 `suggest_correction` → 仪表盘「Agent 修正」
- `upsert_note` 新增时若已有相近笔记（同类型、同项目，标题/做法 bigram 相似度 ≥ `HINDDIAN_DEDUPE`，默认 0.40），
  返回 `similar_exists` + `candidates`，由 Agent 改用 `update` 合并，确是新主题再带 `force_new: true`
- Obsidian 仍为 SoT；Hindsight 跟同步

## 常见进不了笔记

| 原因 | 现象 |
|------|------|
| Host hooks 未装 / 未 trust | turn-end 未跑 → 无缓冲 |
| Jev `keep=false` 或 `source=none` | 会话被丢弃 |
| 新项目未满阈值且未批准 | 草稿堆积在 drafts |
| 白名单抽空 | 本轮几乎无用户/助手正文 |
