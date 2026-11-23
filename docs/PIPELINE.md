# 会话到笔记

1. **缓冲**。`Stop`（Magpie 为 `turn-end`）提取用户和助手的白名单内容，脱敏后按宿主会话 ID 写入本地缓冲。`SessionStart` 尝试 finalize 其他会话，`Stop` 也会尝试处理闲置的缓冲。`compact` 和 `resume` 不主动 finalize 其他会话。
2. **判断**。本地 finalize 再脱敏，调用 Jev。配置后可以从本地 System One 失败回退到 TypeSafe。Jev 不可用时保留缓冲并按退避策略重试；只有 Jev 保留的会话才进入草稿。
3. **草稿**。同一会话在同一项目下写入同一份 Markdown，frontmatter 记录 `session_id`。来源项目优先采用明确提示和已知 repo/cwd 名称，再考虑 repo 名、Jev 结果及 `通用-未定`。Jev 状态日志仅记录元数据。
4. **整理**。batch 将草稿段落和已有笔记摘要交给模型，按项目创建或更新笔记。写入后将对应草稿移到 `processed`，笔记的 `sources` 沿用草稿的原始 `session_id`。旧草稿仍可使用 `ingested_from` 或文件名。
5. **阅读**。在 Obsidian 查看和修改笔记。仪表盘可查看草稿与处理状态。

远端采集客户端可配置 `capture_mode: "http"` 和 `url`，向 HTTP 采集器提交同一种 finalize 请求。已有 `url` 的旧配置沿用 HTTP 模式。详见[部署说明](../deploy/api-host/DEPLOY.md)。
