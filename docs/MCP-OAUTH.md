# hinddian MCP OAuth（浏览器登录，替代手填 HINDDIAN_MCP_TOKEN）

实现 MCP 授权规范（2025-06-18）：hinddian 自己当授权服务器，GitHub OAuth App 只负责确认身份（只放行 `HINDDIAN_GH_ALLOWED_USERS`）。
静态 `HINDDIAN_MCP_TOKEN` 继续可用（hooks、过渡期客户端）。

| 端点（相对 `HINDDIAN_PUBLIC_URL`，如 `https://<host>:8444/hinddian`） | 作用 |
|---|---|
| `/.well-known/oauth-protected-resource` | RFC 9728 资源元数据；`/mcp` 的 401 在 `WWW-Authenticate` 里指向它 |
| `/.well-known/oauth-authorization-server` | RFC 8414 元数据（根路径 `/.well-known/…/hinddian` 也可，由 Caddy 转发） |
| `POST /oauth/register` | RFC 7591 动态注册（公共客户端，无 secret） |
| `GET /oauth/authorize` | 必须 PKCE S256 → 跳 GitHub |
| `GET /oauth/github/callback` | GitHub 回调（**要登记到 GitHub OAuth App**） |
| `POST /oauth/token` | `authorization_code`（校验 code_verifier）/ `refresh_token`（轮换） |
| `POST /oauth/revoke` | 吊销 |

令牌：随机串，库里只存 SHA-256（`HINDDIAN_OAUTH_DB`，默认 `data/oauth.sqlite3`，600）。access 1h，refresh 30 天。
OAuth 令牌只对 Agent 通道有效，不能当仪表盘的 AUTH_TOKEN。

## 服务端 `.env`

```
HINDDIAN_PUBLIC_URL=https://<host>:8444/hinddian
HINDDIAN_GH_CLIENT_ID=...
HINDDIAN_GH_CLIENT_SECRET=...
HINDDIAN_GH_ALLOWED_USERS=wyq0x55
HINDDIAN_GH_PROXY=socks5://127.0.0.1:1088   # 国内主机连 github.com 需走代理
```

GitHub OAuth App 的 callback 必须是 `{HINDDIAN_PUBLIC_URL}/oauth/github/callback`。
GitHub OAuth App 只有一个 callback URL，且 redirect_uri 必须同 host+端口；仪表盘 oauth2-proxy 用的是 :8443，
所以 MCP 需要**单独一个 OAuth App**（或把唯一 callback 改成 :8444 那个，仪表盘登录就会坏）。

Caddy：见 `deploy/api-host/caddy-hinddian-mcp.snippet`（新增 `/hinddian/oauth/*`、`/hinddian/.well-known/*` 和根 `/.well-known/oauth-*`）。

## 客户端

- Claude Code：`claude mcp add --transport http hinddian-memory https://<host>:8444/hinddian/mcp`（不带 header），然后 `/mcp` → Authenticate。
- Codex：`~/.codex/config.toml` 里 `[mcp_servers.hinddian-memory] url = "https://<host>:8444/hinddian/mcp"`，然后 `codex mcp login hinddian-memory`。
- 自签证书：Node 客户端需 `NODE_EXTRA_CA_CERTS=<cert.pem>`；Rust/其他客户端需把证书加入系统信任库。用公网可信证书（如 Let's Encrypt IP 证书）可免去这一步。
