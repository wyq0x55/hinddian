# 一轮会话如何进笔记

## 自动路径（host hooks）

1. **开会话（session-start）**
   - 静默启动上一会话 / 空闲缓冲的后台 finalize。Jev `keep` 通过后推送草稿。

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
   - 已批准：增量自动；技巧可自动。增量运行里的决策、经验、技巧均直接写入 Obsidian。显式选择 `review_decisions=True` 的调用仍可入可选审阅队列；默认不排队
   - 产出原子笔记（add/update/supersede）；新建遇到同 id 自动加后缀，不会覆盖已有笔记

6. **索引**
   - `hinddian-hindsight-sync`：active → retain；删除/非 active → 删索引
   - 送进索引的是「标题 + 人写的引用行 + 场景/做法/理由 + 人写的段落」，不含 frontmatter 和自动生成的
     所属/相关/取代链接；是否需要重新 retain 只看这部分内容，重建链接或改日期不会触发
     （升级后第一次同步会把全部笔记重新 retain 一遍，每轮最多 `HS_MAX_RETAIN` 条）

## 显式旁路

- `upsert_note` 或 `suggest_correction` → 直接写 Obsidian（含 decision；仪表盘审阅仅可选/旧队列兼容，**不要**用手调 `push_draft` 代替）
- `upsert_note` 新增时若已有相近笔记（同类型、同项目，标题/做法 bigram 相似度 ≥ `HINDDIAN_DEDUPE`，默认 0.40），
  返回 `similar_exists` + `candidates`，由 Agent 改用 `update` 合并，确是新主题再带 `force_new: true`
- Obsidian 保管笔记，Hindsight 为显式查询同步索引

## 常见进不了笔记

| 原因 | 现象 |
|------|------|
| Host hooks 未装 / 未 trust | turn-end 未跑 → 无缓冲 |
| Jev `keep=false` 或 `source=none` | 会话被丢弃 |
| 新项目未满阈值且未批准 | 草稿堆积在 drafts |
| 白名单抽空 | 本轮几乎无用户/助手正文 |
