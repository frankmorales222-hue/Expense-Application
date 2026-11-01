"""Small helpers so routers apply the company's rules (v0.10.0) and answer 422 with a clear message."""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .. import rules


def company_rules(db: Session) -> rules.CompanyRules:
    return rules.current(db)


def _422(exc: ValueError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


def custom(db: Session, entity: str, values: dict | None, before: dict | None = None,
           r: rules.CompanyRules | None = None) -> dict | None:
    r = r or rules.current(db)
    try:
        out = rules.clean_custom(r, entity, values, before)
    except ValueError as exc:
        raise _422(exc) from None
    return out or None


def term(db: Session, code: str | None, current: str | None = None, r: rules.CompanyRules | None = None) -> None:
    try:
        (r or rules.current(db)).check_term(code, current)
    except ValueError as exc:
        raise _422(exc) from None


def method(db: Session, kind: Literal["expense", "received"], code: str | None, current: str | None = None,
           r: rules.CompanyRules | None = None) -> None:
    try:
        (r or rules.current(db)).check_method(kind, code, current)
    except ValueError as exc:
        raise _422(exc) from None
