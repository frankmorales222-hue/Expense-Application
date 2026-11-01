"""Resellers (partners who offer F&M Finance to their own clients). Managed by platform admins."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..access import find_or_create_user, reseller_ids_administered
from ..database import get_db
from ..models import Company, Reseller, ResellerAdmin, User
from ..schemas import ResellerAdminAdded, ResellerAdminIn, ResellerAdminOut, ResellerIn, ResellerOut
from ..security import current_user

router = APIRouter(prefix="/api/resellers", tags=["resellers"])


def platform_admin(user: User = Depends(current_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only platform administrators can manage resellers")
    return user


def _out(db: Session, r: Reseller) -> ResellerOut:
    count = db.scalar(select(func.count(Company.id)).where(Company.reseller_id == r.id)) or 0
    admins = [ResellerAdminOut(user_id=u.id, name=u.name, email=u.email) for u in db.scalars(
        select(User).join(ResellerAdmin, ResellerAdmin.user_id == User.id)
        .where(ResellerAdmin.reseller_id == r.id).order_by(User.name))]
    return ResellerOut(id=r.id, name=r.name, is_active=r.is_active, company_count=count, admins=admins)


@router.get("", response_model=list[ResellerOut])
def list_resellers(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[ResellerOut]:
    stmt = select(Reseller).order_by(Reseller.name)
    if not user.is_platform_admin:
        mine = reseller_ids_administered(db, user)
        if not mine:
            return []
        stmt = stmt.where(Reseller.id.in_(mine))
    return [_out(db, r) for r in db.scalars(stmt)]


def _unique(db: Session, name: str, exclude: uuid.UUID | None = None) -> None:
    stmt = select(Reseller.id).where(func.lower(Reseller.name) == name.lower())
    if exclude:
        stmt = stmt.where(Reseller.id != exclude)
    if db.scalar(stmt):
        raise HTTPException(status.HTTP_409_CONFLICT, "A reseller with that name already exists")


@router.post("", response_model=ResellerOut, status_code=status.HTTP_201_CREATED)
def create_reseller(payload: ResellerIn, db: Session = Depends(get_db),
                    user: User = Depends(platform_admin)) -> ResellerOut:
    _unique(db, payload.name)
    reseller = Reseller(name=payload.name, is_active=payload.is_active)
    db.add(reseller)
    db.flush()
    audit.record(db, entity_type="reseller", entity_id=reseller.id, action="created", user_id=user.id, account_level=True,
                 changes={"name": reseller.name})
    db.commit()
    return _out(db, reseller)


def _load(db: Session, reseller_id: uuid.UUID) -> Reseller:
    reseller = db.get(Reseller, reseller_id)
    if reseller is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reseller not found")
    return reseller


@router.put("/{reseller_id}", response_model=ResellerOut)
def update_reseller(reseller_id: uuid.UUID, payload: ResellerIn, db: Session = Depends(get_db),
                    user: User = Depends(platform_admin)) -> ResellerOut:
    reseller = _load(db, reseller_id)
    _unique(db, payload.name, exclude=reseller.id)
    changes = {k: [getattr(reseller, k), v] for k, v in payload.model_dump().items() if getattr(reseller, k) != v}
    if changes:
        reseller.name, reseller.is_active = payload.name, payload.is_active
        audit.record(db, entity_type="reseller", entity_id=reseller.id, action="updated", user_id=user.id, account_level=True,
                     changes=changes)
        db.commit()
    return _out(db, reseller)


@router.post("/{reseller_id}/admins", response_model=ResellerAdminAdded, status_code=status.HTTP_201_CREATED)
def add_admin(reseller_id: uuid.UUID, payload: ResellerAdminIn, db: Session = Depends(get_db),
              user: User = Depends(platform_admin)) -> ResellerAdminAdded:
    reseller = _load(db, reseller_id)
    admin, password = find_or_create_user(db, payload.email, payload.name)
    if db.get(ResellerAdmin, (reseller.id, admin.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{admin.email} already manages {reseller.name}")
    db.add(ResellerAdmin(reseller_id=reseller.id, user_id=admin.id))
    audit.record(db, entity_type="reseller", entity_id=reseller.id, action="admin_added", user_id=user.id, account_level=True,
                 changes={"email": admin.email, "new_user": password is not None})
    db.commit()
    return ResellerAdminAdded(admin=ResellerAdminOut(user_id=admin.id, name=admin.name, email=admin.email),
                              temporary_password=password)


@router.delete("/{reseller_id}/admins/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_admin(reseller_id: uuid.UUID, user_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(platform_admin)) -> Response:
    link = db.get(ResellerAdmin, (reseller_id, user_id))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not an administrator of this reseller")
    db.delete(link)
    audit.record(db, entity_type="reseller", entity_id=reseller_id, action="admin_removed", user_id=user.id, account_level=True,
                 changes={"user_id": user_id})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
