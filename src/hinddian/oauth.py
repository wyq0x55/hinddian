"""MCP OAuth for the agent channel (MCP authorization spec, 2025-06-18).

hinddian is its own authorization server; GitHub (OAuth App) is only the upstream identity:

  client ──401 + WWW-Authenticate(resource_metadata)──▶ /.well-known/oauth-protected-resource
         ──▶ /.well-known/oauth-authorization-server ──▶ POST /oauth/register   (RFC 7591, public client)
         ──▶ GET /oauth/authorize (PKCE S256) ──302──▶ github.com/login/oauth/authorize
  github ──▶ GET /oauth/github/callback  (login must be in HINDDIAN_GH_ALLOWED_USERS)
         ──302──▶ client redirect_uri?code=…&state=…
  client ──▶ POST /oauth/token (authorization_code + code_verifier | refresh_token, rotated)

Tokens are opaque random strings; only SHA-256 hashes are stored (SQLite). The static
HINDDIAN_MCP_TOKEN keeps working in parallel (see memory_mcp.require_agent).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .config import Settings, get_settings

router = APIRouter()

GH_AUTHORIZE = "https://github.com/login/oauth/authorize"
GH_TOKEN = "https://github.com/login/oauth/access_token"
GH_USER = "https://api.github.com/user"
SCOPE = "hinddian:memory"
PENDING_TTL = 600
CODE_TTL = 300

_lock = threading.Lock()
_conns: dict[str, sqlite3.Connection] = {}


# ------------------------------------------------------------------ storage
def _db() -> sqlite3.Connection:
    path = get_settings().hinddian_oauth_db
    key = str(path)
    with _lock:
        c = _conns.get(key)
        if c is None:
            if key != ":memory:":
                path.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(key, check_same_thread=False, isolation_level=None)
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS clients(id TEXT PRIMARY KEY, meta TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS pending(state TEXT PRIMARY KEY, data TEXT, exp REAL);
                CREATE TABLE IF NOT EXISTS codes(h TEXT PRIMARY KEY, data TEXT, exp REAL);
                CREATE TABLE IF NOT EXISTS tokens(h TEXT PRIMARY KEY, kind TEXT, client TEXT,
                                                  login TEXT, resource TEXT, exp REAL);
                """
            )
            if key != ":memory:":
                try:
                    path.chmod(0o600)
                except OSError:
                    pass
            _conns[key] = c
        return c


def reset_db_cache() -> None:
    with _lock:
        for c in _conns.values():
            c.close()
        _conns.clear()


