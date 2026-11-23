---
name: hinddian-hooks
description: Install and check Magpie Library Hooks that capture drafts for Obsidian.
---

# hinddian Magpie 采集 hooks

用户要求安装时，先确认 Magpie 已创建本机 `library.json`。在本 skill 目录运行 `python3 install.py`，Windows 使用 `install.ps1`。安装器会先备份 `library.json`，再配置 `hinddian-session-start` 和 `hinddian-turn-end`。

使用 `python3 setup.py --check` 查看本机采集配置。最终可见回复符合四段格式时写入 `~/Obsidian/drafts`。旧 HTTP 配置需由用户决定迁移或停用。WebDAV 可分发本 skill，每台电脑仍须安装自己的 Library Hooks。
