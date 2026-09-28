import json
import re
import sqlite3

import pytest

from papiamentu import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = create_app({"TESTING": True, "SECRET_KEY": "test", "CONTACT_LIMIT_PER_IP_HOUR": 2})
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client):
    html = client.get("/contact").get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def post_contact(client, **fields):
    data = {"csrf_token": csrf(client), "subject": "Hoi", "message": "Een bericht"}
    data.update(fields)
    return client.post("/contact", data=data)


def message_count(app):
    with sqlite3.connect(app.config["DATABASE"]) as db:
        return db.execute("SELECT COUNT(*) FROM contact_messages").fetchone()[0]


# ---------- pages & content ----------

@pytest.mark.parametrize("path", [
    "/", "/scenarios", "/woorden", "/lessen", "/nieuws", "/cultuur", "/profiel", "/eerste-week", "/verder-leren", "/updates",
    "/contact", "/privacy", "/instellingen", "/healthz",
])
def test_pages_ok(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    if path != "/healthz":
        # speak.js (uitspraak-knop) loads via base.html on every real page.
        assert "js/speak.js" in resp.get_data(as_text=True)


def test_every_scenario_and_lesson_renders(app, client):
    content = app.extensions["content"]
    for sid in content.scenarios:
        assert client.get(f"/scenarios/{sid}").status_code == 200, sid
    for les in content.lessen:
        assert client.get(f"/lessen/{les['id']}").status_code == 200, les["id"]
    for aid in content.nieuws:
        assert client.get(f"/nieuws/{aid}").status_code == 200, aid


@pytest.mark.parametrize("path", ["/nope", "/scenarios/scenario-999", "/lessen/999", "/nieuws/nieuws-999"])
def test_not_found(client, path):
    assert client.get(path).status_code == 404


def test_content_integrity(app):
    c = app.extensions["content"]
    assert len(c.scenarios) == 26 and len(c.lessen) == 40 and len(c.woordenlijsten) == 6
    listed = {s["id"] for s in c.scenario_list}
    for les in c.lessen:
        assert len(les["eindoefening"]) >= 14, "pass mark is 14"
        for q in les["eindoefening"]:
            assert set(q) == {"vraag", "opties", "correct"}, (les["id"], q)
            assert q["vraag"].strip(), les["id"]
            assert 0 <= q["correct"] < len(q["opties"])
            assert len({o.strip().lower() for o in q["opties"]}) == len(q["opties"]), (les["id"], q["vraag"])
    for sid, s in c.scenarios.items():
        for q in s["quiz"] + s["grammar"]["exercises"]:
            assert q["question"].strip() and 0 <= q["correct"] < len(q["options"]), (sid, q)
        if "dialoog" in s:
            knopen = s["dialoog"]["knopen"]
            assert s["dialoog"]["start"] in knopen, sid
            for kid, k in knopen.items():
                assert k["npc"].strip() and k["npc_nl"].strip(), (sid, kid)
                for keuze in k["keuzes"]:
                    assert keuze["pap"].strip() and keuze["nl"].strip(), (sid, kid)
                    assert keuze["gaat_naar"] in knopen, (sid, kid, keuze["gaat_naar"])
        for sid in les.get("scenario_links", []):
            assert sid in c.scenarios and sid in listed
    word_ids = [w["id"] for l in c.woordenlijsten for w in l["woorden"]]
    assert len(word_ids) == len(set(word_ids))


def test_alle_leerwoorden_unique_and_complete(app):
    # De centrale woordenschat-motor (Fase 2): elk woord-id is uniek over de hele site, en
    # elk woord heeft een niet-lege papiamentu/uitspraak/vertaling/bron.
    c = app.extensions["content"]
    woorden = c.alle_leerwoorden()
    ids = [w["id"] for w in woorden]
    assert len(ids) == len(set(ids))
    assert len(woorden) >= sum(len(l["woorden"]) for l in c.woordenlijsten)
    for w in woorden:
        assert set(w) == {"id", "woord", "uitspraak", "vertaling", "bron"}
        assert w["woord"].strip() and w["uitspraak"].strip() and w["vertaling"].strip() and w["bron"].strip()
    # De vaste woordenlijst-ids blijven ongewijzigd (bestaande voortgang mag nooit breken).
    lijst_ids = {w["id"] for l in c.woordenlijsten for w in l["woorden"]}
    assert lijst_ids <= set(ids)


def test_noodwoordenboek_integrity(app, client):
    c = app.extensions["content"]
    assert len(c.noodwoordenboek) >= 4
    for cat in c.noodwoordenboek:
        assert cat["naam"].strip() and cat["zinnen"]
        for z in cat["zinnen"]:
            assert z["papiamentu"].strip() and z["uitspraak"].strip() and z["vertaling"].strip()
    html = client.get("/eerste-week").get_data(as_text=True)
    assert c.noodwoordenboek[0]["zinnen"][0]["papiamentu"] in html


def test_updates_integrity(app, client):
    c = app.extensions["content"]
    assert c.updates, "op zijn minst één update"
    ids = [u["id"] for u in c.updates]
    assert ids == sorted(ids, reverse=True), "nieuwste eerst"
    for u in c.updates:
        assert u["id"].strip() and u["titel"].strip() and u["punten"]
        for p in u["punten"]:
            assert p.strip()

    html = client.get("/updates").get_data(as_text=True)
    assert c.updates[0]["titel"] in html

    # De homepage stuurt dezelfde updates mee (voor het eenmalige "wat is er nieuw"-scherm).
    home_html = client.get("/").get_data(as_text=True)
    assert c.updates[0]["id"] in home_html


def test_nieuws_integrity(app):
    from papiamentu.content import KATEGORIA_NL, NIVEAU_LABEL
    c = app.extensions["content"]
    assert c.nieuws, "at least one article"

    def check_question(where, q):
        assert 3 <= len(q["opties"]) <= 6 and 0 <= q["correct"] < len(q["opties"]), where
        assert len({o.strip().lower() for o in q["opties"]}) == len(q["opties"]), where
        assert all(o.strip() for o in q["opties"]), where

    # Unlocking goes by position, so ids must be a gap-free sequence nieuws-001, nieuws-002, ...
    assert list(c.nieuws) == [f"nieuws-{i:03d}" for i in range(1, len(c.nieuws) + 1)]
    for aid, a in c.nieuws.items():
        assert aid.startswith("nieuws-") and len(aid) <= 40
        assert a["titel"].strip() and a["beschrijving"].strip(), aid
        assert a["nivo"] in NIVEAU_LABEL and a["kategoria"] in KATEGORIA_NL, aid
        assert a["paragrafen"], aid
        for pi, p in enumerate(a["paragrafen"]):
            check_question((aid, pi), p)
            assert p["vraag"].strip() and p["uitleg"].strip(), (aid, pi)
            assert p["zinnen"], (aid, pi)
            for z in p["zinnen"]:
                assert z["pap"].strip() and z["nl"].strip() and z["uitleg"].strip(), (aid, z["pap"])
                check_question((aid, z["pap"]), z)
        for w in a.get("sleutelwoorden", []):
            assert w["woord"] and w["uitspraak"] and w["vertaling"], aid


def test_home_and_sitemap_link_nieuws(app, client):
    assert 'href="/nieuws"' in client.get("/").get_data(as_text=True)
    sitemap = client.get("/sitemap.xml").get_data(as_text=True)
    assert "/nieuws/nieuws-001" in sitemap


def test_cultuur_integrity(app, client):
    c = app.extensions["content"]
    assert c.cultuur, "op zijn minst één cultuurstuk"

    def check_question(where, q):
        assert 3 <= len(q["opties"]) <= 6 and 0 <= q["correct"] < len(q["opties"]), where
        assert len({o.strip().lower() for o in q["opties"]}) == len(q["opties"]), where
        assert all(o.strip() for o in q["opties"]), where

    assert list(c.cultuur) == [f"cultuur-{i:03d}" for i in range(1, len(c.cultuur) + 1)]
    for cid, a in c.cultuur.items():
        assert a["titel"].strip() and a["beschrijving"].strip() and a["kategoria"].strip(), cid
        assert a["paragrafen"], cid
        for pi, p in enumerate(a["paragrafen"]):
            check_question((cid, pi), p)
            assert p["vraag"].strip() and p["uitleg"].strip(), (cid, pi)
            for z in p["zinnen"]:
                assert z["pap"].strip() and z["nl"].strip() and z["uitleg"].strip(), (cid, z["pap"])
                check_question((cid, z["pap"]), z)
        for w in a.get("sleutelwoorden", []):
            assert w["woord"] and w["uitspraak"] and w["vertaling"], cid

    assert 'href="/cultuur"' in client.get("/").get_data(as_text=True)
    assert client.get("/cultuur/cultuur-001").status_code == 200
    sitemap = client.get("/sitemap.xml").get_data(as_text=True)
    assert "/cultuur/cultuur-001" in sitemap


def test_profiel_medal_thresholds_match_content(app, client):
    content = app.extensions["content"]
    html = client.get("/profiel").get_data(as_text=True)
    items = json.loads(re.search(r"const ITEMS = (\[.*?\]);", html, re.DOTALL).group(1))

    # One entry per scenario that actually has data, plus one per news article.
    assert len(items) == len(content.scenarios) + len(content.nieuws)
    assert all(set(it) == {"nivo", "punten"} and it["punten"] > 0 for it in items)

    by_nivo = {}
    for it in items:
        by_nivo[it["nivo"]] = by_nivo.get(it["nivo"], 0) + it["punten"]
    expected = {}
    for s in content.scenario_list:
        if s["id"] in content.scenarios:
            expected[s["difficulty"]] = expected.get(s["difficulty"], 0) + len(content.scenarios[s["id"]]["quiz"])
    for a in content.nieuws.values():
        expected[a["nivo"]] = expected.get(a["nivo"], 0) + sum(len(p["zinnen"]) + 1 for p in a["paragrafen"])
    assert by_nivo == expected

    # /profiel isn't personal data anywhere on the site: it's not in the sitemap or robots.
    assert "/profiel" not in client.get("/sitemap.xml").get_data(as_text=True)


# ---------- contact form ----------

def test_contact_saves_message(app, client):
    resp = post_contact(client, name="Ana", email="ana@example.com")
    assert resp.status_code == 302
    assert message_count(app) == 1


def test_contact_requires_csrf(app, client):
    client.get("/contact")
    resp = client.post("/contact", data={"subject": "x", "message": "y"})
    assert resp.status_code == 400
    assert message_count(app) == 0


def test_contact_rejects_empty(app, client):
    assert post_contact(client, subject="", message="").status_code == 400
    assert message_count(app) == 0


def test_contact_rejects_bad_email(app, client):
    assert post_contact(client, email="geen-adres").status_code == 400


def test_honeypot_discards(app, client):
    assert post_contact(client, website="http://spam").status_code == 302
    assert message_count(app) == 0


def test_rate_limit_per_ip(app, client):
    assert post_contact(client).status_code == 302
    assert post_contact(client).status_code == 302
    assert post_contact(client).status_code == 429
    assert message_count(app) == 2


def test_raw_ip_not_stored(app, client):
    post_contact(client)
    with sqlite3.connect(app.config["DATABASE"]) as db:
        ip_hash = db.execute("SELECT ip_hash FROM contact_messages").fetchone()[0]
    assert ip_hash and "127.0.0.1" not in ip_hash


def test_subject_newlines_stripped(app, client):
    post_contact(client, subject="Hoi\r\nBcc: evil@example.com")
    with sqlite3.connect(app.config["DATABASE"]) as db:
        subject = db.execute("SELECT subject FROM contact_messages").fetchone()[0]
    assert "\n" not in subject and "\r" not in subject


def test_old_database_is_migrated(tmp_path, monkeypatch):
    db_path = tmp_path / "papiamentu.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE contact_messages (id INTEGER PRIMARY KEY, name TEXT, email TEXT, "
                   "subject TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL)")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    create_app({"TESTING": True})
    with sqlite3.connect(db_path) as db:
        cols = {r[1] for r in db.execute("PRAGMA table_info(contact_messages)")}
    assert "ip_hash" in cols


