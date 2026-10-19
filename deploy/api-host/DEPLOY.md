# hinddian · API 主机 部署

目标：仪表盘与 hinddian-memory API 在 API 主机（与 `/opt/session-distill` 同机）；手机用 **既有 mTLS 客户端证书** 访问 `https://<api-host-ip>:8443/`。

## 现行组件一览

| 组件 | 作用 |
|------|------|
| `hinddian.service` | FastAPI：仪表盘 + MCP `POST /mcp` + `/api/memory/*` |
| Caddy `:8444` TLS `/hinddian/{mcp,api/memory/*}` | **Agent 通道**：hinddian-memory MCP + hook REST（Bearer `HINDDIAN_MCP_TOKEN`）；hooks 用 `HINDDIAN_MEMORY_URL=https://…:8444/hinddian` |
| Caddy `:8443` mTLS | **仪表盘通道**（图谱 / 批准项目 / Agent 修正）；Caddy 校验客户端证书后注入 `X-Hinddian-Dashboard: $AUTH_TOKEN` |
| Caddy `:80` `/hinddian/*` | 已关闭（410）——会话正文与 token 不再走明文 |
| `magpie-tunnel.service`（可选 infra 名） | 本机 `127.0.0.1:3425` → 远端 System One / chat 网关（Jev） |
| Hindsight `:8888` | bank（`HINDSIGHT_BANK`，默认 `hinddian`）；**仅同步层写入**，不对 Agent 暴露 retain |
| `hinddian-hindsight-sync.timer` | Obsidian active 笔记 → Hindsight 索引对齐 |
| 会话草稿 | hooks → `push_draft` → vault 主机 `/var/lib/hinddian/drafts`（经 MCP/SSH） |
| Agent 修正队列 | vault 主机 `/var/lib/hinddian/agent_corrections`；仪表盘确认/拒绝 |

Vault / batch / pi 在 **vault 主机**；API 主机 通过已有 root SSH（`CLASSIFY_SSH_HOST=vault-host`）调 `hinddian-memory-cli` / `hinddian-classify`。

## 前置

- API 主机 SSH：`api-host`（`<api-host-ip>`）
- mTLS CA 公钥：`/etc/caddy/mtls/ca.pem`（只拷公钥；可来自既有证书基建）
- 手机已装 `<client>` 客户端证书

## 1. 同步代码

```bash
rsync -az --delete \
  --exclude .venv --exclude data --exclude .env --exclude '__pycache__' --exclude .git \
  ./hinddian/ root@api-host:/opt/hinddian/
```

## 2. venv + 依赖

```bash
cd /opt/hinddian
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
mkdir -p /opt/hinddian/data
```

## 3. `.env`（mode 600）

```bash
cat >/opt/hinddian/.env <<'ENV'
INBOX_DIR=/opt/session-distill/inbox
PROCESSED_DIR=/opt/session-distill/processed
QUARANTINE_DIR=/opt/session-distill/quarantine
FAILED_DIR=/opt/session-distill/failed
HINDDIAN_HOST=127.0.0.1
HINDDIAN_PORT=8787
STATUS_DB=/opt/hinddian/data/hinddian.db
HINDSIGHT_BASE_URL=http://127.0.0.1:8888
CLASSIFY_SSH_HOST=vault-host
ENV
chmod 600 /opt/hinddian/.env
# 另从 secrets 注入（勿提交）：
#   HINDSIGHT_API_KEY
#   HINDDIAN_MCP_TOKEN   Agent 通道（hooks / MCP 客户端持有）
#   AUTH_TOKEN           仪表盘通道；必须与 HINDDIAN_MCP_TOKEN 不同，二者缺一即 503
#   生成：python3 -c "import secrets;print(secrets.token_urlsafe(32))"
# 同一个 AUTH_TOKEN 写进 /etc/caddy/hinddian.env：HINDDIAN_DASHBOARD_TOKEN=<AUTH_TOKEN>（600），
#   caddy.service 加 EnvironmentFile=/etc/caddy/hinddian.env（systemctl edit caddy）
# 不要设 VAULT_ROOT（vault 在 vault 主机）
# Jev：JEV_BASE_URL → 本机 :3425（可经 SSH 隧道）；可选 TYPESAFE_API_KEY 云端兜底（写失败仍可不记）
```

完整变量说明见仓库根 `.env.example`。

## 4. systemd

```bash
cp /opt/hinddian/deploy/api-host/hinddian.service /etc/systemd/system/hinddian.service
systemctl daemon-reload
systemctl enable --now hinddian.service
curl -s http://127.0.0.1:8787/api/health
```

