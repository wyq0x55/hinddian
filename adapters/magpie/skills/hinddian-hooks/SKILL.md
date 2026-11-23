---
name: hinddian-hooks
description: Install and check Magpie Library Hooks that capture drafts for Obsidian.
---

# hinddian Magpie 采集 hooks

用户要求安装时，先确认 Magpie 已创建本机 `library.json`。在本 skill 目录运行 `python3 install.py`，Windows 使用 `install.ps1`。安装器会先备份 `library.json`，再配置 `hinddian-session-start` 和 `hinddian-turn-end`。

使用 `python3 setup.py --check` 查看本机采集模式、草稿目录和 Jev 配置。默认本地处理，草稿写入 `~/Obsidian/drafts`。如有旧的 HTTP 采集配置，可在用户要求切换时运行 `setup.py --local`。WebDAV 可分发本 skill，每台电脑仍须安装自己的 Library Hooks。
