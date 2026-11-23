# 本机笔记管线与可选 HTTP 服务

## 本机运行

使用同一用户的配置启动会话采集 hooks 和 [batch 定时任务](../../classify/README.md)。默认目录是 `~/Obsidian/vault`、`~/Obsidian/drafts` 和 `~/Obsidian/processed`，批处理和日志状态独立于 vault。Obsidian LiveSync 负责笔记库同步。

完成数据备份和本机迁移后，可停用旧的 `hinddian-hindsight-sync.service`、`.timer`、本管线用的 Hindsight API、旧 `hinddian-batch-force.service`、`.timer`、SSH 笔记 CLI 和修正队列。旧服务环境中的 `HINDDIAN_SYNC_KICK` 和 Caddy 的 `/mcp`、OAuth、`.well-known` 路由也可撤除。所有采集端使用本地写入后，旧华为 `hinddian.service` 也可停用。wan37 只需为 `hinddian_batch.py run` 保留用户级定时任务以及供 Jev 和 batch 使用的模型端点。

## 可选仪表盘或 HTTP 采集器

使用同一个 vault、drafts、processed 和状态目录运行 API。可参考 [`hinddian-api.service.example`](../systemd/hinddian-api.service.example) 设置 checkout 和虚拟环境位置。默认监听 `127.0.0.1:8787`，端口冲突时同时调整 `HINDDIAN_PORT` 和反代 upstream。

- 仪表盘凭据是 `AUTH_TOKEN`。mTLS 反代可使用 [`Caddyfile.snippet`](Caddyfile.snippet)，通过 `X-Hinddian-Dashboard` 注入仪表盘凭据。
- 采集凭据沿用 `HINDDIAN_MCP_TOKEN` 变量名，供可选的 HTTP 采集端使用。TLS 反代可参考 [`caddy-hinddian-collector.snippet`](caddy-hinddian-collector.snippet)，只放行采集和连通性路径。客户端设置 `HINDDIAN_MEMORY_URL=https://<host>:8444/hinddian` 及采集凭据，私有 CA 可通过 `HINDDIAN_CA_FILE` 指定。
- 两个凭据分开设置并由本机私有的 `EnvironmentFile` 提供。`HINDDIAN_ALLOW_NO_AUTH` 仅供本地开发。
