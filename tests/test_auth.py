import json
import re
import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from joserfc import jwt
from joserfc.jwk import ECKey

from papiamentu import create_app
from papiamentu.auth import _valid_microsoft_issuer
from papiamentu.sync import merge, resolve, sanitize

APPLE_KEY = ec.generate_private_key(ec.SECP256R1())
APPLE_PEM = APPLE_KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()

ALL_KEYS = {
    "GOOGLE_CLIENT_ID": "g-id", "GOOGLE_CLIENT_SECRET": "g-secret",
    "MICROSOFT_CLIENT_ID": "m-id", "MICROSOFT_CLIENT_SECRET": "m-secret",
    "APPLE_CLIENT_ID": "com.example.web", "APPLE_TEAM_ID": "TEAM123", "APPLE_KEY_ID": "KEY123",
    "APPLE_PRIVATE_KEY": APPLE_PEM.replace("\n", "\\n"),
    "FACEBOOK_CLIENT_ID": "f-id", "FACEBOOK_CLIENT_SECRET": "f-secret",
}

META = {
    "issuer": "https://issuer.example",
    "authorization_endpoint": "https://issuer.example/authorize",
    "token_endpoint": "https://issuer.example/token",
    "jwks_uri": "https://issuer.example/jwks",
}


@pytest.fixture
def app(tmp_path, monkeypatch):
    for k, v in ALL_KEYS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return create_app({"TESTING": True, "SECRET_KEY": "test"})


@pytest.fixture
def client(app):
    return app.test_client()


def oauth_client(app, provider):
    with app.app_context():
        return app.extensions["authlib.integrations.flask_client"].create_client(provider)


def fake_token(app, monkeypatch, provider, userinfo=None, me=None):
    c = oauth_client(app, provider)
    monkeypatch.setattr(c, "authorize_access_token", lambda **kw: {"access_token": "at", "userinfo": userinfo})
    if me is not None:
        class Resp:
            def json(self): return me
        monkeypatch.setattr(c, "get", lambda *a, **kw: Resp())
    return c


def login_as(client, app, monkeypatch, provider="google", sub="123", name="Ana", email="ana@example.com",
             verified=True):
    fake_token(app, monkeypatch, provider, {"sub": sub, "given_name": name, "email": email, "email_verified": verified})
    return client.get(f"/auth/{provider}/callback?code=x&state=y")


def csrf_of(client):
    html = client.get("/instellingen").get_data(as_text=True)
    return re.search(r'name="papiamentu-user"[^>]*data-csrf="([^"]+)"', html).group(1)


def users(app):
    with sqlite3.connect(app.config["DATABASE"]) as db:
        return db.execute("SELECT id, name, email FROM users").fetchall()


# ---------- which providers show up ----------

def test_no_providers_means_no_login_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for k in ALL_KEYS:
        monkeypatch.delenv(k, raising=False)
    c = create_app({"TESTING": True}).test_client()
    assert "Doorgaan met" not in c.get("/").get_data(as_text=True)
    assert "nog niet ingeschakeld" in c.get("/inloggen").get_data(as_text=True)
    assert c.get("/auth/google").status_code == 404


def test_only_configured_provider_is_shown(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for k in ALL_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "y")
    html = create_app({"TESTING": True}).test_client().get("/inloggen").get_data(as_text=True)
    assert "Doorgaan met Google" in html and "Doorgaan met Facebook" not in html


def test_all_providers_listed(client):
    html = client.get("/inloggen").get_data(as_text=True)
    for label in ("Google", "Microsoft", "Apple", "Facebook"):
        assert f"Doorgaan met {label}" in html


# ---------- redirects to the provider ----------

@pytest.mark.parametrize("provider", ["google", "microsoft", "apple"])
def test_authorize_redirect(app, client, monkeypatch, provider):
    c = oauth_client(app, provider)
    monkeypatch.setattr(c, "load_server_metadata", lambda: META)
    resp = client.get(f"/auth/{provider}")
    assert resp.status_code == 302
    url = urlparse(resp.headers["Location"])
    q = parse_qs(url.query)
    assert url.netloc == "issuer.example"
    assert q["redirect_uri"] == [f"http://localhost/auth/{provider}/callback"]
    assert "openid" in q["scope"][0] and q["state"] and q["nonce"]
    if provider == "apple":
        assert q["response_mode"] == ["form_post"]


