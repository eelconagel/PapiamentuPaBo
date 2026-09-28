# Papiamentu Pa Bo — Web

Flask version of the Papiamentu Pa Bo app: practical scenarios, word practice and structured lessons for learning Papiamentu (in Dutch).

- **Content** (26 scenarios, 40 lessons, 6 word lists, plus news reading practice) is JSON in `papiamentu/data/`, originally copied from the mobile app and extended since.
- **Progress** (name, XP, lessons, scenarios, words) is kept in the visitor's browser (`localStorage`), like the app kept it on-device. Visitors can export and import a backup under *Instellingen*.
- **Optional login** with Google, Microsoft, Apple or Facebook. Logged-in visitors get their progress stored on the server and synced across devices. Without keys configured, the site works exactly the same, just without login buttons.
- **Contact messages** are stored in SQLite on the `/data` volume, optionally with an e-mail notification.

## Run on the server with Docker

```bash
git clone <your-repo-url> papiamentu-pa-bo
cd papiamentu-pa-bo
cp .env.example .env        # set SECRET_KEY; see the comments for the other options
docker compose up -d --build
```

The container listens on `127.0.0.1:8000`, so it is only reachable from the server itself. A reverse proxy on the same server handles HTTPS and forwards to it. With [Caddy](https://caddyserver.com) that is the whole config (certificates are automatic):

```
papiamentu.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8000
}
```

With nginx, forward the usual headers:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
}
```

Settings in `.env` that matter behind a proxy:

| Setting | Default | Meaning |
|---|---|---|
| `PROXY_COUNT` | `1` | Proxies in front of the site. Used to find the visitor's real IP (rate limit) and to detect HTTPS. Set `0` if nothing is in front. |
| `COOKIE_SECURE` | `1` | Only send the session cookie over HTTPS. Set `0` when testing over plain http. |
| `BIND_ADDRESS` | `127.0.0.1` | Set `0.0.0.0` only if the proxy runs on another machine. |

If your proxy runs in its own Docker container instead of on the host, put both on a shared Docker network and point it at `papiamentu-pa-bo:8000`.

### Update

```bash
git pull
docker compose up -d --build
```

### Contact messages

```bash
docker compose exec web flask messages
```

To get an e-mail for each new message, fill in the `SMTP_*` settings and `NOTIFY_EMAIL` in `.env` and restart (`docker compose up -d`). The mail's Reply-To is the visitor's address, if they gave one.

The form is protected by a CSRF token, a honeypot field and rate limits: `CONTACT_LIMIT_PER_IP_HOUR` (default 5) per visitor and `CONTACT_LIMIT_PER_DAY` (default 100) in total. Only a keyed hash of the visitor's IP is stored, never the IP itself.

### Login (Google, Microsoft, Apple, Facebook)

Each provider is optional: its button only appears once all of its keys are in `.env`. Set `PUBLIC_BASE_URL=https://your-domain` first; every provider needs the callback URL

```
https://your-domain/auth/<provider>/callback      e.g. https://your-domain/auth/google/callback
```

After editing `.env`, run `docker compose up -d` to apply.

**Google** (free, ~5 minutes)
1. Go to <https://console.cloud.google.com/>, create a project.
2. *APIs & Services → OAuth consent screen*: type *External*, fill in app name, support e-mail, and your privacy page (`https://your-domain/privacy`). Scopes: `openid`, `email`, `profile` only (no review needed). Publish the app.
3. *Credentials → Create credentials → OAuth client ID*, type *Web application*, authorised redirect URI `https://your-domain/auth/google/callback`.
4. Put the client ID and secret in `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.

**Microsoft** (free; covers Outlook/Hotmail/Live and work/school accounts)
1. Go to <https://portal.azure.com/> → *Microsoft Entra ID → App registrations → New registration*.
2. Supported account types: *Accounts in any organizational directory and personal Microsoft accounts*. Redirect URI: platform *Web*, `https://your-domain/auth/microsoft/callback`.
3. *Certificates & secrets → New client secret*. Note: it expires (max 24 months); put a reminder in your calendar.
4. `MICROSOFT_CLIENT_ID` = *Application (client) ID*, `MICROSOFT_CLIENT_SECRET` = the secret's *Value*.

**Facebook** (free)
1. Go to <https://developers.facebook.com/apps/> → *Create app* → use case *Authenticate and request data from users with Facebook Login*.
2. *Facebook Login → Settings*: add `https://your-domain/auth/facebook/callback` under *Valid OAuth Redirect URIs*.
3. *App settings → Basic*: fill in privacy policy URL (`https://your-domain/privacy`) and *User data deletion* → instructions URL `https://your-domain/privacy#verwijderen`. Switch the app to *Live*.
4. `FACEBOOK_CLIENT_ID` = App ID, `FACEBOOK_CLIENT_SECRET` = App secret.

