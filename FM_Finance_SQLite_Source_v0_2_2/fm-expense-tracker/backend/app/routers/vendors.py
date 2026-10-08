from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, Vendor
from ..schemas import VendorOut
from ..security import current_user
from .util import like_pattern

router = APIRouter(prefix="/api/vendors", tags=["vendors"])


@router.get("", response_model=list[VendorOut])
def search_vendors(
    q: str = Query(default="", max_length=100),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> list[Vendor]:
    stmt = select(Vendor).order_by(Vendor.name).limit(10)
    if q.strip():
        stmt = stmt.where(Vendor.name.ilike(like_pattern(q.strip()), escape="\\"))
    return list(db.scalars(stmt))
