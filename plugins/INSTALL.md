# 安装会话采集插件

插件包含 `SessionStart` 和 `Stop` hooks。需要 Python 3.11 或更新版本，并且宿主进程要能通过 PATH 找到 `python3`。Magpie 的 Windows 适配器也支持 `py` 和 `python`。

## Claude Code

在 Claude Code 中从项目 marketplace 安装 `hinddian`。

```text
/plugin marketplace add wyq0x55/hinddian
/plugin install hinddian@hinddian-plugins
```

从本地 checkout 安装时，marketplace 地址可使用仓库的本地路径。

## Codex

从仓库的 `.agents/plugins/marketplace.json` 所声明的 marketplace 安装 `hinddian`。插件自带 `.codex-plugin/hooks.json`，按宿主提示启用和信任 hooks。插件入口在 `plugins/hinddian`。

## 确认采集模式

在 checkout 根目录检查当前用户的有效设置。

```sh
python3 plugins/hinddian/scripts/setup.py --check
```

hooks 直接将符合格式的最终可见回复写到 `~/Obsidian/drafts`。旧配置带有远端地址时，将 `capture_mode` 显式设为 `local`。在 wan37 直接配置 Codex 用户级 hook 的片段见[运维说明](../deploy/api-host/DEPLOY.md)。

用一轮包含「原行为」「改进」「取舍」「验证」的最终回复验证采集，完成后在草稿目录核对来源。缺段和失败信息见 `~/.config/hinddian/hooks/capture.log`。`SessionStart` 可用于配置检查，实际采集在 `Stop`。
