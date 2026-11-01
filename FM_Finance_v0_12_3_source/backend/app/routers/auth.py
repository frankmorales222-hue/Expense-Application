from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Request, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..access import COMPANY_COOKIE, describe
from ..database import get_db
from ..paths import app_dir, is_frozen
from ..models import User
from ..schemas import ChangePasswordIn, LoginIn, ThemeIn, UserOut
from ..security import (
    clear_session_cookie,
    create_token,
    current_user,
    hash_password,
    login_throttle,
    set_session_cookie,
    verify_password, bind_company, set_company_cookie,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger(__name__)


def remove_initial_password_traces() -> None:
    """After the first password change, delete the plaintext first-run password.

    Only for the packaged app: a developer's source-tree .env is never edited (tests change passwords).
    """
    if not is_frozen():
        return
    try:
        (app_dir() / "INITIAL_LOGIN.txt").unlink(missing_ok=True)
        env_path = app_dir() / ".env"
        if env_path.is_file():
            text = env_path.read_text(encoding="utf-8")
            cleaned = re.sub(r"(?m)^(\s*ADMIN_INITIAL_PASSWORD\s*=).*$", r"\1", text)
            if cleaned != text:
                env_path.write_text(cleaned, encoding="utf-8")
    except OSError:
        log.warning("Could not remove the initial password from INITIAL_LOGIN.txt/.env; delete it manually.")


@router.post("/login", response_model=UserOut)
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> UserOut:
    key = payload.email.strip().lower()
    if login_throttle.is_blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts. Try again in 15 minutes.")
    user = db.scalar(select(User).where(func.lower(User.email) == key))
    if user is None or not user.is_active or not verify_password(user.password_hash, payload.password):
        login_throttle.fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    login_throttle.reset(key)
    set_session_cookie(response, create_token(user.id, user.token_version))
    bind_company(request, db, user)
    if user.company_role:
        set_company_cookie(response, request.state.company.id)
    return describe(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


@router.get("/me", response_model=UserOut)
def me(request: Request, response: Response, user: User = Depends(current_user),
       db: Session = Depends(get_db)) -> UserOut:
    company = getattr(request.state, "company", None)
    # Sessions that began before v0.5.0 (or before a switch) may lack the remembered-company cookie,
    # which the sign-in page uses for its logo.
    if company is not None and request.cookies.get(COMPANY_COOKIE) != str(company.id):
        set_company_cookie(response, company.id)
    return describe(db, user)


@router.put("/me/theme", response_model=UserOut)
def set_theme(payload: ThemeIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> UserOut:
    """The person's own look (v0.9.0); follows them to every company. None goes back to the company default."""
    user.theme = payload.theme
    db.commit()
    return describe(db, user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1  # signs out every other session
    audit.record(db, entity_type="user", entity_id=user.id, action="password_changed", user_id=user.id,
                 account_level=True)
    db.commit()
    remove_initial_password_traces()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session_cookie(response, create_token(user.id, user.token_version))
    return response
