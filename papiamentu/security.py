"""Proxy handling, CSRF tokens, security headers and cache-busted static URLs."""
import hashlib
import hmac
import os
import secrets
from functools import lru_cache
from pathlib import Path

from flask import g, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

ONE_YEAR = 365 * 24 * 3600


def init_security(app):
    # Trust X-Forwarded-* from this many proxies (Caddy/nginx in front = 1).
    proxy_count = app.config["PROXY_COUNT"]
    if proxy_count > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_count, x_proto=proxy_count, x_host=proxy_count)

    # Static URLs carry a content hash (?v=...), so browsers may cache them for a year.
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = ONE_YEAR
    static_root = Path(app.static_folder)

    @lru_cache(maxsize=256)
    def _hash(filename, mtime):
        return hashlib.sha256((static_root / filename).read_bytes()).hexdigest()[:10]

    @app.url_defaults
    def static_version(endpoint, values):
        if endpoint == "static" and "filename" in values:
            path = static_root / values["filename"]
            if path.is_file():
                values["v"] = _hash(values["filename"], os.stat(path).st_mtime_ns)

    @app.before_request
    def make_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def inject_security():
        return {"csp_nonce": g.get("csp_nonce", ""), "csrf_token": csrf_token}

    @app.after_request
    def security_headers(resp):
        nonce = g.get("csp_nonce", "")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "object-src 'none'",
        )
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), interest-cohort=()")
        resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.is_secure:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp


def csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def csrf_valid() -> bool:
    expected = session.get("_csrf")
    given = request.form.get("csrf_token", "")
    return bool(expected) and hmac.compare_digest(expected, given)


def client_fingerprint(secret_key: str) -> str:
    """Keyed hash of the client IP, so rate limiting works without storing raw IPs."""
    ip = request.remote_addr or "unknown"
    return hmac.new(secret_key.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]
