# 批量整理 Obsidian 笔记

`hinddian_batch.py` 按项目读取库外的会话草稿，合并成决策、经验和全局技巧。自动运行跳过 `holdout`，`通用-未定` 只产出全局技巧。成功写入后，草稿移到 `processed`。路径与采集共用[环境变量和 JSON 配置](../README.md#路径配置)。

整理器使用 PyYAML 校验更新后的 frontmatter，保留无关字段里的自定义 YAML 标签。更新遇到递归 YAML 别名时，本批跳过并记录告警，保留原笔记和草稿。请将项目依赖安装到运行整理器的 Python 环境。

```sh
python3 classify/hinddian_batch.py run
python3 classify/hinddian_batch.py process my-project --dry-run
python3 classify/hinddian_batch.py process my-project --dir ./comparison-drafts --batch 10
python3 classify/hinddian_batch.py rebuild-hubs
```

`process --dir` 可指定独立的输入目录。输入目录必须位于归档根目录 `processed` 及其所有子目录之外。`--dry-run` 仅支持 `process`，需要干净的 Git 工作区，只请求和校验模型操作。`HB_BATCH` 控制每批草稿数（默认 20），`HB_RUN_MAX_BATCHES` 控制一次 `run` 每项目的批次数上限（默认 3）。因递归别名跳过的批次不占上限，`run` 继续处理后续草稿，结束时报告跳过批数并以非零状态退出。模型由 `HB_MODEL` 指定，`HB_GATEWAY` 默认为 `http://127.0.0.1:3425/v1/chat/completions`。

笔记库必须拥有自己的 Git 提交和本地提交身份。干净时使用 HEAD 作为快照，有改动时先把现有变更做成本地快照提交。这样手写改动和上次入库结果会留在本地历史里，定时器也能自动处理下一批。整理后的 diff 写入 stdout 与状态目录的 `batch-ledger.jsonl`。笔记改动留在工作区，下一次整理可将其提交到本地快照。

白名单为 `项目/`、`技巧/` 和 `00-系统/INDEX.md`，并拒绝符号链接。新笔记须有场景、做法、理由和真实 `session_id@commit` 来源。旧笔记追加新段落，项目枢纽页和 INDEX 只更新专属生成区。缺少来源的草稿应从原会话或仓库核实后补录。批内操作被拒时，输入草稿保留供检查重跑。

重建会保留无逐行标记的链接，其中可能有手写待补链接。确认某条无标记断链来自旧版整理器后，可指定枢纽路径、二级标题和链接行（省略 `- `）清理。该节的所有生成块标记必须成对且无嵌套，合计必须刚好匹配一行，围栏内的示例不计入。

```sh
python3 classify/hinddian_batch.py rebuild-hubs \
  --prune-legacy-link '项目/P/README.md' '经验' '[[项目/P/经验/已移除|已移除]]'
```

写入锁在 POSIX 上用 `flock`，在 Windows 上用 `msvcrt` 的字节锁。宿主和整理器应使用同一个状态目录，或显式指向同一个 `HINDDIAN_VAULT_LOCK`。

Linux 的用户级 service 和每 15 分钟 timer 见[运维说明](../deploy/api-host/DEPLOY.md)。
