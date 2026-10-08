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
