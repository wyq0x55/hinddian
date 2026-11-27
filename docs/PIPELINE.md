# 会话到笔记

1. **采集**。`Stop`（Magpie 为 `turn-end`）从最终可见回复摘取「原行为」「改进」「取舍」「验证」。独行 Markdown 标题或强调标题的可见文字含「附录」时结束当前段。链接按显示文字判断，带同行正文的强调标签和普通引用句逐字保留。缺段默认记一条跳过日志。设置 `no_closing: "summary"` 时取前 `summary_chars` 字，标记 `kind: summary`。
2. **草稿**。同一会话、同一来源的轮次可追加到同一份 Markdown。记录原始 `session_id`、主机、工作目录 basename、仓库、分支、短 HEAD、带时区的时间和项目。脏工作区的短 HEAD 附 `-dirty`，缺失的字段为空。项目依次看显式项目、repo/cwd 能匹配的已有项目、repo 名和 `通用-未定`。重复轮次在待处理目录和归档中均可识别。
3. **本地诊断**。采集直接写入草稿，正文保留原文。脚本静默退出，写锁竞争、跳过或异常只记录元数据。`capture.log` 上限为 128 KiB。
4. **整理**。batch 以 Git 提交为基线，将草稿和已有笔记摘要交给模型。笔记 `sources` 使用 `session_id@commit`。缺少来源的草稿暂留原地。写入限于项目、技巧及 INDEX，既有笔记和枢纽页的人工内容保留。成功后草稿移入 `processed`。
5. **阅读**。在 Obsidian 查看和修改笔记，或通过仪表盘查看草稿与处理状态。

`SessionStart` 可用于检查本地配置。旧 HTTP hook 配置需迁移为 `capture_mode: "local"`。详见[部署说明](../deploy/api-host/DEPLOY.md)。
