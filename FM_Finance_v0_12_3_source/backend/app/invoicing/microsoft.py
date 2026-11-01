"""Microsoft 365: sign in with the device-code flow (works with MFA) and send mail through Microsoft Graph.

The person signs in on Microsoft's own page (microsoft.com/devicelogin) with their password and MFA;
this app never sees the password. We keep only an encrypted refresh token, and send with
POST /me/sendMail, so sent invoices also appear in the mailbox's Sent Items.

Needs an Entra app registration (multitenant, "Allow public client flows" on, delegated Graph permission
Mail.Send). Its Application (client) ID goes in .env (MS_CLIENT_ID) or Settings > Email.
"""

from __future__ import annotations

import base64
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass

from .mailer import MailError

LOGIN = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = "offline_access https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/User.Read"
TIMEOUT = 30


def _http(method: str, url: str, form: dict | None = None, body: dict | None = None,
          token: str | None = None) -> tuple[int, dict]:
    """One HTTP call; returns (status, JSON body or {}). Separate so tests can replace it."""
    headers = {"Accept": "application/json"}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - fixed Microsoft URLs
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else {}
        except ValueError:
            return exc.code, {"error": "http_error", "error_description": raw[:300].decode("utf-8", "replace")}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MailError("Couldn't reach Microsoft. Check that this computer is online and that the firewall "
                        f"allows login.microsoftonline.com and graph.microsoft.com ({exc.__class__.__name__}).") from exc


def explain(payload: dict) -> str:
    """Turn a Microsoft identity error into something a person can act on."""
    desc = str(payload.get("error_description") or payload.get("error") or "")
    code = desc.split(":", 1)[0].strip() if desc.startswith("AADSTS") else ""
    known = {
        "AADSTS700016": "Microsoft doesn't recognize the app (client) ID. Check it, and that the app registration "
                        "allows accounts in any organizational directory (multitenant).",
        "AADSTS7000218": "In the Entra app registration, open Authentication and turn on \"Allow public client "
                         "flows\", then try again.",
        "AADSTS65001": "Your Microsoft 365 administrator needs to approve the app first (Entra admin center > "
                       "Enterprise applications > the app > Permissions > Grant admin consent).",
        "AADSTS90094": "Your Microsoft 365 administrator needs to approve the app first (admin consent).",
        "AADSTS50194": "This Microsoft app is single-tenant. Enter your Directory (tenant) ID from the app's "
                       "Overview page next to the app ID, then connect again.",
        "AADSTS90002": "Microsoft doesn't know that Directory (tenant) ID. Copy it again from the app's Overview page.",
        "AADSTS50020": "That account is from a different Microsoft 365 organization than this app. Sign in with an "
                       "account from the organization that owns the app.",
        "AADSTS53003": "A Conditional Access policy in your Microsoft 365 tenant blocked the sign-in.",
        "AADSTS50076": "Microsoft wants MFA for this sign-in; start the connection again and complete MFA.",
        "AADSTS70043": "The Microsoft sign-in has expired. Connect Microsoft 365 again in Settings > Email.",
        "AADSTS700082": "The Microsoft sign-in has expired. Connect Microsoft 365 again in Settings > Email.",
        "AADSTS50173": "Your Microsoft password changed, so the sign-in expired. Connect Microsoft 365 again.",
    }
    if code in known:
        return known[code]
    if payload.get("error") == "invalid_grant":
        return "The Microsoft sign-in is no longer valid. Connect Microsoft 365 again in Settings > Email."
    return f"Microsoft said: {desc.splitlines()[0][:300]}" if desc else "Microsoft sign-in failed."


# ---------------------------------------------------------------- device-code sign-in
@dataclass
class _Flow:
    company_id: uuid.UUID
    client_id: str
    tenant: str
    device_code: str
    interval: int
    expires_at: float


_flows: dict[str, _Flow] = {}
_lock = threading.Lock()


def start_sign_in(company_id: uuid.UUID, client_id: str, tenant: str) -> dict:
    status, data = _http("POST", f"{LOGIN}/{tenant}/oauth2/v2.0/devicecode",
                         form={"client_id": client_id, "scope": SCOPES})
    if status != 200 or "device_code" not in data:
        raise MailError(explain(data))
    flow_id = secrets.token_urlsafe(16)
    with _lock:
        now = time.time()
        for k in [k for k, f in _flows.items() if f.expires_at < now]:
            _flows.pop(k, None)
        _flows[flow_id] = _Flow(company_id, client_id, tenant, data["device_code"], int(data.get("interval", 5)),
                                now + int(data.get("expires_in", 900)))
    return {"flow_id": flow_id, "user_code": data["user_code"],
            "verification_uri": data.get("verification_uri", "https://microsoft.com/devicelogin"),
            "interval": int(data.get("interval", 5)), "expires_in": int(data.get("expires_in", 900))}