def test_facebook_redirect(client):
    resp = client.get("/auth/facebook")
    url = urlparse(resp.headers["Location"])
    assert url.netloc == "www.facebook.com" and "email" in parse_qs(url.query)["scope"][0]


def test_public_base_url_used_for_callback(tmp_path, monkeypatch):
    for k, v in ALL_KEYS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = create_app({"TESTING": True, "PUBLIC_BASE_URL": "https://papiamentu.example/"})
    monkeypatch.setattr(oauth_client(app, "google"), "load_server_metadata", lambda: META)
    loc = app.test_client().get("/auth/google").headers["Location"]
    assert parse_qs(urlparse(loc).query)["redirect_uri"] == ["https://papiamentu.example/auth/google/callback"]


# ---------- callbacks ----------

def test_google_login_creates_account(app, client, monkeypatch):
    resp = login_as(client, app, monkeypatch)
    assert resp.status_code == 302 and resp.headers["Location"] == "/"
    assert users(app) == [(1, "Ana", "ana@example.com")]
    assert "Ingelogd als" in client.get("/instellingen").get_data(as_text=True)


def test_second_login_reuses_account(app, client, monkeypatch):
    login_as(client, app, monkeypatch)
    client.post("/uitloggen", data={"csrf_token": csrf_of(client)})
    login_as(client, app, monkeypatch)
    assert len(users(app)) == 1


def test_accounts_not_merged_by_email(app, client, monkeypatch):
    login_as(client, app, monkeypatch, provider="google", sub="g1")
    client.post("/uitloggen", data={"csrf_token": csrf_of(client)})
    fake_token(app, monkeypatch, "microsoft", {"sub": "m1", "tid": "t", "given_name": "Ana", "email": "ana@example.com"})
    client.get("/auth/microsoft/callback?code=x&state=y")
    assert len(users(app)) == 2


def test_link_second_provider_while_logged_in(app, client, monkeypatch):
    login_as(client, app, monkeypatch, provider="google", sub="g1")
    fake_token(app, monkeypatch, "microsoft", {"sub": "m1", "tid": "t", "given_name": "Ana"})
    resp = client.get("/auth/microsoft/callback?code=x&state=y")
    assert resp.headers["Location"] == "/instellingen"
    assert len(users(app)) == 1
    html = client.get("/instellingen").get_data(as_text=True)
    assert "Gekoppeld met Google" in html and "Gekoppeld met Microsoft" in html


def test_facebook_login(app, client, monkeypatch):
    fake_token(app, monkeypatch, "facebook", me={"id": "fb1", "first_name": "Rik", "email": "rik@example.com"})
    client.get("/auth/facebook/callback?code=x&state=y")
    assert users(app) == [(1, "Rik", "rik@example.com")]


def test_apple_form_post_bounces_to_get(client):
    user = json.dumps({"name": {"firstName": "Sam"}})
    resp = client.post("/auth/apple/callback", data={"code": "c", "state": "s", "user": user})
    assert resp.status_code == 303
    q = parse_qs(urlparse(resp.headers["Location"]).query)
    assert q["code"] == ["c"] and q["state"] == ["s"] and json.loads(q["user"][0])["name"]["firstName"] == "Sam"


def test_apple_login_uses_first_name(app, client, monkeypatch):
    fake_token(app, monkeypatch, "apple", {"sub": "a1", "email": "x@privaterelay.appleid.com"})
    client.get("/auth/apple/callback?code=c&state=s&user=" + json.dumps({"name": {"firstName": "Sam"}}))
    assert users(app)[0][1] == "Sam"


