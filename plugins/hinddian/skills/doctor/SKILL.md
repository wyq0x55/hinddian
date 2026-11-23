---
name: doctor
description: Diagnose hinddian session capture and draft creation.
---

# hinddian 采集诊断

1. 在插件根目录运行 `python3 scripts/setup.py --check`。
2. 检查宿主 `Stop` hook，确认最终回复含有四个指定标题。
3. 查看 `~/.config/hinddian/hooks/capture.log`。`no_closing` 表示回复缺段，`VaultBusy` 表示写锁被占用。
4. 检查配置的 drafts 和 processed 目录。草稿已进入 processed 时，到 Obsidian 查看对应项目。