@dataclass
class SignedIn:
    client_id: str
    tenant: str
    refresh_token: str
    email: str
    display_name: str | None


def poll_sign_in(company_id: uuid.UUID, flow_id: str) -> SignedIn | None:
    """None while the person hasn't finished signing in yet."""
    with _lock:
        flow = _flows.get(flow_id)
    if flow is None or flow.company_id != company_id:
        raise MailError("This sign-in has expired. Click Connect Microsoft 365 again.")
    if time.time() > flow.expires_at:
        _flows.pop(flow_id, None)
        raise MailError("The code expired before sign-in finished. Click Connect Microsoft 365 again.")
    status, data = _http("POST", f"{LOGIN}/{flow.tenant}/oauth2/v2.0/token", form={
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code", "client_id": flow.client_id,
        "device_code": flow.device_code})
    if status != 200:
        err = data.get("error")
        if err in ("authorization_pending", "slow_down"):
            return None
        _flows.pop(flow_id, None)
        if err == "authorization_declined":
            raise MailError("The sign-in was cancelled on the Microsoft page.")
        if err == "expired_token":
            raise MailError("The code expired before sign-in finished. Click Connect Microsoft 365 again.")
        raise MailError(explain(data))
    _flows.pop(flow_id, None)
    refresh = data.get("refresh_token")
    if not refresh:
        raise MailError("Microsoft didn't allow staying signed in (offline_access). Ask your administrator to "
                        "allow the app's permissions.")
    status, me = _http("GET", f"{GRAPH}/me?$select=displayName,mail,userPrincipalName", token=data["access_token"])
    if status != 200:
        raise MailError("Signed in, but couldn't read the mailbox address from Microsoft Graph.")
    email = me.get("mail") or me.get("userPrincipalName") or ""
    return SignedIn(client_id=flow.client_id, tenant=flow.tenant, refresh_token=refresh, email=email, display_name=me.get("displayName"))


# ---------------------------------------------------------------- sending
def access_token(client_id: str, tenant: str, refresh_token: str) -> tuple[str, str]:
    """A fresh access token, and the (possibly rotated) refresh token to keep."""
    status, data = _http("POST", f"{LOGIN}/{tenant}/oauth2/v2.0/token", form={
        "grant_type": "refresh_token", "client_id": client_id, "refresh_token": refresh_token, "scope": SCOPES})
    if status != 200 or "access_token" not in data:
        raise MailError(explain(data))
    return data["access_token"], data.get("refresh_token") or refresh_token


def _recipients(addresses: list[str]) -> list[dict]:
    return [{"emailAddress": {"address": a}} for a in addresses]


def send_graph(token: str, to: list[str], subject: str, html: str, cc: list[str] | None = None,
               bcc: list[str] | None = None, reply_to: str | None = None,
               attachment: tuple[str, bytes, str] | None = None) -> None:
    message: dict = {"subject": subject, "body": {"contentType": "HTML", "content": html},
                     "toRecipients": _recipients(to)}
    if cc:
        message["ccRecipients"] = _recipients(cc)
    if bcc:
        message["bccRecipients"] = _recipients(bcc)
    if reply_to:
        message["replyTo"] = _recipients([reply_to])
    if attachment:
        name, data, mime = attachment
        message["attachments"] = [{"@odata.type": "#microsoft.graph.fileAttachment", "name": name, "contentType": mime,
                                   "contentBytes": base64.b64encode(data).decode("ascii")}]
    status, data = _http("POST", f"{GRAPH}/me/sendMail", body={"message": message, "saveToSentItems": True},
                         token=token)
    if status in (200, 202):
        return
    err = (data.get("error") or {}) if isinstance(data.get("error"), dict) else {}
    code, text = err.get("code", ""), err.get("message", "")
    if status == 401:
        raise MailError("Microsoft rejected the sign-in. Connect Microsoft 365 again in Settings > Email.")
    if code == "MailboxNotEnabledForRESTAPI" or "mailbox" in text.lower() and "not" in text.lower():
        raise MailError("This Microsoft account has no Exchange Online mailbox. Sign in with a licensed mailbox.")
    if status == 403 or code == "ErrorAccessDenied":
        raise MailError("Microsoft didn't allow sending. The app needs the Mail.Send permission (and admin consent "
                        "if your tenant requires it).")
    raise MailError(f"Microsoft couldn't send the email ({status} {code}): {text[:300]}")