**Apple** (needs a paid Apple Developer account, $99/year)
1. <https://developer.apple.com/account/resources/identifiers>: create an *App ID* with *Sign in with Apple* enabled, then a *Services ID* (this is `APPLE_CLIENT_ID`, e.g. `com.yourname.papiamentu.web`). Configure it with your domain and return URL `https://your-domain/auth/apple/callback`.
2. *Keys → +*: enable *Sign in with Apple*, download the `.p8` file. Note the *Key ID* (`APPLE_KEY_ID`) and your *Team ID* (top right, `APPLE_TEAM_ID`).
3. `APPLE_PRIVATE_KEY` = contents of the `.p8` file on one line, with line breaks written as `\n`:
   `python3 -c "print(open('AuthKey_XXXX.p8').read().replace('\n','\\\\n'))"`

How accounts work: an account is tied to the provider's user id, not the e-mail address. Someone who is logged in can link extra providers under *Instellingen*. On login, progress made anonymously in that browser is merged into the account. On logout, the browser's copy is cleared (it stays safe on the server). Visitors can delete their account themselves under *Instellingen*.

### Admin panel

A small admin panel at `ADMIN_PATH` (default `/dit/is/admin/panel/`) shows sign-up stats, the contact messages and the accounts with their progress, and lets you delete messages and accounts.

Only one person gets in: the logged-in user whose **Google** login has the verified e-mail address `ADMIN_EMAIL`. Set it in `.env` and restart (`docker compose up -d`); leave it empty to switch the panel off. Google login must be configured. Not logged in → you're sent to the login page and back; logged in as anyone else → a plain 404. The admin sees a *Beheer* link under *Instellingen*.

### Backups

The database lives in the Docker volume `papiamentu-data`, so it survives rebuilds, but not a lost disk. `scripts/backup.sh` copies it out of the running container into `./backups/` and keeps 30 days. Run it daily from cron:

```
0 3 * * * cd /path/to/papiamentu-pa-bo && sh scripts/backup.sh >> backups/backup.log 2>&1
```

Copy `backups/` somewhere off the server as well. To restore: `docker compose cp backups/<file>.sqlite3 web:/data/papiamentu.sqlite3 && docker compose restart`.

### Security

- Content-Security-Policy with a per-request nonce (no external scripts, no `unsafe-inline` for scripts), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, and HSTS when served over HTTPS.
- Runs as a non-root user under gunicorn, with a health check at `/healthz`.
- CSS and JS URLs carry a content hash (`?v=…`) and are cached for a year; a new deploy changes the hash, so browsers pick up changes immediately.

## Local development

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Windows (use .venv/bin/ on Linux/macOS)
.venv/Scripts/flask --app wsgi.py run --debug --port 5057
.venv/Scripts/python -m pytest
```

Locally the database goes in `instance/` (ignored by git). `flask run` reads `.env` (via python-dotenv), just like Docker does.

### Testing login locally

Google and Microsoft accept `http://localhost` redirect URIs, so no domain or HTTPS is needed while developing. Use a separate OAuth client for development, so production keys never live on your laptop.

1. In `.env`: `COOKIE_SECURE=0`, `PROXY_COUNT=0`, leave `PUBLIC_BASE_URL` empty, and fill in `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` of the development client.
2. In the Google Cloud Console, add these authorised redirect URIs to that client:
   - `http://localhost:8765/auth/google/callback` (local Docker, `docker compose up -d --build`)
   - `http://localhost:5057/auth/google/callback` (`flask run --port 5057`; port 5000 is often taken on Windows/macOS)
3. On the OAuth consent screen you can leave the app in *Testing* and add your own Google account as a test user.
4. Always open the site as `http://localhost:…`, not `127.0.0.1`: the login cookie belongs to the host name, and Google sends you back to the exact URI above.

Facebook and Apple don't allow plain-http redirects; test those on a server with HTTPS.

## Layout

```
papiamentu/
  __init__.py        routes and config (create_app)
  content.py         loads the JSON content
  db.py              contact-message storage, backups
  auth.py            optional OAuth login + progress sync API
  admin.py           mini admin panel (one Google account, set via ADMIN_EMAIL)
  sync.py            validating and merging progress between devices
  security.py        proxy handling, CSRF, security headers, static versioning
  notify.py          optional e-mail notification
  richtext.py        turns the plain lesson texts into paragraphs, lists and headings
  data/              scenarios, lessons, word lists
  templates/         Jinja pages
  static/js/store.js browser-side progress store
  static/js/quiz.js  shared quiz component
tests/               pytest suite
scripts/backup.sh    database backup
wsgi.py              gunicorn entry point
Dockerfile, docker-compose.yml
```

To add or edit content, change the JSON files in `papiamentu/data/`. New `scenario-XXX.json` and `les-XXX.json` files are picked up automatically; new scenarios also need an entry in `papiamentuPaBoScenarios.json` to show in the list. Run the tests afterwards: they check that every page renders and that the quiz data is consistent.
