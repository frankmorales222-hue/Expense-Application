"""Send an email the way the company set up: Microsoft 365 sign-in (Graph) or an SMTP server."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import EmailSettings
from . import mailer, microsoft
from .secretbox import SecretUnavailable, decrypt, encrypt


class NotConfigured(RuntimeError):
    pass


@dataclass
class OutMail:
    to: list[str]
    subject: str
    text: str
    html: str | None = None
    cc: list[str] = field(default_factory=list)
    attachment: tuple[str, bytes, str] | None = None


def settings_row(db: Session) -> EmailSettings | None:
    return db.scalar(select(EmailSettings))


def client_id_for(row: EmailSettings | None) -> str:
    return ((row.oauth_client_id if row is not None else None) or get_settings().MS_CLIENT_ID or "").strip()


def is_ready(row: EmailSettings | None) -> bool:
    if row is None:
        return False
    return bool(row.oauth_refresh_encrypted) if row.provider == "microsoft" else bool(row.smtp_host)


def from_label(row: EmailSettings | None) -> str | None:
    if row is None:
        return None
    if row.provider == "microsoft":
        return f"{row.oauth_account or row.from_email} (Microsoft 365)"
    return f"{row.from_name} <{row.from_email}>" if row.from_name else row.from_email


def send(db: Session, mail: OutMail) -> None:
    """Raises NotConfigured, mailer.MailError (explained) or SecretUnavailable. The caller commits, so a
    refreshed Microsoft sign-in is kept."""
    row = settings_row(db)
    if not is_ready(row):
        raise NotConfigured("Set up email in Settings > Email first")
    bcc = [row.from_email] if row.copy_me else []
    if row.provider == "microsoft":
        if not row.oauth_refresh_encrypted:
            raise mailer.MailError("Microsoft 365 isn't connected. Connect it again in Settings > Email.")
        client_id = client_id_for(row)
        if not client_id:
            raise mailer.MailError("The Microsoft app (client) ID is missing. Add it in Settings > Email.")
        refresh = decrypt(row.oauth_refresh_encrypted)
        tenant = row.oauth_tenant or get_settings().MS_TENANT or "organizations"
        token, new_refresh = microsoft.access_token(client_id, tenant, refresh)
        if new_refresh != refresh:
            row.oauth_refresh_encrypted = encrypt(new_refresh)
        microsoft.send_graph(token, mail.to, mail.subject, mail.html or _plain_html(mail.text), cc=mail.cc, bcc=bcc,
                             reply_to=row.reply_to, attachment=mail.attachment)
        return
    password = decrypt(row.password_encrypted) if row.password_encrypted else None
    cfg = mailer.SmtpConfig(host=row.smtp_host, port=row.smtp_port, security=row.security, username=row.username,
                            password=password, from_email=row.from_email, from_name=row.from_name,
                            reply_to=row.reply_to)
    msg = mailer.build_message(cfg, mail.to, mail.subject, mail.text, mail.html, cc=mail.cc, bcc=bcc,
                               attachment=mail.attachment)
    mailer.send(cfg, msg)


def _plain_html(text: str) -> str:
    import html

    return "<div style=\"font-family:Segoe UI,Arial,sans-serif;font-size:14px\">" + \
        html.escape(text).replace("\n", "<br>") + "</div>"


__all__ = ["NotConfigured", "OutMail", "SecretUnavailable", "client_id_for", "from_label", "is_ready", "send", "settings_row"]