def test_backup_command(app, tmp_path):
    with app.app_context():
        from papiamentu.db import save_contact_message
        save_contact_message("", "", "s", "m", "h")
    target = tmp_path / "backup.sqlite3"
    result = app.test_cli_runner().invoke(args=["backup", str(target)])
    assert result.exit_code == 0
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT COUNT(*) FROM contact_messages").fetchone()[0] == 1


# ---------- security headers, proxy, caching ----------

def test_security_headers_and_nonce(client):
    resp = client.get("/")
    csp = resp.headers["Content-Security-Policy"]
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    html = resp.get_data(as_text=True)
    scripts = re.findall(r"<script\b[^>]*>", html)
    assert scripts and all(f'nonce="{nonce}"' in s for s in scripts)
    assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "Strict-Transport-Security" not in resp.headers  # plain http


def test_nonce_changes_per_request(client):
    a = client.get("/").headers["Content-Security-Policy"]
    b = client.get("/").headers["Content-Security-Policy"]
    assert a != b


def test_proxy_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROXY_COUNT", "1")
    client = create_app({"TESTING": True}).test_client()
    resp = client.get("/", headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.9"})
    assert "Strict-Transport-Security" in resp.headers


def test_rate_limit_uses_forwarded_ip(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROXY_COUNT", "1")
    app = create_app({"TESTING": True, "CONTACT_LIMIT_PER_IP_HOUR": 1})
    a, b = app.test_client(), app.test_client()
    for c, ip in ((a, "203.0.113.1"), (b, "203.0.113.2")):
        token = csrf(c)
        resp = c.post("/contact", data={"csrf_token": token, "subject": "s", "message": "m"},
                      headers={"X-Forwarded-For": ip})
        assert resp.status_code == 302, ip  # different visitors behind the same proxy


def test_static_urls_are_versioned(client):
    html = client.get("/").get_data(as_text=True)
    assert re.search(r'/static/css/style\.css\?v=[0-9a-f]{10}', html)
    assert re.search(r'/static/js/store\.js\?v=[0-9a-f]{10}', html)
    resp = client.get(re.search(r'(/static/css/style\.css\?v=[0-9a-f]+)', html).group(1))
    assert "max-age=31536000" in resp.headers["Cache-Control"]


# ---------- e-mail notification ----------

def test_notification_email(tmp_path, monkeypatch):
    import papiamentu.notify as notify

    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent.append(("connect", host, port))
        def starttls(self, context=None): sent.append(("starttls",))
        def login(self, user, pw): sent.append(("login", user))
        def send_message(self, msg): sent.append(("msg", msg))
        def __enter__(self): return self
        def __exit__(self, *a): pass

    class SyncThread:
        def __init__(self, target, args, daemon=None): self.target, self.args = target, args
        def start(self): self.target(*self.args)

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(notify.threading, "Thread", SyncThread)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = create_app({"TESTING": True, "SMTP_HOST": "smtp.example.com", "SMTP_USER": "u",
                      "SMTP_PASSWORD": "p", "NOTIFY_EMAIL": "me@example.com"})
    client = app.test_client()
    assert post_contact(client, email="ana@example.com", subject="Vraag").status_code == 302

    msg = next(s[1] for s in sent if s[0] == "msg")
    assert ("connect", "smtp.example.com", 587) in sent and ("starttls",) in sent
    assert msg["To"] == "me@example.com"
    assert msg["Reply-To"] == "ana@example.com"
    assert "Vraag" in msg["Subject"]


def test_no_notification_without_smtp(client, monkeypatch):
    import papiamentu.notify as notify
    monkeypatch.setattr(notify.threading, "Thread", lambda **kw: (_ for _ in ()).throw(AssertionError("sent")))
    assert post_contact(client).status_code == 302
