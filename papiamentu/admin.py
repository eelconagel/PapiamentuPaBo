"""Mini admin panel: stats, contact messages and users.

Reachable at ADMIN_PATH (default /dit/is/admin/panel), only for the logged-in user whose Google
login has the verified address ADMIN_EMAIL. Everyone else who is logged in gets a plain 404, so the
panel's existence isn't advertised; visitors who aren't logged in are sent to the login page first.
"""
import json
from functools import wraps

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   url_for)

from . import db
from .security import csrf_valid

bp = Blueprint("admin", __name__, template_folder="templates")


def is_admin(user) -> bool:
    email = current_app.config.get("ADMIN_EMAIL", "").strip()
    return bool(email and user is not None and db.has_google_email(user["id"], email))


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_app.config.get("ADMIN_EMAIL"):
            abort(404)
        if g.get("user") is None:
            return redirect(url_for("auth.login_page", next=request.path))
        if not is_admin(g.user):
            abort(404)
        if request.method == "POST" and not csrf_valid():
            abort(400)
        return view(*args, **kwargs)
    return wrapper


def _progress_summary(raw):
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return {
        "xp": data.get("xp", 0),
        "lessen": sum(1 for steps in data.get("lessen", {}).values() if len(steps) >= 4),
        "scenarios": len(data.get("scenarios", {})),
        "woorden": sum(1 for w in data.get("woorden", {}).values() if w.get("is_mastered")),
    }


@bp.after_request
def no_index(resp):
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.get("/")
@admin_required
def dashboard():
    return render_template("admin/dashboard.html", stats=db.admin_stats(),
                           messages=db.admin_messages(limit=5), section="dashboard")


@bp.get("/berichten")
@admin_required
def messages():
    return render_template("admin/messages.html", messages=db.admin_messages(), section="berichten")


@bp.post("/berichten/<int:message_id>/verwijderen")
@admin_required
def delete_message(message_id):
    if db.delete_message(message_id):
        current_app.logger.info("admin %s verwijderde bericht #%s", g.user["id"], message_id)
        flash(f"Bericht #{message_id} verwijderd.", "success")
    return redirect(url_for("admin.messages"))


@bp.get("/gebruikers")
@admin_required
def users():
    rows = [dict(r, summary=_progress_summary(r["progress"])) for r in db.admin_users()]
    return render_template("admin/users.html", users=rows, section="gebruikers")


@bp.post("/gebruikers/<int:user_id>/verwijderen")
@admin_required
def delete_user(user_id):
    if user_id == g.user["id"]:
        flash("Je kunt je eigen beheerdersaccount hier niet verwijderen.", "error")
    elif db.get_user(user_id) is not None:
        db.delete_user(user_id)
        current_app.logger.info("admin %s verwijderde gebruiker #%s", g.user["id"], user_id)
        flash(f"Gebruiker #{user_id} en de voortgang zijn verwijderd.", "success")
    return redirect(url_for("admin.users"))


def init_admin(app):
    path = "/" + app.config["ADMIN_PATH"].strip("/")
    app.register_blueprint(bp, url_prefix=path)

    @app.context_processor
    def inject_admin():
        return {"is_admin": is_admin(g.get("user"))}
