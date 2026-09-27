import os
from datetime import timedelta
from pathlib import Path

import click
from markupsafe import escape
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for

from .admin import init_admin
from .auth import PROVIDERS, init_auth
from .content import KATEGORIA_NL, NIEUWS_UNLOCK, NIVEAU_COLOR, NIVEAU_LABEL, Content
from .db import backup_to, count_messages_since, get_db, init_db, save_contact_message
from .notify import notify_new_message
from .richtext import rich
from .security import client_fingerprint, csrf_valid, init_security

SCREEN_TITLES = {
    "scenarios": "Papiamentu Pa Bo",
    "scenario": "Scenario",
    "woorden": "Woorden Oefenen",
    "lessen": "Leer met lessen",
    "les": "Les",
    "nieuws": "Nieuws lezen",
    "eerste_week": "Eerste week op Curaçao",
    "nieuws_artikel": "Nieuws",
    "cultuur": "Cultuur lezen",
    "cultuur_artikel": "Cultuur",
    "profiel": "Profiel",
    "verder_leren": "Verder na de app",
    "contact": "Contact",
    "privacy": "Privacy",
    "instellingen": "Instellingen",
    "auth.login_page": "Inloggen",
    "admin.dashboard": "Beheer",
    "admin.messages": "Beheer · Berichten",
    "admin.users": "Beheer · Gebruikers",
}


