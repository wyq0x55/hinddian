---
name: setup
description: Check or configure hinddian session capture for Obsidian.
---

# hinddian 采集设置

在插件根目录执行 `python3 scripts/setup.py --check`，报告当前模式和路径。默认本地采集，无需创建配置文件。用户要求从旧 HTTP 采集切回本机时使用 `python3 scripts/setup.py --local`。

用户明确要使用 HTTP 采集时，执行 `python3 scripts/setup.py --url <collector-base-url>`。采集凭据使用安全的本机环境变量 `HINDDIAN_MCP_TOKEN`。引导用户启用并信任插件的 `SessionStart` 和 `Stop` hooks。
