# 批量整理 Obsidian 笔记

`hinddian_batch.py` 按项目读取库外的会话草稿，合并成决策、经验和全局技巧。自动运行跳过 `holdout`，`通用-未定` 只产出全局技巧。成功写入后，草稿移到 `processed`。路径与采集共用[环境变量和 JSON 配置](../README.md#路径配置)。

```sh
python3 classify/hinddian_batch.py run
python3 classify/hinddian_batch.py process my-project --dry-run
python3 classify/hinddian_batch.py process my-project --dir ./comparison-drafts --batch 10
python3 classify/hinddian_batch.py rebuild-hubs
```

`process --dir` 可指定独立的输入目录，用于手工比较。用 `--dry-run` 时保留笔记库与输入草稿。`HB_BATCH` 控制每批草稿数（默认 20），`HB_RUN_MAX_BATCHES` 控制一次 `run` 每项目最多处理的批数（默认 3）。批处理默认访问 `HB_GATEWAY=http://127.0.0.1:3425/v1/chat/completions`，模型由 `HB_MODEL` 指定。

Linux 上可在运行 Obsidian 的用户账户下执行 `bash classify/deploy/install-user.sh`。该脚本安装用户级 `hinddian-classify.timer` 和 `.service`，每 15 分钟运行，输出写入 user journal。路径建议统一写入 `config.json`，定时任务专用环境变量可写入 `~/.config/hinddian/batch.env`。
