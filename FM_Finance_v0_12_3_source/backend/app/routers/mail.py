"""Outgoing email settings for sending invoices: Microsoft 365 sign-in (v0.7.1) or an SMTP server."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..invoicing import mailer, microsoft, outbox
from ..invoicing.secretbox import SecretUnavailable, encrypt
from ..models import EmailSettings, User
from ..schemas import (
    EmailSettingsIn, EmailSettingsOut, MicrosoftPollIn, MicrosoftPollOut, MicrosoftStartIn, MicrosoftStartOut,
    TestEmailIn,
)
from ..security import require_roles
from .util import current_company

router = APIRouter(prefix="/api/email-settings", tags=["email"])
OWNER = require_roles("admin")


def _out(row: EmailSettings | None) -> EmailSettingsOut:
    env = bool(get_settings().MS_CLIENT_ID.strip())
    saved = row.oauth_client_id if row is not None else None
    common = {"ms_client_id": saved, "ms_client_id_in_env": env, "microsoft_ready": bool(saved or env),
              "ms_tenant": row.oauth_tenant if row is not None else None}
    if row is None or (row.provider == "microsoft" and not row.oauth_refresh_encrypted) \
            or (row.provider == "smtp" and not row.smtp_host):
        return EmailSettingsOut(configured=False, **common)
    if row.provider == "microsoft":
        return EmailSettingsOut(configured=True, provider="microsoft", oauth_account=row.oauth_account,
                                from_email=row.from_email, from_name=row.from_name, reply_to=row.reply_to,
                                copy_me=row.copy_me, **common)
    return EmailSettingsOut(configured=True, provider="smtp", smtp_host=row.smtp_host, smtp_port=row.smtp_port,
                            security=row.security, username=row.username, has_password=bool(row.password_encrypted),
                            from_email=row.from_email, from_name=row.from_name, reply_to=row.reply_to,
                            copy_me=row.copy_me, **common)


@router.get("", response_model=EmailSettingsOut)
def get_email_settings(db: Session = Depends(get_db),
                       _: User = Depends(require_roles("admin", "approver"))) -> EmailSettingsOut:
    return _out(outbox.settings_row(db))


def _row(db: Session) -> EmailSettings:
    row = outbox.settings_row(db)
    if row is None:
        row = EmailSettings(company_id=current_company(db).id, smtp_host="", smtp_port=587, security="starttls",
                            from_email="")
        db.add(row)
    return row


@router.put("", response_model=EmailSettingsOut)
def save_smtp(payload: EmailSettingsIn, db: Session = Depends(get_db), user: User = Depends(OWNER)) -> EmailSettingsOut:
    """Use an SMTP server with a password (switches away from Microsoft 365 sign-in)."""
    company = current_company(db)
    row = _row(db)
    was_microsoft = row.provider == "microsoft"
    for field in ("smtp_host", "smtp_port", "security", "username", "from_email", "from_name", "reply_to", "copy_me"):
        setattr(row, field, getattr(payload, field))
    row.provider = "smtp"
    row.oauth_refresh_encrypted, row.oauth_account = None, None
    if was_microsoft:
        row.password_encrypted = None
    if payload.password is not None:
        try:
            row.password_encrypted = encrypt(payload.password) if payload.password else None
        except SecretUnavailable as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    audit.record(db, entity_type="company", entity_id=company.id, action="email_settings_saved", user_id=user.id,
                 changes={"provider": "smtp", "host": payload.smtp_host, "port": payload.smtp_port,
                          "from": payload.from_email, "password_changed": payload.password is not None})
    db.commit()
    return _out(row)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def remove_settings(db: Session = Depends(get_db), user: User = Depends(OWNER)) -> Response:
    row = outbox.settings_row(db)
    if row is not None:
        db.delete(row)
        audit.record(db, entity_type="company", entity_id=current_company(db).id, action="email_settings_removed",
                     user_id=user.id)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- Microsoft 365
@router.post("/microsoft/start", response_model=MicrosoftStartOut)
def microsoft_start(payload: MicrosoftStartIn, db: Session = Depends(get_db),
                    _: User = Depends(OWNER)) -> MicrosoftStartOut:
    """Step 1: get a code. The person enters it at microsoft.com/devicelogin and signs in (with MFA)."""
    company = current_company(db)
    row = outbox.settings_row(db)
    client_id = payload.client_id or outbox.client_id_for(row)
    if not client_id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Enter the Application (client) ID of your Microsoft app registration first")
    try:
        tenant = payload.tenant_id or (row.oauth_tenant if row is not None else None) \
            or get_settings().MS_TENANT or "organizations"
        flow = microsoft.start_sign_in(company.id, client_id, tenant)
    except mailer.MailError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return MicrosoftStartOut(**flow)


@router.post("/microsoft/poll", response_model=MicrosoftPollOut)
def microsoft_poll(payload: MicrosoftPollIn, db: Session = Depends(get_db),
                   user: User = Depends(OWNER)) -> MicrosoftPollOut:
    """Step 2: called every few seconds until the sign-in finishes."""
    company = current_company(db)
    try:
        signed = microsoft.poll_sign_in(company.id, payload.flow_id)
    except mailer.MailError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if signed is None:
        return MicrosoftPollOut(status="pending")
    row = _row(db)
    try:
        row.oauth_refresh_encrypted = encrypt(signed.refresh_token)
    except SecretUnavailable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    env_id = get_settings().MS_CLIENT_ID.strip().lower()
    row.oauth_client_id = None if signed.client_id == env_id else signed.client_id
    env_tenant = (get_settings().MS_TENANT or "organizations").lower()
    row.oauth_tenant = None if signed.tenant == env_tenant else signed.tenant
    row.provider, row.oauth_account = "microsoft", signed.email
    row.smtp_host, row.smtp_port, row.security = "graph.microsoft.com", 443, "ssl"
    row.username, row.password_encrypted = None, None
    row.from_email = signed.email
    row.from_name = row.from_name or signed.display_name
    audit.record(db, entity_type="company", entity_id=company.id, action="email_microsoft_connected", user_id=user.id,
                 changes={"account": signed.email})
    db.commit()
    return MicrosoftPollOut(status="connected", settings=_out(row))


@router.post("/microsoft/disconnect", response_model=EmailSettingsOut)
def microsoft_disconnect(db: Session = Depends(get_db), user: User = Depends(OWNER)) -> EmailSettingsOut:
    """Forget the Microsoft sign-in but keep the app ID, so connecting again is one click."""
    row = outbox.settings_row(db)
    if row is not None and row.provider == "microsoft":
        row.oauth_refresh_encrypted, row.oauth_account = None, None
        audit.record(db, entity_type="company", entity_id=current_company(db).id, action="email_microsoft_disconnected",
                     user_id=user.id)
        db.commit()
    return _out(row)


@router.put("/options", response_model=EmailSettingsOut)
def save_options(payload: dict, db: Session = Depends(get_db), _: User = Depends(OWNER)) -> EmailSettingsOut:
    """Reply-to and copy-me for a connected Microsoft 365 mailbox."""
    from ..schemas import EMAIL_RE

    row = outbox.settings_row(db)
    if row is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Set up email first")
    reply = (payload.get("reply_to") or "").strip() or None
    if reply and not EMAIL_RE.match(reply):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter a valid reply-to address")
    row.reply_to = reply
    row.copy_me = bool(payload.get("copy_me"))
    db.commit()
    return _out(row)


@router.post("/test")
def send_test(payload: TestEmailIn, db: Session = Depends(get_db), _: User = Depends(OWNER)) -> dict:
    company = current_company(db)
    mail = outbox.OutMail(
        to=[payload.to], subject=f"Test email from F&M Finance ({company.name})",
        text=f"This is a test from F&M Finance.\n\nIf you're reading it, {company.name} can email invoices.")
    try:
        outbox.send(db, mail)
    except outbox.NotConfigured as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Save the email settings first") from exc
    except SecretUnavailable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except mailer.MailError as exc:
        db.commit()  # keep a refreshed Microsoft sign-in even when the send fails
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    db.commit()
    return {"sent": True, "to": payload.to}
