# 笔记流水线仪表盘

可选 FastAPI 服务读取本机的笔记、草稿目录和历史 Jev 日志。仪表盘提供两个页签。

| 页签 | 内容 |
| --- | --- |
| 流水线 | 会话最终回复 → 草稿 → 批处理 → Obsidian。显示待处理、已处理以及笔记分类计数。 |
| 草稿 | 待处理草稿、最近已处理草稿、按项目计数及历史 Jev 记录。可点开草稿正文。 |

`/api/overview` 提供汇总，`/api/batch` 提供各项目的待处理与已处理计数。草稿详情使用 `/api/draft`，列表使用 `/api/drafts`。Jev 记录使用 `/api/jev-decisions`。正式笔记在 Obsidian 打开。

访问需要仪表盘 `AUTH_TOKEN`。反代可注入 `X-Hinddian-Dashboard`。部署配置见[运维说明](../deploy/api-host/DEPLOY.md)。
