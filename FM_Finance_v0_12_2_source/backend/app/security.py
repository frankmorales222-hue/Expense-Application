"""Password hashing (Argon2), JWT session cookie, and role checks."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from . import permissions, tenancy
from .access import COMPANY_COOKIE, accessible, pick
from .models import ROLE_ACCESS, CompanyRole, User

COOKIE_NAME = "fm_session"
_ALGORITHM = "HS256"
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_token(user_id: uuid.UUID, token_version: int = 0) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "ver": token_version, "iat": now,
               "exp": now + timedelta(hours=settings.JWT_EXPIRE_HOURS)}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=_ALGORITHM)


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.JWT_EXPIRE_HOURS * 3600,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def set_company_cookie(response: Response, company_id: uuid.UUID) -> None:
    """Remembers the chosen company (also used to show that company's logo on the sign-in page)."""
    response.set_cookie(COMPANY_COOKIE, str(company_id), max_age=365 * 24 * 3600, httponly=True,
                        secure=get_settings().COOKIE_SECURE, samesite="lax", path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if not token:
        raise unauthorized
    try:
        payload = jwt.decode(token, get_settings().JWT_SECRET, algorithms=[_ALGORITHM])
        user_id = uuid.UUID(payload["sub"])
        version = int(payload.get("ver", 0))
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        raise unauthorized from None
    user = db.get(User, user_id)
    if user is None or not user.is_active or user.token_version != version:
        raise unauthorized
    _bind_company(request, db, user)
    return user


def _viewer_may_write(path: str) -> bool:
    """Writes a view-only member may still make: their own sign-in and password, choosing a company."""
    return path.startswith("/api/auth/") or (path.startswith("/api/companies/") and path.endswith("/switch"))


def bind_company(request: Request, db: Session, user: User, wanted: str | None = None) -> None:
    _bind_company(request, db, user, wanted)


def _bind_company(request: Request, db: Session, user: User, wanted: str | None = None) -> None:
    """Resolve the company this request works in and scope the database session to it."""
    choice = pick(accessible(db, user), wanted or request.cookies.get(COMPANY_COOKIE))
    if choice is None:
        tenancy.set_company(db, tenancy.NO_COMPANY)  # fail closed: company data reads return nothing
        user.company_role = user.access_role = None
        user.custom_role, user.area_levels = None, {}
        request.state.company = None
        return
    tenancy.set_company(db, choice.company.id)
    user.company_role = choice.role
    user.access_role = ROLE_ACCESS[choice.role]
    request.state.company = choice.company
    if (choice.role == "viewer" and request.method not in ("GET", "HEAD", "OPTIONS")
            and not _viewer_may_write(request.url.path)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your access to this company is view-only")
    # v0.10.0 custom roles: the company's own role narrows what the base role may see and change, per area.
    user.custom_role = None
    user.area_levels = permissions.effective(choice.role, None)
    if choice.custom_role_id is not None:
        role = db.get(CompanyRole, choice.custom_role_id)
        if role is not None and role.company_id == choice.company.id:
            user.custom_role = role
            user.area_levels = permissions.effective(choice.role, role.permissions)
            reason = permissions.check(request.url.path, request.method, user.area_levels)
            if reason:
                raise HTTPException(status.HTTP_403_FORBIDDEN, reason)


def require_roles(*roles: str, viewer_can_read: bool = True) -> Callable[..., User]:
    """Permission names: admin (owner), approver (accountant/bookkeeper), submitter (employee).
    View-only members may read what the listed roles can read (unless viewer_can_read=False),
    but never write."""

    def checker(request: Request, user: User = Depends(current_user)) -> User:
        if user.access_role is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Choose a company first")
        if user.access_role in roles or (viewer_can_read and user.access_role == "viewer"
                                         and request.method in ("GET", "HEAD")):
            return user
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission for this action")

    return checker


def require_company(user: User = Depends(current_user)) -> User:
    """Any member of the current company (including employees and viewers)."""
    if user.access_role is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Choose a company first")
    return user


class LoginThrottle:
    """Simple in-memory limiter: 5 failed attempts per email per 15 minutes."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 900) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        q = self._failures[key]
        cutoff = time.monotonic() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def is_blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= self.max_failures

    def fail(self, key: str) -> None:
        self._prune(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


login_throttle = LoginThrottle()
