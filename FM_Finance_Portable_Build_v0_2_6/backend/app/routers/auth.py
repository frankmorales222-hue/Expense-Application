from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..models import User
from ..schemas import ChangePasswordIn, LoginIn, UserOut
from ..security import (
    clear_session_cookie,
    create_token,
    current_user,
    hash_password,
    login_throttle,
    set_session_cookie,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)) -> User:
    key = payload.email.strip().lower()
    if login_throttle.is_blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts. Try again in 15 minutes.")
    user = db.scalar(select(User).where(func.lower(User.email) == key))
    if user is None or not user.is_active or not verify_password(user.password_hash, payload.password):
        login_throttle.fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    login_throttle.reset(key)
    set_session_cookie(response, create_token(user.id))
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    audit.record(db, entity_type="user", entity_id=user.id, action="password_changed", user_id=user.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