def test_apple_client_secret_is_valid_jwt(app):
    c = oauth_client(app, "apple")
    with app.test_request_context():
        from papiamentu.auth import _client
        secret = _client("apple").client_secret
    public = ECKey.import_key(APPLE_KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    tok = jwt.decode(secret, public)
    assert tok.header["kid"] == "KEY123" and tok.claims["iss"] == "TEAM123"
    assert tok.claims["sub"] == "com.example.web" and tok.claims["aud"] == "https://appleid.apple.com"
    assert c is not None


def test_cancelled_login(app, client, monkeypatch):
    from authlib.integrations.base_client import OAuthError
    c = oauth_client(app, "google")
    monkeypatch.setattr(c, "authorize_access_token", lambda **kw: (_ for _ in ()).throw(OAuthError("access_denied")))
    resp = client.get("/auth/google/callback?error=access_denied")
    assert resp.headers["Location"] == "/inloggen"
    assert "geannuleerd" in client.get("/inloggen").get_data(as_text=True)
    assert users(app) == []


def test_login_redirects_to_next(app, client, monkeypatch):
    client.get("/inloggen?next=/lessen/3")
    assert login_as(client, app, monkeypatch).headers["Location"] == "/lessen/3"


def test_open_redirect_blocked(app, client, monkeypatch):
    client.get("/inloggen?next=//evil.example")
    assert login_as(client, app, monkeypatch).headers["Location"] == "/"


def test_microsoft_issuer_check():
    assert _valid_microsoft_issuer({"tid": "abc"}, "https://login.microsoftonline.com/abc/v2.0")
    assert not _valid_microsoft_issuer({"tid": "abc"}, "https://login.microsoftonline.com/other/v2.0")
    assert not _valid_microsoft_issuer({}, "https://login.microsoftonline.com//v2.0")


# ---------- logout & delete ----------

def test_logout_requires_csrf(app, client, monkeypatch):
    login_as(client, app, monkeypatch)
    assert client.post("/uitloggen").status_code == 400
    resp = client.post("/uitloggen", data={"csrf_token": csrf_of(client)})
    assert resp.headers["Location"] == "/?uitgelogd=1"
    assert "Ingelogd als" not in client.get("/instellingen").get_data(as_text=True)


def test_delete_account(app, client, monkeypatch):
    login_as(client, app, monkeypatch)
    token = csrf_of(client)
    client.put("/api/progress", json={"base_rev": None, "state": {"xp": 5}}, headers={"X-CSRF-Token": token})
    client.post("/account/verwijderen", data={"csrf_token": token})
    assert users(app) == []
    with sqlite3.connect(app.config["DATABASE"]) as db:
        assert db.execute("SELECT COUNT(*) FROM progress").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM identities").fetchone()[0] == 0


# ---------- progress API ----------

def test_progress_requires_login(client):
    assert client.put("/api/progress", json={"state": {}}).status_code == 401


def test_progress_requires_csrf_header(app, client, monkeypatch):
    login_as(client, app, monkeypatch)
    assert client.put("/api/progress", json={"state": {}}).status_code == 403


def test_progress_roundtrip_and_merge(app, client, monkeypatch):
    login_as(client, app, monkeypatch)
    h = {"X-CSRF-Token": csrf_of(client)}
    r1 = client.put("/api/progress", json={"base_rev": None, "state": {"xp": 10, "lessen": {"1": [1, 2]}}}, headers=h).json
    assert r1["rev"] == 1
    # Same device, on top of rev 1: spending XP sticks.
    r2 = client.put("/api/progress", json={"base_rev": 1, "state": {"xp": 8, "lessen": {"1": [1, 2]}}}, headers=h).json
    assert r2["state"]["xp"] == 8 and r2["rev"] == 2
    # Another device with stale rev: merged, nothing lost.
    r3 = client.put("/api/progress", json={"base_rev": 1, "state": {"xp": 3, "lessen": {"2": [1]}}}, headers=h).json
    assert r3["state"]["xp"] == 8 and r3["state"]["lessen"] == {"1": [1, 2], "2": [1]}


def test_progress_reset(app, client, monkeypatch):
    login_as(client, app, monkeypatch)
    h = {"X-CSRF-Token": csrf_of(client)}
    client.put("/api/progress", json={"base_rev": None, "state": {"xp": 10}}, headers=h)
    assert client.delete("/api/progress", headers=h).status_code == 200
    r = client.put("/api/progress", json={"base_rev": 1, "state": {"xp": 0}}, headers=h).json
    assert r["state"]["xp"] == 0


def test_progress_too_large(app, client, monkeypatch):
    login_as(client, app, monkeypatch)
    big = {"state": {"woorden": {f"w{i}": {"correct_count": 1} for i in range(20000)}}}
    assert client.put("/api/progress", json=big, headers={"X-CSRF-Token": csrf_of(client)}).status_code == 413


# ---------- merge rules ----------

def test_sanitize_drops_junk():
    s = sanitize({"xp": "12", "theme": "dark", "evil": 1, "lijsten": [3, "x"], "lessen": {"1": [9, 2, "a"]},
                  "woorden": {"w": {"correct_count": 999999, "is_mastered": 1}}, "profile": {"name": "  Bo  "}})
    assert s["xp"] == 12 and "theme" not in s and "evil" not in s
    assert s["lijsten"] == [1, 3] and s["lessen"] == {"1": [2, 4]} and s["profile"] == {"name": "Bo"}
    assert s["woorden"]["w"] == {"correct_count": 1000, "is_mastered": True}


def test_merge_keeps_best_of_both():
    a = sanitize({"xp": 5, "woorden": {"w1": {"correct_count": 2, "is_mastered": True}}, "lijsten": [1, 2],
                  "scenarios": {"s1": "2026-01-02"}})
    b = sanitize({"xp": 9, "woorden": {"w1": {"correct_count": 1}, "w2": {"correct_count": 1}},
                  "scenarios": {"s1": "2026-01-01", "s2": "2026-02-01"}, "profile": {"name": "B"}})
    m = merge(a, b)
    assert m["xp"] == 9 and m["lijsten"] == [1, 2] and m["profile"] == {"name": "B"}
    assert m["woorden"]["w1"] == {"correct_count": 2, "is_mastered": True} and "w2" in m["woorden"]
    assert m["scenarios"] == {"s1": "2026-01-01", "s2": "2026-02-01"}


def test_nieuws_sanitized_and_merged():
    a = sanitize({"nieuws": {"nieuws-001": "2026-03-02", "": "x", "n2": None}})
    assert a["nieuws"] == {"nieuws-001": "2026-03-02"}
    b = sanitize({"nieuws": {"nieuws-001": "2026-03-01", "nieuws-002": "2026-04-01"}})
    assert merge(a, b)["nieuws"] == {"nieuws-001": "2026-03-01", "nieuws-002": "2026-04-01"}


def test_old_client_without_nieuws_keeps_it():
    # A tab running stale JavaScript sends no "nieuws" key: don't wipe what the server has.
    stored = json.dumps(sanitize({"xp": 5, "nieuws": {"nieuws-001": "2026-03-01"}}))
    new, _ = resolve(stored, 2, {"xp": 6}, 2, replace=False)
    assert new["xp"] == 6 and new["nieuws"] == {"nieuws-001": "2026-03-01"}
    # ...but an explicit empty map (e.g. a restored backup) does replace it.
    new, _ = resolve(stored, 2, {"xp": 6, "nieuws": {}}, 2, replace=False)
    assert new["nieuws"] == {}


def test_xp_earned_sanitized_merged_and_protected():
    # xpEarned is the lifetime, spend-proof total the medal system is based on: it only ever
    # grows, sanitizes/merges like xp, and — like "nieuws" — is never wiped by a stale client.
    a = sanitize({"xpEarned": "12", "evil": 1})
    b = sanitize({"xpEarned": 9})
    assert a["xpEarned"] == 12
    assert merge(a, b)["xpEarned"] == 12

    stored = json.dumps(sanitize({"xp": 5, "xpEarned": 40}))
    new, _ = resolve(stored, 2, {"xp": 6}, 2, replace=False)
    assert new["xpEarned"] == 40
    new, _ = resolve(stored, 2, {"xp": 6, "xpEarned": 0}, 2, replace=False)
    assert new["xpEarned"] == 0


def test_replace_keeps_profile():
    stored = json.dumps(sanitize({"xp": 5, "profile": {"name": "Ana"}}))
    new, rev = resolve(stored, 3, {"xp": 0}, None, replace=True)
    assert new["xp"] == 0 and new["profile"] == {"name": "Ana"} and rev == 4
