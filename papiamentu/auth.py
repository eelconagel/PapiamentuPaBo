"""Optional sign-in with Google, Microsoft, Apple and Facebook, plus the progress-sync API.

A provider only shows up when its keys are set in the environment. Accounts are matched on
the provider's user id (never on e-mail address), so one person can link several providers
to the same account by logging in with another provider while already logged in.
"""
import json
import time
from urllib.parse import urlencode

from authlib.integrations.base_client import OAuthError
from authlib.integrations.flask_client import OAuth
from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from joserfc import jwt
from joserfc.jwk import ECKey

from . import db
from .security import csrf_token, csrf_valid
from .sync import MAX_BYTES, resolve

bp = Blueprint("auth", __name__)

# Display order on the login page.
PROVIDERS = {
    "google": {"label": "Google", "env": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")},
    "microsoft": {"label": "Microsoft", "env": ("MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET")},
    "apple": {"label": "Apple", "env": ("APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_PRIVATE_KEY")},
    "facebook": {"label": "Facebook", "env": ("FACEBOOK_CLIENT_ID", "FACEBOOK_CLIENT_SECRET")},
}

APPLE_ISSUER = "https://appleid.apple.com"


def enabled_providers(app=None) -> list[str]:
    app = app or current_app
    return [p for p, spec in PROVIDERS.items() if all(app.config.get(k) for k in spec["env"])]


def _apple_client_secret(config) -> str:
    """Apple wants a short-lived JWT signed with your .p8 key instead of a fixed secret."""
    now = int(time.time())
    key = ECKey.import_key(config["APPLE_PRIVATE_KEY"].replace("\\n", "\n"))
    return jwt.encode(
        {"alg": "ES256", "kid": config["APPLE_KEY_ID"]},
        {"iss": config["APPLE_TEAM_ID"], "iat": now, "exp": now + 3600,
         "aud": APPLE_ISSUER, "sub": config["APPLE_CLIENT_ID"]},
        key,
    )


def init_auth(app):
    oauth = OAuth(app)  # one registry per app; reachable via app.extensions
    c = app.config
    enabled = enabled_providers(app)
    if "google" in enabled:
        oauth.register(
            "google", client_id=c["GOOGLE_CLIENT_ID"], client_secret=c["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
            authorize_params={"prompt": "select_account"},
        )
    if "microsoft" in enabled:
        oauth.register(
            "microsoft", client_id=c["MICROSOFT_CLIENT_ID"], client_secret=c["MICROSOFT_CLIENT_SECRET"],
            # "common" = personal (Outlook/Hotmail/Live) and work/school accounts.
            server_metadata_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
            authorize_params={"prompt": "select_account"},
        )
    if "apple" in enabled:
        oauth.register(
            "apple", client_id=c["APPLE_CLIENT_ID"], client_secret="set-per-request",
            server_metadata_url=f"{APPLE_ISSUER}/.well-known/openid-configuration",
            client_kwargs={"scope": "openid name email", "token_endpoint_auth_method": "client_secret_post"},
            authorize_params={"response_mode": "form_post"},
        )
    if "facebook" in enabled:
        oauth.register(
            "facebook", client_id=c["FACEBOOK_CLIENT_ID"], client_secret=c["FACEBOOK_CLIENT_SECRET"],
            authorize_url="https://www.facebook.com/dialog/oauth",
            access_token_url="https://graph.facebook.com/oauth/access_token",
            api_base_url="https://graph.facebook.com/",
            client_kwargs={"scope": "public_profile email"},
        )

    @app.before_request
    def load_user():
        g.user = None
        uid = session.get("uid")
        if uid is not None:
            g.user = db.get_user(uid)
            if g.user is None:  # account was deleted elsewhere
                session.pop("uid", None)

    @app.context_processor
    def inject_auth():
        user = g.get("user")
        return {
            "current_user": user,
            "login_providers": [(p, PROVIDERS[p]["label"]) for p in enabled_providers()],
            "user_providers": [r["provider"] for r in db.get_user_identities(user["id"])] if user else [],
            "PROVIDER_LABELS": {p: s["label"] for p, s in PROVIDERS.items()},
            "user_meta": user_meta,
        }

    app.register_blueprint(bp)


def _safe_next(value) -> str:
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return url_for("home")


def _redirect_uri(provider: str) -> str:
    base = current_app.config.get("PUBLIC_BASE_URL")
    if base:
        return base.rstrip("/") + url_for("auth.callback", provider=provider)
    return url_for("auth.callback", provider=provider, _external=True)


def _client(provider: str):
    if provider not in enabled_providers():
        abort(404)
    client = current_app.extensions["authlib.integrations.flask_client"].create_client(provider)
    if provider == "apple":
        client.client_secret = _apple_client_secret(current_app.config)
    return client


# ---------- login flow ----------

@bp.get("/inloggen")
def login_page():
    if request.args.get("next"):
        session["login_next"] = _safe_next(request.args["next"])
    return render_template("inloggen.html")


@bp.get("/auth/<provider>")
def login(provider):
    return _client(provider).authorize_redirect(_redirect_uri(provider))


@bp.route("/auth/<provider>/callback", methods=["GET", "POST"])
def callback(provider):
    client = _client(provider)
    if request.method == "POST":
        # Apple posts the result cross-site, and browsers don't send our (SameSite=Lax)
        # session cookie with that POST. Bounce to a GET on ourselves, which does carry it.
        params = {k: request.form[k] for k in ("code", "state", "error", "user") if k in request.form}
        return redirect(url_for("auth.callback", provider=provider) + "?" + urlencode(params), code=303)

    try:
        kwargs = {}
        if provider == "microsoft":
            kwargs["claims_options"] = {"iss": {"essential": True, "validate": _valid_microsoft_issuer}}
        token = client.authorize_access_token(**kwargs)
        identity = _identity(provider, client, token)
    except OAuthError as exc:
        current_app.logger.info("Login via %s mislukt: %s", provider, exc)
        flash("Inloggen is geannuleerd of mislukt. Probeer het nog eens.", "error")
        return redirect(url_for("auth.login_page"))
    except Exception:
        current_app.logger.exception("Login via %s mislukt", provider)
        flash("Inloggen is mislukt. Probeer het later nog eens.", "error")
        return redirect(url_for("auth.login_page"))

    return _finish_login(provider, identity)


def _valid_microsoft_issuer(claims, value) -> bool:
    return bool(claims.get("tid")) and value == f"https://login.microsoftonline.com/{claims['tid']}/v2.0"


def _identity(provider: str, client, token) -> dict:
    """Normalise what each provider tells us into subject / name / email."""
    if provider == "facebook":
        me = client.get("me", params={"fields": "id,first_name,name,email"}, token=token).json()
        if "id" not in me:
            raise OAuthError(description="Facebook gaf geen gebruikers-id terug")
        return {"subject": str(me["id"]), "name": me.get("first_name") or me.get("name") or "",
                "email": me.get("email") or ""}

    info = token.get("userinfo")
    if not info or not info.get("sub"):
        raise OAuthError(description="Geen geldig ID-token ontvangen")

    if provider == "microsoft":
        email = info.get("email") or ""
        return {"subject": f"{info['tid']}:{info['sub']}",
                "name": info.get("given_name") or (info.get("name") or "").split(" ")[0],
                "email": email}

    if provider == "apple":
        name = ""
        try:  # Apple only sends the name the very first time someone signs in.
            user = json.loads(request.args.get("user", "{}"))
            name = (user.get("name") or {}).get("firstName") or ""
        except (ValueError, AttributeError):
            pass
        return {"subject": info["sub"], "name": name, "email": info.get("email") or ""}

    # google
    return {"subject": info["sub"], "name": info.get("given_name") or info.get("name") or "",
            "email": info.get("email") or ""}


def _finish_login(provider: str, identity: dict):
    subject, name, email = identity["subject"], identity["name"][:60], identity["email"][:200]
    existing = db.find_identity(provider, subject)
    current = g.get("user")

    if current is not None:
        # Already logged in: link this provider to the current account.
        if existing is None:
            db.add_identity(current["id"], provider, subject, email)
            flash(f"{PROVIDERS[provider]['label']} is gekoppeld aan je account.", "success")
        elif existing["user_id"] != current["id"]:
            flash(f"Dit {PROVIDERS[provider]['label']}-account hoort al bij een ander profiel.", "error")
        db.get_db().commit()
        return redirect(url_for("instellingen"))

    if existing is not None:
        user_id = existing["user_id"]
    else:
        user_id = db.create_user(name or (email.split("@")[0] if email else "Leerling"), email)
        db.add_identity(user_id, provider, subject, email)
    db.touch_login(user_id, provider, subject, email)
    db.get_db().commit()

    next_url = session.get("login_next")
    session.clear()  # fresh session on login (no fixation, drops OAuth state)
    session.permanent = True
    session["uid"] = user_id
    return redirect(_safe_next(next_url))


@bp.post("/uitloggen")
def logout():
    if not csrf_valid():
        abort(400)
    session.clear()
    # The browser clears its local copy of the progress when it sees this flag.
    return redirect(url_for("home", uitgelogd=1))


@bp.post("/account/verwijderen")
def delete_account():
    if not csrf_valid() or g.user is None:
        abort(400)
    db.delete_user(g.user["id"])
    session.clear()
    return redirect(url_for("home", uitgelogd=1, verwijderd=1))


# ---------- progress sync API ----------

def _api_guard():
    if g.user is None:
        return jsonify(error="not_logged_in"), 401
    expected = session.get("_csrf")
    if not expected or request.headers.get("X-CSRF-Token") != expected:
        return jsonify(error="csrf"), 403
    return None


@bp.put("/api/progress")
def put_progress():
    if (err := _api_guard()) is not None:
        return err
    if (request.content_length or 0) > MAX_BYTES:
        return jsonify(error="too_large"), 413
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="bad_request"), 400

    uid = g.user["id"]
    conn = db.get_db()
    conn.commit()  # close any implicit transaction before taking the write lock
    conn.execute("BEGIN IMMEDIATE")  # serialise concurrent saves for the same user
    row = db.get_progress(uid)
    state, rev = resolve(row["data"] if row else None, row["rev"] if row else None,
                         body.get("state"), body.get("base_rev"), bool(body.get("replace")))
    db.put_progress(uid, json.dumps(state, separators=(",", ":")), rev)
    conn.commit()
    return jsonify(rev=rev, state=state)


@bp.delete("/api/progress")
def reset_progress():
    if (err := _api_guard()) is not None:
        return err
    db.delete_progress(g.user["id"])
    return jsonify(ok=True)


def user_meta():
    """Values the page needs to sync (rendered into a <meta> tag)."""
    user = g.get("user")
    if user is None:
        return None
    return {"id": user["id"], "name": user["name"] or "", "csrf": csrf_token()}
