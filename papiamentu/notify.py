"""Optional e-mail notification for new contact messages (enabled when SMTP_HOST and NOTIFY_EMAIL are set)."""
import smtplib
import ssl
import threading
from email.message import EmailMessage


def notifications_enabled(config) -> bool:
    return bool(config.get("SMTP_HOST") and config.get("NOTIFY_EMAIL"))


def _send(config, msg: EmailMessage, logger):
    try:
        host, port = config["SMTP_HOST"], config["SMTP_PORT"]
        context = ssl.create_default_context()
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, context=context, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls(context=context)
        with server:
            if config.get("SMTP_USER"):
                server.login(config["SMTP_USER"], config["SMTP_PASSWORD"])
            server.send_message(msg)
    except Exception:
        logger.exception("Kon e-mailnotificatie voor contactbericht niet versturen")


def notify_new_message(app, message_id: int, name: str, email: str, subject: str, body: str):
    config = app.config
    if not notifications_enabled(config):
        return
    msg = EmailMessage()
    msg["Subject"] = f"[Papiamentu Pa Bo] {subject}"
    msg["From"] = config["SMTP_FROM"] or config["SMTP_USER"] or config["NOTIFY_EMAIL"]
    msg["To"] = config["NOTIFY_EMAIL"]
    if email:
        msg["Reply-To"] = email
    msg.set_content(
        f"Nieuw contactbericht #{message_id}\n\n"
        f"Naam: {name or '(niet opgegeven)'}\n"
        f"E-mail: {email or '(niet opgegeven)'}\n"
        f"Onderwerp: {subject}\n\n{body}\n"
    )
    # Send in the background so a slow mail server doesn't delay the visitor.
    threading.Thread(target=_send, args=(config, msg, app.logger), daemon=True).start()