def _h(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def _gc(c: sqlite3.Connection) -> None:
    now = time.time()
    for t in ("pending", "codes", "tokens"):
        c.execute(f"DELETE FROM {t} WHERE exp < ?", (now,))


# ------------------------------------------------------------------ helpers
def _s() -> Settings:
    s = get_settings()
    if not s.oauth_enabled:
        raise HTTPException(404, "oauth not configured")
    return s


def base_url(s: Settings | None = None) -> str:
    s = s or get_settings()
    return (s.hinddian_public_url or "").rstrip("/")


def resource_url(s: Settings | None = None) -> str:
    return base_url(s) + "/mcp"


def resource_metadata_url(s: Settings | None = None) -> str:
    return base_url(s) + "/.well-known/oauth-protected-resource"


def www_authenticate(error: str | None = None) -> str:
    v = f'Bearer resource_metadata="{resource_metadata_url()}"'
    if error:
        v += f', error="{error}"'
    return v


def _oauth_error(error: str, desc: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": desc}, status_code=status,
                        headers={"Cache-Control": "no-store"})


def _redirect_ok(uri: str) -> bool:
    u = urlparse(uri)
    if u.fragment:
        return False
    if u.scheme == "https":
        return bool(u.netloc)
    if u.scheme == "http":  # loopback only (RFC 8252 §7.3)
        return u.hostname in ("127.0.0.1", "localhost", "::1")
    # private-use URI schemes for native apps (e.g. cursor://), never javascript:/data:
    return u.scheme not in ("javascript", "data", "file", "vbscript", "") and (
        "." in u.scheme or u.scheme in ("cursor", "vscode", "claude")
    )


def _redirect_matches(registered: list[str], got: str) -> bool:
    if got in registered:
        return True
    # RFC 8252 §7.3: loopback redirect may use any port.
    g = urlparse(got)
    if g.scheme == "http" and g.hostname in ("127.0.0.1", "localhost", "::1"):
        for r in registered:
            ru = urlparse(r)
            if ru.scheme == "http" and ru.hostname == g.hostname and ru.path == g.path:
                return True
    return False


def _with_query(uri: str, params: dict[str, str]) -> str:
    return uri + ("&" if "?" in uri else "?") + urlencode(params)


def _pkce_ok(verifier: str, challenge: str) -> bool:
    if not (43 <= len(verifier) <= 128):
        return False
    d = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return secrets.compare_digest(d, challenge)


async def _form(request: Request) -> dict[str, str]:
    """application/x-www-form-urlencoded without the python-multipart dependency."""
    return dict(parse_qsl((await request.body()).decode("utf-8", "replace"), keep_blank_values=True))


def _gh_client(s: Settings) -> httpx.Client:
    return httpx.Client(timeout=20, proxy=s.hinddian_gh_proxy or None,
                        headers={"Accept": "application/json", "User-Agent": "hinddian"})


def _resource_ok(s: Settings, resource: str | None) -> bool:
    if not resource:
        return True
    r = resource.rstrip("/")
    return r in (resource_url(s), base_url(s))


# ------------------------------------------------------------------ token check (used by require_agent)
def verify_access_token(token: str) -> dict | None:
    s = get_settings()
    if not s.oauth_enabled or not token:
        return None
    row = _db().execute(
        "SELECT client, login, exp FROM tokens WHERE h=? AND kind='access'", (_h(token),)
    ).fetchone()
    if not row or row[2] < time.time():
        return None
    if row[1].lower() not in s.allowed_gh_users:  # allow-list shrank → revoke
        return None
    return {"client_id": row[0], "login": row[1]}


# ------------------------------------------------------------------ metadata
def _as_metadata(s: Settings) -> dict:
    b = base_url(s)
    return {
        "issuer": b,
        "authorization_endpoint": b + "/oauth/authorize",
        "token_endpoint": b + "/oauth/token",
        "registration_endpoint": b + "/oauth/register",
        "revocation_endpoint": b + "/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [SCOPE],
    }


def _pr_metadata(s: Settings) -> dict:
    return {
        "resource": resource_url(s),
        "authorization_servers": [base_url(s)],
        "scopes_supported": [SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "hinddian-memory",
    }


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/{rest:path}")
def protected_resource_metadata(rest: str = ""):
    return _pr_metadata(_s())


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/oauth-authorization-server/{rest:path}")
@router.get("/.well-known/openid-configuration")
def authorization_server_metadata(rest: str = ""):
    return _as_metadata(_s())


# ------------------------------------------------------------------ dynamic client registration
@router.post("/oauth/register")
async def register(request: Request):
    _s()
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _oauth_error("invalid_client_metadata", "json body required")
    uris = body.get("redirect_uris") if isinstance(body, dict) else None
    if not isinstance(uris, list) or not uris or not all(isinstance(u, str) and _redirect_ok(u) for u in uris):
        return _oauth_error("invalid_redirect_uri", "redirect_uris must be https, loopback http, or a native app scheme")
    if len(uris) > 10 or any(len(u) > 2000 for u in uris):
        return _oauth_error("invalid_redirect_uri", "too many / too long redirect_uris")
    cid = "hd_" + secrets.token_urlsafe(18)
    meta = {
        "client_id": cid,
        "client_id_issued_at": int(time.time()),
        "redirect_uris": uris,
        "client_name": str(body.get("client_name") or "")[:200],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": SCOPE,
    }
    c = _db()
    _gc(c)
    if c.execute("SELECT COUNT(*) FROM clients").fetchone()[0] > 500:
        return _oauth_error("invalid_client_metadata", "registration limit reached", 429)
    c.execute("INSERT INTO clients VALUES(?,?,?)", (cid, json.dumps(meta), time.time()))
    return JSONResponse(meta, status_code=201, headers={"Cache-Control": "no-store"})


def _client(cid: str | None) -> dict | None:
    if not cid:
        return None
    row = _db().execute("SELECT meta FROM clients WHERE id=?", (cid,)).fetchone()
    return json.loads(row[0]) if row else None


# ------------------------------------------------------------------ authorize → GitHub
@router.get("/oauth/authorize")
def authorize(request: Request):
    s = _s()
    q = request.query_params
    client = _client(q.get("client_id"))
    redirect_uri = q.get("redirect_uri") or ""
    if not client:
        return HTMLResponse("unknown client_id", status_code=400)
    if not _redirect_matches(client["redirect_uris"], redirect_uri):
        return HTMLResponse("redirect_uri not registered for this client", status_code=400)
    state = q.get("state") or ""

    def back(err: str, desc: str):
        p = {"error": err, "error_description": desc}
        if state:
            p["state"] = state
        return RedirectResponse(_with_query(redirect_uri, p), status_code=302)

    if q.get("response_type") != "code":
        return back("unsupported_response_type", "only code")
    challenge = q.get("code_challenge") or ""
    if not challenge or q.get("code_challenge_method") != "S256":
        return back("invalid_request", "PKCE S256 required")
    if not _resource_ok(s, q.get("resource")):
        return back("invalid_target", "unknown resource")
    gh_state = secrets.token_urlsafe(24)
    c = _db()
    _gc(c)
    c.execute(
        "INSERT INTO pending VALUES(?,?,?)",
        (gh_state, json.dumps({
            "client_id": client["client_id"], "redirect_uri": redirect_uri, "state": state,
            "challenge": challenge, "resource": q.get("resource") or resource_url(s),
        }), time.time() + PENDING_TTL),
    )
    gh = GH_AUTHORIZE + "?" + urlencode({
        "client_id": s.hinddian_gh_client_id,
        "redirect_uri": base_url(s) + "/oauth/github/callback",
        "scope": "read:user",
        "state": gh_state,
        "allow_signup": "false",
    })
    return RedirectResponse(gh, status_code=302)


def _github_login(s: Settings, code: str) -> str:
    with _gh_client(s) as h:
        r = h.post(GH_TOKEN, data={
            "client_id": s.hinddian_gh_client_id,
            "client_secret": s.hinddian_gh_client_secret,
            "code": code,
            "redirect_uri": base_url(s) + "/oauth/github/callback",
        })
        r.raise_for_status()
        tok = r.json().get("access_token")
        if not tok:
            raise ValueError("github did not return a token")
        u = h.get(GH_USER, headers={"Authorization": f"Bearer {tok}"})
        u.raise_for_status()
        return str(u.json().get("login") or "")


@router.get("/oauth/github/callback")
def github_callback(request: Request):
    s = _s()
    q = request.query_params
    c = _db()
    row = c.execute("SELECT data, exp FROM pending WHERE state=?", (q.get("state") or "",)).fetchone()
    if not row or row[1] < time.time():
        return HTMLResponse("login expired or invalid state — start again from your MCP client", status_code=400)
    c.execute("DELETE FROM pending WHERE state=?", (q.get("state"),))
    p = json.loads(row[0])

    def back(params: dict[str, str]):
        if p["state"]:
            params["state"] = p["state"]
        return RedirectResponse(_with_query(p["redirect_uri"], params), status_code=302)

    if q.get("error") or not q.get("code"):
        return back({"error": "access_denied", "error_description": q.get("error") or "no code"})
    try:
        login = _github_login(s, q["code"])
    except Exception:  # noqa: BLE001 — don't leak upstream details
        return back({"error": "server_error", "error_description": "github login failed"})
    if login.lower() not in s.allowed_gh_users:
        return back({"error": "access_denied", "error_description": "github user not allowed"})
    code = secrets.token_urlsafe(32)
    c.execute("INSERT INTO codes VALUES(?,?,?)",
              (_h(code), json.dumps({**p, "login": login}), time.time() + CODE_TTL))
    return back({"code": code})


# ------------------------------------------------------------------ token
def _issue(c: sqlite3.Connection, s: Settings, client_id: str, login: str, resource: str) -> dict:
    access = secrets.token_urlsafe(32)
    refresh = secrets.token_urlsafe(32)
    now = time.time()
    c.execute("INSERT INTO tokens VALUES(?,?,?,?,?,?)",
              (_h(access), "access", client_id, login, resource, now + s.hinddian_oauth_access_ttl))
    c.execute("INSERT INTO tokens VALUES(?,?,?,?,?,?)",
              (_h(refresh), "refresh", client_id, login, resource, now + s.hinddian_oauth_refresh_ttl))
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": s.hinddian_oauth_access_ttl,
        "refresh_token": refresh,
        "scope": SCOPE,
    }


@router.post("/oauth/token")
async def token(request: Request):
    s = _s()
    f = await _form(request)
    grant = f.get("grant_type")
    c = _db()
    _gc(c)
    if grant == "authorization_code":
        code = str(f.get("code") or "")
        row = c.execute("SELECT data, exp FROM codes WHERE h=?", (_h(code),)).fetchone()
        c.execute("DELETE FROM codes WHERE h=?", (_h(code),))  # single use
        if not row or row[1] < time.time():
            return _oauth_error("invalid_grant", "code invalid or expired")
        d = json.loads(row[0])
        if f.get("client_id") != d["client_id"]:
            return _oauth_error("invalid_grant", "client mismatch")
        if f.get("redirect_uri") and f.get("redirect_uri") != d["redirect_uri"]:
            return _oauth_error("invalid_grant", "redirect_uri mismatch")
        if not _pkce_ok(str(f.get("code_verifier") or ""), d["challenge"]):
            return _oauth_error("invalid_grant", "PKCE verification failed")
        out = _issue(c, s, d["client_id"], d["login"], d["resource"])
        return JSONResponse(out, headers={"Cache-Control": "no-store"})
    if grant == "refresh_token":
        rt = str(f.get("refresh_token") or "")
        row = c.execute("SELECT client, login, resource, exp FROM tokens WHERE h=? AND kind='refresh'",
                        (_h(rt),)).fetchone()
        if not row or row[3] < time.time():
            return _oauth_error("invalid_grant", "refresh token invalid or expired")
        if f.get("client_id") and f.get("client_id") != row[0]:
            return _oauth_error("invalid_grant", "client mismatch")
        if row[1].lower() not in s.allowed_gh_users:
            return _oauth_error("invalid_grant", "user no longer allowed")
        c.execute("DELETE FROM tokens WHERE h=?", (_h(rt),))  # rotate
        return JSONResponse(_issue(c, s, row[0], row[1], row[2]), headers={"Cache-Control": "no-store"})
    return _oauth_error("unsupported_grant_type", "authorization_code or refresh_token")


@router.post("/oauth/revoke")
async def revoke(request: Request):
    _s()
    f = await _form(request)
    t = str(f.get("token") or "")
    if t:
        _db().execute("DELETE FROM tokens WHERE h=?", (_h(t),))
    return JSONResponse({})
