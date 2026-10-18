# hinddian · 华为部署

目标：仪表盘与 hinddian-memory API 在华为（与 `/opt/session-distill` 同机）；手机用 **与 Magpie 同一套客户端证书** 访问 `https://124.70.90.224:8443/`。

## 现行组件一览

| 组件 | 作用 |
|------|------|
| `hinddian.service` | FastAPI：仪表盘 + MCP `POST /mcp` + `/api/memory/*` |
| Caddy `:80` `/hinddian/*` | 公网 hinddian-memory（Bearer）；hooks 用 `HINDDIAN_MEMORY_URL` |
| Caddy `:8443` mTLS | 仪表盘（图谱 / 批准项目 / Agent 修正） |
| `magpie-tunnel.service` | 本机 `127.0.0.1:3425` → DMIT Magpie（Jev + LLM） |
| Hindsight `:8888` | bank `wanwan`；**仅同步层写入**，不对 Agent 暴露 retain |
| `hinddian-hindsight-sync.timer` | Obsidian active 笔记 → Hindsight 索引对齐 |
| 会话草稿 | hooks → `push_draft` → DMIT `/var/lib/hinddian/drafts`（经 MCP/SSH） |
| Agent 修正队列 | DMIT `/var/lib/hinddian/agent_corrections`；仪表盘确认/拒绝 |

Vault / batch / pi 在 **DMIT**；华为通过已有 root SSH（`CLASSIFY_SSH_HOST=dmit-vps`）调 `hinddian-memory-cli` / `hinddian-classify`。

## 前置

- 华为 SSH：`huawei-vps`（`124.70.90.224`）
- DMIT Magpie mTLS CA 公钥：`/etc/caddy/mtls/ca.pem`（只拷公钥）
- 手机已装 `wanwan-iphone` 客户端证书（Magpie 同款）

## 1. 同步代码

```bash
rsync -az --delete \
  --exclude .venv --exclude data --exclude .env --exclude '__pycache__' --exclude .git \
  ./hinddian/ root@huawei-vps:/opt/hinddian/
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
USE_DEMO_DATA=false
HINDSIGHT_BASE_URL=http://127.0.0.1:8888
HINDDIAN_MEMORY_URL=http://124.70.90.224/hinddian
CLASSIFY_SSH_HOST=dmit-vps
ENV
chmod 600 /opt/hinddian/.env
# 另从 secrets 注入 HINDSIGHT_API_KEY / HINDDIAN_MCP_TOKEN（勿提交）
# 不要设 VAULT_ROOT（vault 在 DMIT）；AUTH_TOKEN 留空（mTLS 守门）
# Jev：经 magpie-tunnel 本机 :3425；可选 TYPESAFE_API_KEY 云端兜底（写失败仍可不记）
```

完整变量说明见仓库根 `.env.example`。

## 4. systemd

```bash
cp /opt/hinddian/deploy/huawei/hinddian.service /etc/systemd/system/hinddian.service
systemctl daemon-reload
systemctl enable --now hinddian.service
curl -s http://127.0.0.1:8787/api/health
```

确保 `magpie-tunnel.service` 与 `hinddian-hindsight-sync.timer` 已 enable。

## 5. mTLS CA（仅公钥）

```bash
scp dmit-vps:/etc/caddy/mtls/ca.pem /tmp/magpie-ca.pem
ssh huawei-vps 'mkdir -p /etc/caddy/mtls /etc/caddy/certs'
scp /tmp/magpie-ca.pem huawei-vps:/etc/caddy/mtls/ca.pem
ssh huawei-vps 'chown root:caddy /etc/caddy/mtls/ca.pem; chmod 640 /etc/caddy/mtls/ca.pem'
rm -f /tmp/magpie-ca.pem
```

**不要**把 CA 私钥、`.p12`、`.pass` 拷到华为或写进 git。

## 6. 服务器 TLS（自签即可）

```bash
ssh huawei-vps bash -s <<'SH'
set -euo pipefail
mkdir -p /etc/caddy/certs
if [[ ! -f /etc/caddy/certs/privkey.pem ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -keyout /etc/caddy/certs/privkey.pem \
    -out /etc/caddy/certs/fullchain.pem \
    -subj "/CN=124.70.90.224/O=hinddian/C=CN"
  chown root:caddy /etc/caddy/certs/fullchain.pem /etc/caddy/certs/privkey.pem
  chmod 640 /etc/caddy/certs/fullchain.pem /etc/caddy/certs/privkey.pem
fi
SH
```

## 7. Caddyfile

1. 备份现有 Caddyfile
2. 追加 `deploy/huawei/Caddyfile.snippet`：`:8443`（仪表盘 mTLS）与 `:80` `/hinddian/*`（MCP 公网）
3. `caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy`

## 8. 防火墙 / 安全组

- 本机放行 8443（及若需公网 MCP 的 80）
- 华为云安全组放行对应 TCP；外网超时而本机 `:8787` 正常时先查 SG

## 9. 冒烟

```bash
curl -s http://127.0.0.1:8787/api/health
curl -s http://127.0.0.1:8787/api/stats | python3 -m json.tool | head
# Jev 经隧道：
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3425/v1/models
# 同步 timer：
systemctl status hinddian-hindsight-sync.timer --no-pager
```

外网仪表盘（测完删除临时证书）：

```bash
scp dmit-vps:/root/magpie-mtls/wanwan-iphone.pem /tmp/iphone.pem
scp dmit-vps:/root/magpie-mtls/wanwan-iphone.key /tmp/iphone.key
chmod 600 /tmp/iphone.pem /tmp/iphone.key
curl -sk --cert /tmp/iphone.pem --key /tmp/iphone.key \
  https://124.70.90.224:8443/api/health
rm -f /tmp/iphone.pem /tmp/iphone.key
```

手机：`https://124.70.90.224:8443/`，选用 Magpie 客户端证书。

## 10. DMIT 归类 / 修正

华为 `.env`：`CLASSIFY_SSH_HOST=dmit-vps`。  
hinddian 经 SSH 调 `hinddian-classify` / `hinddian-memory-cli`（含 `suggest_correction` / `decide_correction`）。  
DMIT 安装见 `classify/README.md`。

## 回滚

```bash
systemctl stop hinddian
# 恢复 Caddyfile 备份后 reload
```
