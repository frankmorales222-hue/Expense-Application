from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..models import ExpenseCategory, User, Vendor
from ..schemas import VendorDetail, VendorOut, VendorUpdate
from ..security import require_company, require_roles
from .util import like_pattern

router = APIRouter(prefix="/api/vendors", tags=["vendors"])


@router.get("", response_model=list[VendorOut])
def search_vendors(
    q: str = Query(default="", max_length=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_company),
) -> list[Vendor]:
    stmt = select(Vendor).order_by(Vendor.name).limit(10)
    if q.strip():
        stmt = stmt.where(Vendor.name.ilike(like_pattern(q.strip()), escape="\\"))
    return list(db.scalars(stmt))


@router.get("/all", response_model=list[VendorDetail])
def all_vendors(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "approver"))) -> list[Vendor]:
    return list(db.scalars(select(Vendor).order_by(Vendor.name).limit(2000)))


@router.put("/{vendor_id}", response_model=VendorDetail)
def update_vendor(vendor_id: uuid.UUID, payload: VendorUpdate, db: Session = Depends(get_db),
                  user: User = Depends(require_roles("admin", "approver"))) -> Vendor:
    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")
    changes: dict[str, object] = {}
    if payload.name is not None:
        name = " ".join(payload.name.split())
        clash = db.scalar(select(Vendor.id).where(func.lower(Vendor.name) == name.lower(), Vendor.id != vendor.id))
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, "A vendor with that name already exists")
        if name != vendor.name:
            changes["name"] = [vendor.name, name]
            vendor.name = name
    if payload.clear_default_category:
        if vendor.default_category_id is not None:
            changes["default_category_id"] = [vendor.default_category_id, None]
        vendor.default_category_id = None
    elif payload.default_category_id is not None:
        if db.get(ExpenseCategory, payload.default_category_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Category not found")
        changes["default_category_id"] = [vendor.default_category_id, payload.default_category_id]
        vendor.default_category_id = payload.default_category_id
    if payload.is_1099 is not None and payload.is_1099 != vendor.is_1099:
        changes["is_1099"] = [vendor.is_1099, payload.is_1099]
        vendor.is_1099 = payload.is_1099
    if payload.match_key is not None:
        key = " ".join(payload.match_key.upper().split()) or None
        if key != vendor.match_key:
            changes["match_key"] = [vendor.match_key, key]
            vendor.match_key = key
    if changes:
        audit.record(db, entity_type="vendor", entity_id=vendor.id, action="updated", user_id=user.id,
                     changes=changes)
        db.commit()
    return vendor
