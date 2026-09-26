import re
import sqlite3

import pytest

from papiamentu import create_app
from test_auth import ALL_KEYS, csrf_of, fake_token, login_as, users

ADMIN = "eelconagel@gmail.com"
PANEL = "/dit/is/admin/panel/"


@pytest.fixture
def app(tmp_path, monkeypatch):
    for k, v in ALL_KEYS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return create_app({"TESTING": True, "SECRET_KEY": "test", "ADMIN_EMAIL": ADMIN})


@pytest.fixture
def client(app):
    return app.test_client()


def login_admin(client, app, monkeypatch):
    return login_as(client, app, monkeypatch, sub="admin-sub", name="Eelco", email="EelcoNagel@gmail.com")


def add_message(app, subject="Vraag", message="Hoi!"):
    with app.app_context():
        from papiamentu.db import save_contact_message
        return save_contact_message("Bo", "bo@example.com", subject, message, "hash")


def test_anonymous_is_sent_to_login(client):
    resp = client.get(PANEL)
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/inloggen?next=")


def test_login_then_back_to_panel(app, client, monkeypatch):
    client.get("/inloggen?next=" + PANEL)
    resp = login_admin(client, app, monkeypatch)
    assert resp.headers["Location"] == PANEL
    assert client.get(PANEL).status_code == 200


def test_other_user_gets_404(app, client, monkeypatch):
    login_as(client, app, monkeypatch, sub="someone", email="someone@gmail.com")
    for path in (PANEL, PANEL + "berichten", PANEL + "gebruikers"):
        assert client.get(path).status_code == 404


def test_unverified_google_email_is_not_admin(app, client, monkeypatch):
    login_as(client, app, monkeypatch, sub="fake", email=ADMIN, verified=False)
    assert client.get(PANEL).status_code == 404


def test_same_email_via_other_provider_is_not_admin(app, client, monkeypatch):
    fake_token(app, monkeypatch, "microsoft", {"sub": "m", "tid": "t", "given_name": "X", "email": ADMIN})
    client.get("/auth/microsoft/callback?code=x&state=y")
    assert client.get(PANEL).status_code == 404


def test_panel_off_without_admin_email(tmp_path, monkeypatch):
    for k, v in ALL_KEYS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = create_app({"TESTING": True, "ADMIN_EMAIL": ""})
    c = app.test_client()
    assert c.get(PANEL).status_code == 404
    login_admin(c, app, monkeypatch)
    assert c.get(PANEL).status_code == 404


def test_custom_path(tmp_path, monkeypatch):
    for k, v in ALL_KEYS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = create_app({"TESTING": True, "ADMIN_EMAIL": ADMIN, "ADMIN_PATH": "geheim/beheer"})
    c = app.test_client()
    login_admin(c, app, monkeypatch)
    assert c.get("/geheim/beheer/").status_code == 200
    assert c.get(PANEL).status_code == 404


def test_dashboard_shows_stats_and_headers(app, client, monkeypatch):
    add_message(app, subject="Idee voor scenario")
    login_admin(client, app, monkeypatch)
    resp = client.get(PANEL)
    html = resp.get_data(as_text=True)
    assert "Idee voor scenario" in html and "accounts" in html
    assert resp.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert resp.headers["Cache-Control"] == "no-store"


def test_settings_link_only_for_admin(app, client, monkeypatch):
    login_admin(client, app, monkeypatch)
    assert "Beheer" in client.get("/instellingen").get_data(as_text=True)
    other = app.test_client()
    login_as(other, app, monkeypatch, sub="x", email="x@gmail.com")
    assert PANEL not in other.get("/instellingen").get_data(as_text=True)


def test_delete_message(app, client, monkeypatch):
    mid = add_message(app)
    login_admin(client, app, monkeypatch)
    token = csrf_of(client)
    assert client.post(f"{PANEL}berichten/{mid}/verwijderen").status_code == 400  # no CSRF
    resp = client.post(f"{PANEL}berichten/{mid}/verwijderen", data={"csrf_token": token})
    assert resp.status_code == 302
    with sqlite3.connect(app.config["DATABASE"]) as db:
        assert db.execute("SELECT COUNT(*) FROM contact_messages").fetchone()[0] == 0


def test_users_list_and_delete(app, client, monkeypatch):
    other = app.test_client()
    login_as(other, app, monkeypatch, sub="u2", name="Rik", email="rik@gmail.com")
    h = {"X-CSRF-Token": csrf_of(other)}
    other.put("/api/progress", json={"base_rev": None, "state": {"xp": 42, "lessen": {"1": [1, 2, 3, 4]}}}, headers=h)

    login_admin(client, app, monkeypatch)
    html = client.get(PANEL + "gebruikers").get_data(as_text=True)
    assert "Rik" in html and "42 XP" in html and "1 lessen" in html

    rik_id = next(u[0] for u in users(app) if u[1] == "Rik")
    admin_id = next(u[0] for u in users(app) if u[1] == "Eelco")
    token = csrf_of(client)
    client.post(f"{PANEL}gebruikers/{admin_id}/verwijderen", data={"csrf_token": token})
    client.post(f"{PANEL}gebruikers/{rik_id}/verwijderen", data={"csrf_token": token})
    names = [u[1] for u in users(app)]
    assert names == ["Eelco"]  # admin can't delete themselves; Rik is gone
    assert other.get("/instellingen").get_data(as_text=True).count("Ingelogd als") == 0  # Rik's session ended


def test_message_html_is_escaped(app, client, monkeypatch):
    add_message(app, subject="<script>x</script>", message="<img src=x onerror=alert(1)>")
    login_admin(client, app, monkeypatch)
    html = client.get(PANEL + "berichten").get_data(as_text=True)
    assert "<script>x</script>" not in html and "&lt;img" in html
