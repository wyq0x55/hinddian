# 仪表盘（hinddian）

入口：`https://<api-host>:8443/`（mTLS 客户端证书；Caddy 校验后代为提交 `AUTH_TOKEN`）。
本机调试：`scripts/run_dev.sh` 后开 `http://127.0.0.1:8787/`（未设 token 时为免鉴权开发模式）。

手机优先：iPhone 上底部四个页签，所有按钮 ≥44pt，输入框 16px（Safari 不会自动放大）。
Safari「分享 → 添加到主屏幕」后像 App 一样全屏打开（带图标）。

## 页签

| 页签 | 内容 |
|------|------|
| **待批准**（默认） | **Agent 修正**：涉及 decision 的新增 / 修改 / 取代 / 作废都排在这里；卡片显示改动字段，修改已有笔记时同时显示旧值（删除线）；「Agent 称用户已确认」只是说明，不能代替你批准。「批准写入」会再确认一次，「拒绝」可填原因。<br>**等待批量分析的项目**：新项目攒够阈值（默认 20 份会话草稿）后点「开始批量分析」，之后新草稿自动增量合并。 |
| **笔记** | 按类型（决策 / 经验 / 技巧）和项目浏览原子笔记；搜索框走和 Agent 自动召回**同一套检索**（Hindsight，不可用时本地检索），可以直接检验召回效果。点开看全文、取代关系和相关笔记。 |
| **草稿** | 每个项目的会话草稿：积累中（进度条 / 阈值）、等你批准、自动增量、只提技巧。 |
| **概览** | 笔记数、待批准数、草稿积压、Hindsight 同步；流水线 hooks → 草稿 → 批处理 → Obsidian → Hindsight，每段出错时标红并给出原因。 |

页签上的红色数字 = 待批准（修正 + 等待批量分析的项目）。页面回到前台时自动刷新，平时每分钟刷新一次。

## 接口（仪表盘通道，均需 `AUTH_TOKEN`）

| 接口 | 作用 |
|------|------|
| `GET /api/overview` | 概览与页签角标 |
| `GET /api/notes?type=&project=&q=` | 列表（不含项目首页等枢纽页）；带 `q` 时为检索 |
| `GET /api/note?id=` | 单条笔记 |
| `POST /api/recall` | 与 Agent 相同的 recall |
| `GET /api/gate` · `POST /api/gate/{project}/approve` | 批处理闸门 |
| `GET /api/corrections` · `POST /api/corrections/{id}/approve|reject` | Agent 修正队列 |

写操作需要 `X-Hinddian: 1` 头（防 CSRF）。vault 在本机（设了 `VAULT_ROOT`）时全部本地执行，否则经 SSH 到 vault 主机。

## 真机才能验证的

- Safari 选择 mTLS 客户端证书的弹窗（以及证书过期时的表现）
- 「添加到主屏幕」后的启动画面与状态栏颜色
