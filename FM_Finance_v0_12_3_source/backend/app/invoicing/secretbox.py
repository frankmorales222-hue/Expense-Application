"""Encrypts stored secrets (the SMTP password) with a key derived from JWT_SECRET.

If JWT_SECRET changes, stored passwords can't be read any more and have to be entered again in
Settings > Email; nothing else is affected.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings


class SecretUnavailable(RuntimeError):
    pass


def _fernet() -> Fernet:
    secret = get_settings().JWT_SECRET
    if not secret:
        raise SecretUnavailable("JWT_SECRET is not set, so passwords can't be stored securely")
    key = hashlib.sha256(b"fm-finance/smtp-password/v1:" + secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretUnavailable("The saved email password can't be read (the app's secret key changed). "
                                "Enter the password again in Settings > Email.") from exc
