from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Vendor


def like_pattern(text: str) -> str:
    """Build an ILIKE 'contains' pattern with wildcards in user input escaped."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def get_or_create_vendor(db: Session, name: str | None) -> Vendor | None:
    if not name:
        return None
    vendor = db.scalar(select(Vendor).where(func.lower(Vendor.name) == name.lower()))
    if vendor is None:
        vendor = Vendor(name=name)
        db.add(vendor)
        db.flush()
    return vendor


def current_company(db: Session):
    """The company this request works in (resolved from the sign-in and the company switcher)."""
    from fastapi import HTTPException, status

    from ..models import Company
    from ..tenancy import company_of

    from ..tenancy import NO_COMPANY

    company_id = company_of(db)
    company = db.get(Company, company_id) if company_id and company_id != NO_COMPANY else None
    if company is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Choose a company first")
    return company
