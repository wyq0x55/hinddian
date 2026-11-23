---
name: doctor
description: Diagnose hinddian session capture and draft creation.
---

# hinddian 采集诊断

1. 在插件根目录运行 `python3 scripts/setup.py --check`。
2. 检查宿主是否启用了 `SessionStart` 和 `Stop`。打开新会话会触发前一会话 finalize。
3. 查看 `~/.config/hinddian/hooks/finalize.log` 和配置的 Jev 状态日志。`keep_false` 表示会话被筛掉，`jev_unavailable` 表示先保留缓冲等待重试。
4. 检查配置的 drafts 和 processed 目录。草稿已进入 processed 时，到 Obsidian 查看对应项目。
