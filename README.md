# hinddian · Obsidian 笔记

采集 Claude Code、Codex 或 Magpie 的会话，提炼成草稿，再按项目批量整理成供人阅读、编辑的 Obsidian 笔记。笔记之间的同步由 Obsidian LiveSync 负责。

## 本机运行

1. 按[宿主插件安装说明](plugins/INSTALL.md)启用 `SessionStart` 和 `Stop` 采集 hooks。Magpie 使用[独立适配器](adapters/magpie/README.md)。
2. hooks 在新会话启动、旧会话闲置后触发 finalize。Jev 在默认的 `http://127.0.0.1:3425/v1/systemone` 做保留判断，符合条件的会话写成一份草稿。已有远端采集地址时，可用 `HINDDIAN_CAPTURE_MODE=local` 切到本地。
3. 运行 `python3 classify/hinddian_batch.py run`。它按项目合并待处理草稿、写入笔记库，并把草稿移到 `processed`。定时运行方式见[批处理说明](classify/README.md)。

## 路径配置

hooks、batch 和可选仪表盘共用 `~/.config/hinddian/config.json`（支持 `XDG_CONFIG_HOME` 或 `HINDDIAN_CONFIG`）。环境变量优先，同一行内按列出的顺序取值，路径支持 `~`。

| JSON 键 | 环境变量 | 默认 |
| --- | --- | --- |
| `vault` | `HINDDIAN_VAULT`、`VAULT_ROOT`、`HC_VAULT` | `~/Obsidian/vault` |
| `drafts_dir` | `HINDDIAN_DRAFTS_DIR`、`HB_DRAFTS` | `~/Obsidian/drafts` |
| `processed_dir` | `HINDDIAN_PROCESSED_DIR`、`HB_PROCESSED` | 草稿目录的同级 `processed` |
| `state_dir` | `HINDDIAN_STATE_DIR`、`HB_BASE` | `$XDG_STATE_HOME/hinddian` 或 `~/.local/state/hinddian` |
| `jev_log` | `HINDDIAN_JEV_LOG` | 状态目录下的 `jev-decisions.jsonl` |

兼容旧批处理配置。只设 `HB_BASE` 时，草稿默认读 `$HB_BASE/drafts`。`HINDDIAN_VAULT_LOCK` 可覆盖状态目录下的 `vault.lock`。草稿和已处理目录都在笔记库外。会话缓冲默认位于 `~/.config/hinddian/hooks/sessions`，可由 `HINDDIAN_HOOK_DIR` 指定其他 hooks 数据目录。

## 开发

```sh
pip install -e '.[dev]'
python tools/sync_hooks.py
python -m pytest
```

修改 `hooks/` 或共享的 finalize、脱敏、Jev 和路径模块后，重新生成 Claude Code、Codex 和 Magpie 的脚本副本。CI 用 `tools/sync_hooks.py --check` 校验。

## 进一步说明

- [架构与边界](ARCHITECTURE.md)
- [采集、脱敏和来源](docs/PIPELINE.md)
- [可选的仪表盘](docs/DASHBOARD.md)
- [可选的 HTTP 采集与运维迁移](deploy/api-host/DEPLOY.md)
