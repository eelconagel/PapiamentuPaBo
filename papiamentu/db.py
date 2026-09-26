"""Tiny SQLite store for contact-form messages. Lives on the /data volume in Docker."""
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import current_app, g


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    with app.app_context():
        db = get_db()
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS contact_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                subject TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                ip_hash TEXT
            )
            """
        )
        # Databases created before rate limiting existed lack ip_hash.
        columns = {row["name"] for row in db.execute("PRAGMA table_info(contact_messages)")}
        if "ip_hash" not in columns:
            db.execute("ALTER TABLE contact_messages ADD COLUMN ip_hash TEXT")
        db.execute("CREATE INDEX IF NOT EXISTS idx_contact_created ON contact_messages (created_at)")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );
            CREATE TABLE IF NOT EXISTS identities (
                provider TEXT NOT NULL,
                subject TEXT NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                email TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (provider, subject)
            );
            CREATE INDEX IF NOT EXISTS idx_identities_user ON identities (user_id);
            CREATE TABLE IF NOT EXISTS progress (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                data TEXT NOT NULL,
                rev INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        db.commit()
        close_db()
    app.teardown_appcontext(close_db)


def save_contact_message(name: str, email: str, subject: str, message: str, ip_hash: str) -> int:
    db = get_db()
    cur = db.execute(
        "INSERT INTO contact_messages (name, email, subject, message, created_at, ip_hash) VALUES (?, ?, ?, ?, ?, ?)",
        (name, email, subject, message, _iso(_now()), ip_hash),
    )
    db.commit()
    return cur.lastrowid


def count_messages_since(hours: int, ip_hash: str | None = None) -> int:
    since = _iso(_now() - timedelta(hours=hours))
    if ip_hash is None:
        row = get_db().execute("SELECT COUNT(*) FROM contact_messages WHERE created_at >= ?", (since,)).fetchone()
    else:
        row = get_db().execute(
            "SELECT COUNT(*) FROM contact_messages WHERE created_at >= ? AND ip_hash = ?", (since, ip_hash)
        ).fetchone()
    return row[0]


# ---------- accounts ----------

def get_user(user_id):
    if user_id is None:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_identities(user_id) -> list:
    return get_db().execute(
        "SELECT provider, email FROM identities WHERE user_id = ? ORDER BY created_at", (user_id,)
    ).fetchall()


def find_identity(provider: str, subject: str):
    return get_db().execute(
        "SELECT * FROM identities WHERE provider = ? AND subject = ?", (provider, subject)
    ).fetchone()


def create_user(name: str, email: str) -> int:
    now = _iso(_now())
    cur = get_db().execute(
        "INSERT INTO users (name, email, created_at, last_login_at) VALUES (?, ?, ?, ?)", (name, email, now, now)
    )
    return cur.lastrowid


def add_identity(user_id: int, provider: str, subject: str, email: str):
    get_db().execute(
        "INSERT INTO identities (provider, subject, user_id, email, created_at) VALUES (?, ?, ?, ?, ?)",
        (provider, subject, user_id, email, _iso(_now())),
    )


def touch_login(user_id: int, provider: str, subject: str, email: str):
    db = get_db()
    db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_iso(_now()), user_id))
    if email:
        db.execute("UPDATE identities SET email = ? WHERE provider = ? AND subject = ?", (email, provider, subject))
        db.execute("UPDATE users SET email = ? WHERE id = ? AND (email IS NULL OR email = '')", (email, user_id))


def delete_user(user_id: int):
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()


def get_progress(user_id: int):
    return get_db().execute("SELECT data, rev FROM progress WHERE user_id = ?", (user_id,)).fetchone()


def put_progress(user_id: int, data: str, rev: int):
    get_db().execute(
        """INSERT INTO progress (user_id, data, rev, updated_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, rev = excluded.rev,
                                              updated_at = excluded.updated_at""",
        (user_id, data, rev, _iso(_now())),
    )


def delete_progress(user_id: int):
    db = get_db()
    db.execute("DELETE FROM progress WHERE user_id = ?", (user_id,))
    db.commit()


# ---------- admin ----------

def has_google_email(user_id: int, email: str) -> bool:
    row = get_db().execute(
        "SELECT 1 FROM identities WHERE user_id = ? AND provider = 'google' AND lower(email) = lower(?)",
        (user_id, email),
    ).fetchone()
    return row is not None


def admin_stats() -> dict:
    db = get_db()
    week = _iso(_now() - timedelta(days=7))
    one = lambda sql, *args: db.execute(sql, args).fetchone()[0]
    return {
        "users": one("SELECT COUNT(*) FROM users"),
        "users_new_week": one("SELECT COUNT(*) FROM users WHERE created_at >= ?", week),
        "users_active_week": one("SELECT COUNT(*) FROM users WHERE last_login_at >= ?", week),
        "synced": one("SELECT COUNT(*) FROM progress"),
        "synced_week": one("SELECT COUNT(*) FROM progress WHERE updated_at >= ?", week),
        "messages": one("SELECT COUNT(*) FROM contact_messages"),
        "messages_week": one("SELECT COUNT(*) FROM contact_messages WHERE created_at >= ?", week),
        "providers": db.execute(
            "SELECT provider, COUNT(*) AS n FROM identities GROUP BY provider ORDER BY n DESC"
        ).fetchall(),
    }


def admin_users(limit: int = 500) -> list:
    return get_db().execute(
        """SELECT u.id, u.name, u.email, u.created_at, u.last_login_at,
                  (SELECT group_concat(provider, ',') FROM identities i WHERE i.user_id = u.id) AS providers,
                  p.data AS progress, p.updated_at AS progress_at
           FROM users u LEFT JOIN progress p ON p.user_id = u.id
           ORDER BY u.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def admin_messages(limit: int = 500) -> list:
    return get_db().execute(
        "SELECT id, name, email, subject, message, created_at FROM contact_messages ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def delete_message(message_id: int) -> bool:
    db = get_db()
    cur = db.execute("DELETE FROM contact_messages WHERE id = ?", (message_id,))
    db.commit()
    return cur.rowcount == 1


def backup_to(path: str):
    """Consistent copy of the live database, safe while the site is running."""
    dest = sqlite3.connect(path)
    try:
        get_db().backup(dest)
    finally:
        dest.close()
