"""Sending email through the company's own mail server (SMTP).

Works with Microsoft 365 (smtp.office365.com, port 587, STARTTLS; SMTP AUTH must be allowed for the
mailbox), Gmail / Google Workspace (smtp.gmail.com, port 587, STARTTLS, with an app password) and any
other SMTP server.
"""

from __future__ import annotations

import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

TIMEOUT = 30


@dataclass
class SmtpConfig:
    host: str
    port: int
    security: str  # starttls | ssl | none
    username: str | None
    password: str | None
    from_email: str
    from_name: str | None = None
    reply_to: str | None = None


class MailError(RuntimeError):
    """A sending problem explained in plain words."""


def build_message(cfg: SmtpConfig, to: list[str], subject: str, text: str, html: str | None = None,
                  cc: list[str] | None = None, bcc: list[str] | None = None,
                  attachment: tuple[str, bytes, str] | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.from_name or "", cfg.from_email))
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if cfg.reply_to:
        msg["Reply-To"] = cfg.reply_to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=cfg.from_email.rsplit("@", 1)[-1] or None)
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    if attachment:
        name, data, mime = attachment
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    # Bcc goes in the envelope only, never in the headers.
    msg._fm_bcc = list(bcc or [])  # type: ignore[attr-defined]
    return msg


def _connect(cfg: SmtpConfig) -> smtplib.SMTP:
    """Separate so tests can replace it with a fake server."""
    context = ssl.create_default_context()
    if cfg.security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=TIMEOUT, context=context)
    else:
        server = smtplib.SMTP(cfg.host, cfg.port, timeout=TIMEOUT)
        server.ehlo()
        if cfg.security == "starttls":
            server.starttls(context=context)
            server.ehlo()
    return server


def send(cfg: SmtpConfig, msg: EmailMessage) -> None:
    recipients = [a.strip() for field in ("To", "Cc") for a in (msg.get(field) or "").split(",") if a.strip()]
    recipients += getattr(msg, "_fm_bcc", [])
    try:
        server = _connect(cfg)
        try:
            if cfg.username:
                server.login(cfg.username, cfg.password or "")
            server.send_message(msg, from_addr=cfg.from_email, to_addrs=recipients)
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                pass
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError("The mail server didn't accept the username or password. For Gmail use an app password; "
                        "for Microsoft 365 make sure SMTP AUTH is turned on for this mailbox.") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailError("The mail server refused the recipient address: "
                        + ", ".join(exc.recipients.keys())) from exc
    except smtplib.SMTPSenderRefused as exc:
        raise MailError(f"The mail server won't send as {cfg.from_email}. Use the address of the mailbox you sign "
                        "in with, or one it's allowed to send as.") from exc
    except smtplib.SMTPNotSupportedError as exc:
        raise MailError("The mail server doesn't support that security setting. Try STARTTLS on port 587 "
                        "or SSL on port 465.") from exc
    except ssl.SSLError as exc:
        raise MailError(f"Secure connection failed ({exc.reason or exc}). Check the port and security setting: "
                        "587 uses STARTTLS, 465 uses SSL.") from exc
    except (socket.gaierror, ConnectionRefusedError, TimeoutError, socket.timeout, OSError) as exc:
        if isinstance(exc, smtplib.SMTPException):
            raise MailError(f"The mail server reported a problem: {exc}") from exc
        raise MailError(f"Couldn't reach {cfg.host}:{cfg.port} ({exc.__class__.__name__}). Check the server name "
                        "and port, and that this computer can reach the internet.") from exc
    except smtplib.SMTPException as exc:
        raise MailError(f"The mail server reported a problem: {exc}") from exc