若用本机 :3425 闸门，确保隧道服务与 `hinddian-hindsight-sync.timer` 已 enable。

## 5. mTLS CA（仅公钥）

```bash
scp vault-host:/etc/caddy/mtls/ca.pem /tmp/magpie-ca.pem
ssh api-host 'mkdir -p /etc/caddy/mtls /etc/caddy/certs'
scp /tmp/magpie-ca.pem api-host:/etc/caddy/mtls/ca.pem
ssh api-host 'chown root:caddy /etc/caddy/mtls/ca.pem; chmod 640 /etc/caddy/mtls/ca.pem'
rm -f /tmp/magpie-ca.pem
```

**不要**把 CA 私钥、`.p12`、`.pass` 拷到 API 主机 或写进 git。

## 6. 服务器 TLS（自签即可）

```bash
ssh api-host bash -s <<'SH'
set -euo pipefail
mkdir -p /etc/caddy/certs
if [[ ! -f /etc/caddy/certs/privkey.pem ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -keyout /etc/caddy/certs/privkey.pem \
    -out /etc/caddy/certs/fullchain.pem \
    -subj "/CN=<api-host-ip>/O=hinddian/C=CN" \
    -addext "subjectAltName=IP:<api-host-ip>"   # Python/Node 校验的是 SAN，不是 CN
  chown root:caddy /etc/caddy/certs/fullchain.pem /etc/caddy/certs/privkey.pem
  chmod 640 /etc/caddy/certs/fullchain.pem /etc/caddy/certs/privkey.pem
fi
SH
```

旧证书若没有 SAN，需重签一次（删掉 privkey.pem 后重跑）。

客户端信任自签证书：把 `fullchain.pem` 拷到用户机器，
- hooks（Python）：`HINDDIAN_CA_FILE=/path/fullchain.pem`
- Claude Code / Node 宿主的 HTTP MCP：`NODE_EXTRA_CA_CERTS=/path/fullchain.pem`

## 7. Caddyfile

1. 备份现有 Caddyfile
2. 追加 `deploy/api-host/Caddyfile.snippet`（`:8443` 仪表盘 mTLS + 注入仪表盘凭据）与 `deploy/api-host/caddy-hinddian-mcp.snippet`（`:8444` Agent 通道 TLS）
3. 把 `:80` 里旧的 `handle_path /hinddian/*` 换成 snippet 末尾的 410 块
4. `caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy`

## 8. 防火墙 / 安全组

- 本机放行 8443、8444；80 不再承载 hinddian
- 云厂商安全组放行对应 TCP；外网超时而本机 `:8787` 正常时先查 SG

## 9. 冒烟

```bash
curl -s http://127.0.0.1:8787/api/health
curl -s -H "Authorization: Bearer $AUTH_TOKEN" http://127.0.0.1:8787/api/stats | python3 -m json.tool | head
# Agent token 必须进不了仪表盘（期望 403）：
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $HINDDIAN_MCP_TOKEN" http://127.0.0.1:8787/api/corrections
# Jev 经隧道：
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3425/v1/models
# 同步 timer：
systemctl status hinddian-hindsight-sync.timer --no-pager
```

外网仪表盘（测完删除临时证书）：

```bash
scp vault-host:<ca-dir>/<client>.pem /tmp/client.pem
scp vault-host:<ca-dir>/<client>.key /tmp/client.key
chmod 600 /tmp/client.pem /tmp/client.key
curl -sk --cert /tmp/client.pem --key /tmp/client.key \
  https://<api-host-ip>:8443/api/health
rm -f /tmp/client.pem /tmp/client.key
```

手机：`https://<api-host-ip>:8443/`，选用已导入的 mTLS 客户端证书。

## 10. vault 主机 归类 / 修正

API 主机 `.env`：`CLASSIFY_SSH_HOST=vault-host`。  
hinddian 经 SSH（ControlMaster 复用连接，`SSH_CONTROL_PATH`）调 `hinddian-classify` / `hinddian-memory-cli`（含 `search_notes` / `suggest_correction` / `decide_correction`）。
vault 主机 上同步更新 `/opt/hinddian/src`（`note_format.py` 被 `hinddian-memory-cli` 与 `hinddian_batch.py` 共用）。

> 更省事的形态：hinddian API 直接跑在 vault 主机（设 `VAULT_ROOT`），vault 操作走本地，不再经 SSH。  
vault 主机 安装见 `classify/README.md`。

## 回滚

```bash
systemctl stop hinddian
# 恢复 Caddyfile 备份后 reload
```