def create_app(test_config=None):
    app = Flask(__name__)

    env = os.environ.get
    data_dir = Path(env("DATA_DIR", Path(app.root_path).parent / "instance"))
    data_dir.mkdir(parents=True, exist_ok=True)
    app.config.update(
        SECRET_KEY=env("SECRET_KEY", "dev-only-change-me"),
        DATABASE=str(data_dir / "papiamentu.sqlite3"),
        PROXY_COUNT=int(env("PROXY_COUNT", "0")),
        SESSION_COOKIE_SECURE=env("COOKIE_SECURE", "0") == "1",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Hard ceiling on any request body (sync API also checks Content-Length; this also
        # catches chunked uploads that send no Content-Length header). 512 KB is ample.
        MAX_CONTENT_LENGTH=512 * 1024,
        CONTACT_LIMIT_PER_IP_HOUR=int(env("CONTACT_LIMIT_PER_IP_HOUR", "5")),
        CONTACT_LIMIT_PER_DAY=int(env("CONTACT_LIMIT_PER_DAY", "100")),
        SMTP_HOST=env("SMTP_HOST", ""),
        SMTP_PORT=int(env("SMTP_PORT", "587")),
        SMTP_USER=env("SMTP_USER", ""),
        SMTP_PASSWORD=env("SMTP_PASSWORD", ""),
        SMTP_FROM=env("SMTP_FROM", ""),
        NOTIFY_EMAIL=env("NOTIFY_EMAIL", ""),
        PERMANENT_SESSION_LIFETIME=timedelta(days=90),
        PUBLIC_BASE_URL=env("PUBLIC_BASE_URL", ""),
        # Admin panel: only this Google account (verified e-mail) gets in. Empty = panel off.
        ADMIN_EMAIL=env("ADMIN_EMAIL", ""),
        ADMIN_PATH=env("ADMIN_PATH", "/dit/is/admin/panel"),
    )
    # OAuth keys: a provider is shown only when all of its settings are filled in.
    for spec in PROVIDERS.values():
        for key in spec["env"]:
            app.config[key] = env(key, "")
    if test_config:
        app.config.update(test_config)

    app.jinja_env.filters["rich"] = rich
    init_security(app)
    init_db(app)
    init_auth(app)
    init_admin(app)
    content = Content()
    app.extensions["content"] = content

    @app.context_processor
    def inject_globals():
        endpoint = request.endpoint or ""
        return {
            "screen_title": SCREEN_TITLES.get(endpoint, ""),
            "is_home": endpoint == "home",
            "NIVEAU_LABEL": NIVEAU_LABEL,
            "NIVEAU_COLOR": NIVEAU_COLOR,
            "KATEGORIA_NL": KATEGORIA_NL,
        }

    @app.get("/")
    def home():
        return render_template(
            "home.html",
            words=content.all_words(),
            lessen=[{"id": l["id"], "titel": l["titel"]} for l in content.lessen],
            totals={"scenarios": len(content.scenarios), "woorden": len(content.all_words()),
                    "nieuws": len(content.nieuws), "cultuur": len(content.cultuur)},
        )

    @app.get("/scenarios")
    def scenarios():
        items = [dict(s, number=i, has_data=s["id"] in content.scenarios)
                 for i, s in enumerate(content.scenario_list, start=1)]
        return render_template("scenarios.html", scenarios=items)

    @app.get("/scenarios/<scenario_id>")
    def scenario(scenario_id):
        data = content.scenarios.get(scenario_id)
        if not data:
            abort(404)
        return render_template("scenario.html", s=data,
                               screen_title=f"Scenario · {NIVEAU_LABEL.get(data['difficulty'], '')}")

    @app.get("/nieuws")
    def nieuws():
        items = [{"id": a["id"], "number": i, "titel": a["titel"], "nivo": a["nivo"],
                  "kategoria": a["kategoria"], "beschrijving": a["beschrijving"],
                  "alineas": len(a["paragrafen"]), "zinnen": sum(len(p["zinnen"]) for p in a["paragrafen"])}
                 for i, a in enumerate(content.nieuws.values(), start=1)]
        return render_template("nieuws.html", artikelen=items, unlock=NIEUWS_UNLOCK)

    @app.get("/nieuws/<artikel_id>")
    def nieuws_artikel(artikel_id):
        data = content.nieuws.get(artikel_id)
        if not data:
            abort(404)
        return render_template("nieuws_artikel.html", a=data, ids=list(content.nieuws), unlock=NIEUWS_UNLOCK,
                               screen_title=f"Nieuws · {NIVEAU_LABEL.get(data['nivo'], '')}")

    @app.get("/cultuur")
    def cultuur():
        items = [{"id": a["id"], "number": i, "titel": a["titel"], "kategoria": a["kategoria"],
                  "beschrijving": a["beschrijving"],
                  "alineas": len(a["paragrafen"]), "zinnen": sum(len(p["zinnen"]) for p in a["paragrafen"])}
                 for i, a in enumerate(content.cultuur.values(), start=1)]
        return render_template("cultuur.html", stukken=items)

    @app.get("/cultuur/<stuk_id>")
    def cultuur_artikel(stuk_id):
        data = content.cultuur.get(stuk_id)
        if not data:
            abort(404)
        return render_template("cultuur_artikel.html", a=data, screen_title=f"Cultuur · {data['kategoria']}")

    @app.get("/eerste-week")
    def eerste_week():
        # Puur naslag: geen quiz, geen voortgang. Bewust niets opslaan hier, in lijn met
        # zo min mogelijk gegevens verwerken — dit is een boekje om in te bladeren.
        return render_template("eerste_week.html", categorieen=content.noodwoordenboek)

    @app.get("/woorden")
    def woorden():
        # Alle woorden buiten de vaste woordenlijsten (die komen al binnen via `lijsten`):
        # woordenschat uit lessen/scenario's/nieuws, gekoppeld aan de bron zodat ze pas
        # geoefend kunnen worden zodra die content is gezien (zie woorden.html).
        extra = [w for w in content.alle_leerwoorden() if not w["bron"].startswith("woordenlijst-")]
        return render_template("woorden.html", lijsten=content.woordenlijsten, extra_woorden=extra)

    @app.get("/lessen")
    def lessen():
        return render_template("lessen.html", lessen=content.lessen)

    @app.get("/lessen/<int:les_id>")
    def les(les_id):
        data = content.lessen_by_id.get(les_id)
        if not data:
            abort(404)
        linked = [(sid, content.scenario_title(sid)) for sid in data.get("scenario_links", [])]
        return render_template("les.html", les=data, linked_scenarios=linked, screen_title=f"Les {les_id}")

    @app.route("/contact", methods=["GET", "POST"])
    def contact():
        if request.method == "GET":
            return render_template("contact.html", form={})

        def reject(msg, status):
            flash(msg, "error")
            return render_template("contact.html", form=request.form), status

        if not csrf_valid():
            return reject("Je sessie is verlopen. Probeer het nog eens.", 400)
        # Honeypot: bots tend to fill every field. Pretend it worked.
        if request.form.get("website"):
            flash("Dank je wel! Je bericht is verzonden.", "success")
            return redirect(url_for("contact"))

        one_line = lambda s: " ".join(s.split())  # no newlines in values that end up in mail headers
        name = one_line(request.form.get("name", ""))[:100]
        email = one_line(request.form.get("email", ""))[:200]
        subject = one_line(request.form.get("subject", ""))[:200]
        message = request.form.get("message", "").strip()[:5000]
        if not subject or not message:
            return reject("Vul een onderwerp en bericht in.", 400)
        if email and ("@" not in email or " " in email):
            return reject("Dat e-mailadres lijkt niet te kloppen.", 400)

        ip_hash = client_fingerprint(app.config["SECRET_KEY"])
        if (count_messages_since(1, ip_hash) >= app.config["CONTACT_LIMIT_PER_IP_HOUR"]
                or count_messages_since(24) >= app.config["CONTACT_LIMIT_PER_DAY"]):
            return reject("Je hebt de afgelopen tijd al veel berichten gestuurd. Probeer het later opnieuw.", 429)

        message_id = save_contact_message(name, email, subject, message, ip_hash)
        notify_new_message(app, message_id, name, email, subject, message)
        flash("Dank je wel! Je bericht is verzonden.", "success")
        return redirect(url_for("contact"))

    @app.get("/privacy")
    def privacy():
        return render_template("privacy.html")

    @app.get("/instellingen")
    def instellingen():
        return render_template("instellingen.html")

    @app.get("/profiel")
    def profiel():
        # Only scenarios and news articles carry a difficulty level, so the medal system (and
        # this page) is scoped to those two. "punten" is how much XP that item is worth (one
        # per quiz question), matching how much XP completing it actually earns you — the medal
        # thresholds are the total XP of a level's content, not which items you've done. No
        # account data is read here: everything is computed client-side from the browser's own
        # progress in localStorage.
        items = [{"nivo": s["difficulty"], "punten": len(content.scenarios[s["id"]].get("quiz", []))}
                 for s in content.scenario_list if s["id"] in content.scenarios]
        items += [{"nivo": a["nivo"], "punten": sum(len(p["zinnen"]) + 1 for p in a["paragrafen"])}
                  for a in content.nieuws.values()]
        return render_template("profiel.html", items=items)

    @app.get("/verder-leren")
    def verder_leren():
        # Statische verwijspagina, geen persoonlijke data nodig: geen taalmaatje-matching
        # (dat zou een account/contactgegevens vergen), puur verwijzingen naar bestaand,
        # echt Papiamentu-media en -initiatieven.
        return render_template("verder_leren.html")

    def site_url(path=""):
        base = app.config.get("PUBLIC_BASE_URL") or request.url_root
        return base.rstrip("/") + path

    @app.get("/robots.txt")
    def robots():
        body = "\n".join([
            "User-agent: *",
            "Disallow: /api/",
            "Disallow: /auth/",
            f"Sitemap: {site_url('/sitemap.xml')}",
            "",
        ])
        return app.response_class(body, mimetype="text/plain")

    @app.get("/sitemap.xml")
    def sitemap():
        paths = ["/", "/scenarios", "/woorden", "/lessen", "/nieuws", "/cultuur", "/eerste-week",
                 "/verder-leren", "/privacy", "/contact"]
        paths += [url_for("scenario", scenario_id=sid) for sid in content.scenarios]
        paths += [url_for("les", les_id=l["id"]) for l in content.lessen]
        paths += [url_for("nieuws_artikel", artikel_id=aid) for aid in content.nieuws]
        paths += [url_for("cultuur_artikel", stuk_id=sid) for sid in content.cultuur]
        urls = "".join(f"<url><loc>{escape(site_url(p))}</loc></url>" for p in paths)
        xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
        return app.response_class(xml, mimetype="application/xml")

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("404.html"), 404

    @app.cli.command("messages")
    def list_messages():
        """Print the contact-form messages, newest first."""
        rows = get_db().execute(
            "SELECT * FROM contact_messages ORDER BY id DESC"
        ).fetchall()
        if not rows:
            print("Geen berichten.")
        for r in rows:
            who = " ".join(x for x in (r["name"], f"<{r['email']}>" if r["email"] else "") if x)
            print(f"#{r['id']}  {r['created_at']}  {who or '(anoniem)'}\n  {r['subject']}\n  {r['message']}\n")

    @app.cli.command("backup")
    @click.argument("path")
    def backup(path):
        """Write a consistent copy of the database to PATH."""
        backup_to(path)
        print(f"Backup geschreven naar {path}")

    return app
