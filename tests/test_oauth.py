from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from hinddian.config import get_settings

MCP = "mcp-static-token"
BASE = "https://hd.example:8444/hinddian"
REDIR = "http://127.0.0.1:33418/callback"
VERIFIER = "v" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


@pytest.fixture
def c(vault, monkeypatch, tmp_path):
    from hinddian import oauth

    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("HINDDIAN_MCP_TOKEN", MCP)
    monkeypatch.setenv("AUTH_TOKEN", "dash-token")
    monkeypatch.setenv("HINDSIGHT_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("HINDDIAN_PUBLIC_URL", BASE)
    monkeypatch.setenv("HINDDIAN_GH_CLIENT_ID", "gh-cid")
    monkeypatch.setenv("HINDDIAN_GH_CLIENT_SECRET", "gh-secret")
    monkeypatch.setenv("HINDDIAN_GH_ALLOWED_USERS", "wyq0x55")
    monkeypatch.setenv("HINDDIAN_OAUTH_DB", str(tmp_path / "oauth.sqlite3"))
    get_settings.cache_clear()
    oauth.reset_db_cache()
    login = {"v": "wyq0x55"}
    monkeypatch.setattr(oauth, "_github_login", lambda s, code: login["v"])
    from hinddian.api import app

    with TestClient(app) as cl:
        cl.login = login
        yield cl
    oauth.reset_db_cache()
    get_settings.cache_clear()


def _rpc(c, tok):
    return c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                  headers={"Authorization": f"Bearer {tok}"} if tok else {})


def _register(c, uris=(REDIR,)):
    r = c.post("/oauth/register", json={"redirect_uris": list(uris), "client_name": "test"})
    assert r.status_code == 201, r.text
    return r.json()["client_id"]


def _flow(c, cid, redirect=REDIR):
    r = c.get("/oauth/authorize", params={
        "response_type": "code", "client_id": cid, "redirect_uri": redirect, "state": "xyz",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256", "resource": BASE + "/mcp",
    }, follow_redirects=False)
    assert r.status_code == 302
    gh = urlparse(r.headers["location"])
    gq = parse_qs(gh.query)
    assert gh.netloc == "github.com" and gq["client_id"] == ["gh-cid"]
    assert gq["redirect_uri"] == [BASE + "/oauth/github/callback"]
    r = c.get("/oauth/github/callback", params={"code": "ghcode", "state": gq["state"][0]},
              follow_redirects=False)
    assert r.status_code == 302
    back = urlparse(r.headers["location"])
    return parse_qs(back.query)


def _token(c, cid, code, verifier=VERIFIER):
    return c.post("/oauth/token", data={"grant_type": "authorization_code", "code": code,
                                        "client_id": cid, "redirect_uri": REDIR, "code_verifier": verifier})


def test_metadata_and_challenge(c):
    pr = c.get("/.well-known/oauth-protected-resource").json()
    assert pr["resource"] == BASE + "/mcp" and pr["authorization_servers"] == [BASE]
    assert c.get("/.well-known/oauth-protected-resource/hinddian/mcp").status_code == 200
    md = c.get("/.well-known/oauth-authorization-server").json()
    assert md["issuer"] == BASE and md["code_challenge_methods_supported"] == ["S256"]
    assert md["registration_endpoint"] == BASE + "/oauth/register"
    r = _rpc(c, None)
    assert r.status_code == 401
    assert f'resource_metadata="{BASE}/.well-known/oauth-protected-resource"' in r.headers["www-authenticate"]


def test_full_flow_refresh_and_static_token(c):
    assert _rpc(c, MCP).status_code == 200  # transition: static token still works
    cid = _register(c)
    q = _flow(c, cid, "http://127.0.0.1:50000/callback")  # loopback: any port
    assert q["state"] == ["xyz"]
    t = c.post("/oauth/token", data={"grant_type": "authorization_code", "code": q["code"][0],
                                     "client_id": cid, "code_verifier": VERIFIER}).json()
    assert _rpc(c, t["access_token"]).status_code == 200
    assert c.get("/api/memory/routing/global",
                 headers={"Authorization": f"Bearer {t['access_token']}"}).status_code == 200
    # code is single-use
    again = c.post("/oauth/token", data={"grant_type": "authorization_code", "code": q["code"][0],
                                         "client_id": cid, "code_verifier": VERIFIER})
    assert again.status_code == 400
    r2 = c.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": t["refresh_token"],
                                      "client_id": cid}).json()
    assert _rpc(c, r2["access_token"]).status_code == 200
    # rotated: old refresh token is dead
    old = c.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
    assert old.json()["error"] == "invalid_grant"
    # oauth token is not a dashboard credential
    assert c.get("/api/overview", headers={"Authorization": f"Bearer {r2['access_token']}"}).status_code == 403


def test_bad_pkce_rejected(c):
    cid = _register(c)
    q = _flow(c, cid)
    assert _token(c, cid, q["code"][0], verifier="w" * 64).json()["error"] == "invalid_grant"


def test_other_github_user_denied(c):
    c.login["v"] = "someone-else"
    cid = _register(c)
    q = _flow(c, cid)
    assert q["error"] == ["access_denied"] and "code" not in q


def test_unregistered_redirect_and_no_pkce(c):
    cid = _register(c)
    r = c.get("/oauth/authorize", params={"response_type": "code", "client_id": cid,
                                          "redirect_uri": "https://evil.example/cb",
                                          "code_challenge": CHALLENGE, "code_challenge_method": "S256"},
              follow_redirects=False)
    assert r.status_code == 400
    r = c.get("/oauth/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": REDIR},
              follow_redirects=False)
    assert "error=invalid_request" in r.headers["location"]
    assert c.post("/oauth/register", json={"redirect_uris": ["javascript:alert(1)"]}).status_code == 400


def test_invalid_bearer_is_401_when_oauth_on(c):
    r = _rpc(c, "garbage")
    assert r.status_code == 401 and 'error="invalid_token"' in r.headers["www-authenticate"]


def test_oauth_off_by_default(vault, monkeypatch):
    for k in ("HINDDIAN_PUBLIC_URL", "HINDDIAN_GH_CLIENT_ID", "HINDDIAN_GH_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HINDDIAN_MCP_TOKEN", MCP)
    get_settings.cache_clear()
    from hinddian.api import app

    with TestClient(app) as cl:
        assert cl.get("/.well-known/oauth-authorization-server").status_code == 404
        assert _rpc(cl, "garbage").status_code == 403
    get_settings.cache_clear()
