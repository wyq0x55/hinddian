# hinddian · Obsidian 笔记

采集 Claude Code、Codex 或 Magpie 的每轮最终回复，再按项目批量整理成供人阅读、编辑的 Obsidian 笔记。Obsidian LiveSync 负责跨设备同步。

## 本机运行

1. 按[宿主插件说明](plugins/INSTALL.md)启用 `Stop`。Magpie 使用[独立适配器](adapters/magpie/README.md)。
2. hook 从最终回复摘取「原行为」「改进」「取舍」「验证」，直接写入本地草稿。采集不调用模型。
3. 运行 `python3 classify/hinddian_batch.py run`。整理器以 Git 提交为基线，按项目调用模型、合并待处理草稿、更新导航并记下 diff。定时运行方式见[运维说明](deploy/api-host/DEPLOY.md)。

## 路径配置

hooks、batch 和可选仪表盘共用 `~/.config/hinddian/config.json`（支持 `XDG_CONFIG_HOME` 或 `HINDDIAN_CONFIG`）。环境变量优先，同一行内按列出的顺序取值，路径支持 `~`。

| JSON 键 | 环境变量 | 默认 |
| --- | --- | --- |
| `vault` | `HINDDIAN_VAULT`、`VAULT_ROOT`、`HC_VAULT` | `~/Obsidian/vault` |
| `drafts_dir` | `HINDDIAN_DRAFTS_DIR`、`HB_DRAFTS` | `~/Obsidian/drafts` |
| `processed_dir` | `HINDDIAN_PROCESSED_DIR`、`HB_PROCESSED` | 草稿目录的同级 `processed` |
| `state_dir` | `HINDDIAN_STATE_DIR`、`HB_BASE` | `$XDG_STATE_HOME/hinddian` 或 `~/.local/state/hinddian` |
| `no_closing` | `HINDDIAN_NO_CLOSING` | `skip`，可设为 `summary` |
| `summary_chars` | `HINDDIAN_SUMMARY_CHARS` | 500 |

只设 `HB_BASE` 时，草稿默认读 `$HB_BASE/drafts`。`HINDDIAN_VAULT_LOCK` 可覆盖状态目录下的 `vault.lock`。草稿、归档和状态在库外。`HINDDIAN_HOOK_DIR` 可覆盖 `~/.config/hinddian/hooks`，其下的 `capture.log` 只记元数据。

## 开发

```sh
pip install -e '.[dev]'
python tools/sync_hooks.py
python -m pytest
```

修改 `hooks/` 或共享草稿模块后，重新生成三个宿主的脚本副本。CI 用 `tools/sync_hooks.py --check` 校验。

## 进一步说明

- [架构与边界](ARCHITECTURE.md)
- [采集和来源](docs/PIPELINE.md)
- [可选的仪表盘](docs/DASHBOARD.md)
- [定时运行与迁移](deploy/api-host/DEPLOY.md)
