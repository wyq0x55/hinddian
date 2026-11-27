---
name: setup
description: Check local hinddian session capture settings for Obsidian.
---

# hinddian 采集设置

在插件根目录执行 `python3 scripts/setup.py --check`，报告有效路径和缺段策略。默认本地采集。兼容旧远端配置时，征得用户授权后将 hinddian 的 `capture_mode` 设为 `local`。引导用户检查并授权信任 `Stop` hook。
