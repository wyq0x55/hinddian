# hinddian 架构

```text
宿主 SessionStart / Stop
  → 本机会话缓冲
  → finalize + Jev
  → drafts/<project>/session-*.md
  → hinddian_batch.py
  → Obsidian 原子笔记 + processed/<project>/
```

- `hooks/` 按会话 ID 缓冲白名单用户消息和助手最终回复，后台运行 finalize。`tools/sync_hooks.py` 为 Claude Code、Codex 和 Magpie 生成可独立运行的标准库脚本副本。
- `src/hinddian/session_finalize.py` 负责校验、再次脱敏、调用 Jev 和处理保留结果。`draft_store.py` 用原始会话 ID 标记草稿，使用安全路径及原子写入。可选的 HTTP 采集器使用同一套 finalize 与落盘逻辑。
- `classify/hinddian_batch.py` 根据草稿和库内已有笔记生成 `create` / `update` 操作，按相似度合并并维护相关链接。模型调用之后，在写锁内重新读取笔记和校验草稿。内容指纹可识别大小和 mtime 都没变的编辑。旧笔记中的自定义 frontmatter、段落和历史取代信息由通用保留逻辑透传。
- `web/` 仪表盘展示流水线计数、草稿和 Jev 判断。Obsidian 是正式笔记的阅读与编辑入口，跨设备同步由 LiveSync 管理。

见[入库流程](docs/PIPELINE.md)、[目录配置](README.md#路径配置)和[批处理说明](classify/README.md)。
