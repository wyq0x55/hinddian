# hinddian · 华为部署

目标：仪表盘挂在华为（与 `/opt/session-distill` 同机），手机用 **与 Magpie 同一套客户端证书** 访问 `https://124.70.90.224:8443/`。

## 前置

- 华为 SSH：`huawei-vps`（`124.70.90.224`）
- DMIT 上 Magpie mTLS CA 公钥：`/etc/caddy/mtls/ca.pem`（只拷公钥，不拷 CA 私钥 / p12）
- 手机已装 `wanwan-iphone` 客户端证书（Magpie 同款）

## 1. 同步代码

```bash
# 从开发机 rsync（排除 venv / data / secrets）
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
ENV
chmod 600 /opt/hinddian/.env
# 不要设 VAULT_ROOT（vault 在 DMIT）；不要写 API key；AUTH_TOKEN 留空（mTLS 守门）
```

## 4. systemd

```bash
cp /opt/hinddian/deploy/huawei/hinddian.service /etc/systemd/system/hinddian.service
systemctl daemon-reload
systemctl enable --now hinddian.service
curl -s http://127.0.0.1:8787/api/health
curl -s http://127.0.0.1:8787/api/stats   # 期望 inbox_count ≈ 真实收件箱数量
```

## 5. mTLS CA（仅公钥）

从 DMIT 拷贝 Magpie CA **公钥**：

```bash
# 在运维机
scp dmit-vps:/etc/caddy/mtls/ca.pem /tmp/magpie-ca.pem
ssh huawei-vps 'mkdir -p /etc/caddy/mtls /etc/caddy/certs'
scp /tmp/magpie-ca.pem huawei-vps:/etc/caddy/mtls/ca.pem
ssh huawei-vps 'chown root:caddy /etc/caddy/mtls/ca.pem; chmod 640 /etc/caddy/mtls/ca.pem; rm -f /tmp/magpie-ca.pem'
rm -f /tmp/magpie-ca.pem
```

**不要**把 `/root/magpie-mtls/ca.key`、`.p12`、`.pass` 拷到华为或写进 git。

## 6. 华为服务器 TLS（自签即可）

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

1. 备份：`cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.$(date +%Y%m%d%H%M%S)`
2. 若文件顶部还没有 global block，加上与 DMIT 相同的 `strict_sni_host insecure_off`（IP 访问无 SNI）。
3. 追加 `deploy/huawei/Caddyfile.snippet` 里的 `:8443` 段。
4. `caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy`

## 8. 防火墙 / 安全组

- 本机：`ufw allow 8443/tcp`（若启用 ufw）或放行 iptables。
- **华为云安全组** 需放行 TCP 8443 入站；若外网 curl 超时而本机 `127.0.0.1:8787` 正常，多半是 SG。

## 9. 冒烟

本机（无 mTLS）：

```bash
curl -s http://127.0.0.1:8787/api/stats | python3 -m json.tool | head
```

外网（临时客户端证书，测完删除，勿提交）：

```bash
# 仅公钥+客户端钥用于 curl；测完 rm
scp dmit-vps:/root/magpie-mtls/wanwan-iphone.pem /tmp/iphone.pem
scp dmit-vps:/root/magpie-mtls/wanwan-iphone.key /tmp/iphone.key
chmod 600 /tmp/iphone.pem /tmp/iphone.key
curl -sk --cert /tmp/iphone.pem --key /tmp/iphone.key \
  https://124.70.90.224:8443/api/health
rm -f /tmp/iphone.pem /tmp/iphone.key
```

手机：Safari/快捷方式打开 `https://124.70.90.224:8443/`，选用已装的 Magpie 客户端证书。首次会提示信任自签服务器证书。

## 回滚

```bash
systemctl stop hinddian
# 恢复 Caddyfile 备份后 reload
```
