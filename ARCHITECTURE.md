# hinddian 架构

```text
宿主 Stop / turn-end
  → 从最终可见回复读取四段
  → drafts/<project>/session-*.md
  → Git 快照 + hinddian_batch.py 模型整理
  → Obsidian 原子笔记 + processed/<project>/
```

- `hooks/` 读取最终可见回复。`tools/sync_hooks.py` 为 Claude Code、Codex 和 Magpie 生成可独立运行的标准库脚本。
- `draft_store.py` 按会话和来源归集草稿，使用非阻塞写锁及原子写入。`Stop` 的故障和跳过事件记录在本地。
- `classify/hinddian_batch.py` 调用模型生成 JSON 操作，以来源和路径校验约束写入。写锁内重新读取笔记、校验草稿并合并正文。内容指纹可识别大小和 mtime 都没变的编辑。Git diff 记录本次整理的文件变化。
- `web/` 仪表盘展示流水线计数、草稿和历史 Jev 记录。Obsidian 提供正式笔记的阅读与编辑入口。

见[入库流程](docs/PIPELINE.md)、[目录配置](README.md#路径配置)和[批处理说明](classify/README.md)。
