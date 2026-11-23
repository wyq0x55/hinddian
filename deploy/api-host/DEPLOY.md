# wan37 本机整理与迁移

## 定时整理

运维以 `wan37` 运行整理。先确认 `~/Obsidian/vault` 是独立 Git 仓库，有初始提交及本地提交身份。草稿和归档默认为 `~/Obsidian/drafts` 和 `~/Obsidian/processed`。采集进程和整理服务使用同一份路径和锁配置。

仓库提供 [service](../../classify/deploy/hinddian-classify.service) 和 [timer](../../classify/deploy/hinddian-classify.timer)。`ExecStart` 使用 `~/.local/bin/hinddian-batch`，可由[安装脚本](../../classify/deploy/install-user.sh)从固定 checkout 创建，再启用每 15 分钟的用户级 timer。定时任务的 `HB_GATEWAY` 和 `HB_MODEL` 可放在 `~/.config/hinddian/batch.env`。stdout diff 在 `journalctl --user -u hinddian-classify.service`，快照和 diff 同时记到 `batch-ledger.jsonl`。

若需退出登录后继续运行，由运维执行 `loginctl enable-linger wan37`（可能需要管理员权限），再用 `loginctl show-user wan37 -p Linger` 核对。`systemctl --user list-timers hinddian-classify.timer` 显示下一次运行。

## Codex 采集示例

在 `~/.codex/hooks.json` 的既有 `hooks.Stop` 数组追加这一项。将 checkout 路径换成实际固定路径。

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/usr/bin/python3 /opt/hinddian/plugins/hinddian/hooks/turn_end_entry.py",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

先征得用户同意，再通过 Codex 的 `/hooks` 审阅并信任该条目，由 Codex 写入对应的 `trusted_hash`。已启用插件自带 Stop 的用户可选一处注册。

## 运维交接

- `dmit` 上 Magpie `library.json` 的旧 hook 指向已删除的华为 finalize 路由。由用户决定停用、升级为本地采集或另行安排草稿转移。
- 已迁移采集端的旧 `capture_mode: "http"` 或 `url` 要清理，或显式设置 `capture_mode: "local"`。检查旧 `hooks/sessions` 缓冲和 `holdout` 草稿是否需要保留。旧草稿的缺失提交只能从原始会话或对应仓库记录核实补录。
- 完成备份和迁移后，可停用 hinddian 专用的 Jev finalize 路由及旧华为 `hinddian.service`，撤除旧 Hindsight 同步、批处理强制触发服务、SSH 笔记 CLI、修正队列及旧 MCP/OAuth 反代路由。保留供单道整理使用的 `chat/completions` 端点。
- 可选仪表盘继续使用同一目录。`8787` 已有其它服务时，应选择空闲端口并同步调整 [API unit](../systemd/hinddian-api.service.example) 和反代 upstream。mTLS 反代使用 [Caddy 模板](Caddyfile.snippet) 和 `AUTH_TOKEN`。需显式 HTTP 提交草稿时，仅开放 [`push_draft` 模板](caddy-hinddian-collector.snippet) 并用独立的 `HINDDIAN_MCP_TOKEN`。
