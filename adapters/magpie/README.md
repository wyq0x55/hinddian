# Magpie 会话采集适配器

在采集主机安装 `hinddian-session-start` 和 `hinddian-turn-end` 两个 Library Hooks。适配器使用本机 hinddian 配置和草稿目录。

从 Magpie Library → Skills 安装 `wyq0x55/hinddian` 的 `hinddian-hooks` skill，或使用 `magpie plugin add github:wyq0x55/hinddian` 后调用 `hinddian_install`。也可直接运行 skill 目录里的 `install.py`（Linux/macOS）或 `install.ps1`（Windows）。

安装器备份本机 `library.json`，将采集脚本放入版本化的本机目录，再接入两个 hooks。WebDAV 可分发 skill，Library Hooks 仍须在每台采集电脑上安装。用 `setup.py --check` 确认设置，笔记库随后由 [batch](../../classify/README.md) 整理。
