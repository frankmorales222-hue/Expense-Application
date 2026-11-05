"""The company's own roles (v0.10.0). Owners manage them on the Team page."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, permissions
from ..permissions import Level
from ..database import get_db
from ..models import CompanyMember, CompanyRole, User
from ..schemas import CompanyRole as BaseRole
from ..security import require_roles
from .util import current_company

router = APIRouter(prefix="/api/roles", tags=["roles"])
OWNERS = require_roles("admin", viewer_can_read=False)


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    base_role: BaseRole
    permissions: dict[str, Level] = {}


class RoleOut(RoleIn):
    id: uuid.UUID
    effective: dict[str, str]
    member_count: int


class AreasOut(BaseModel):
    areas: dict[str, str]
    base: dict[str, dict[str, str]]


def _out(db: Session, r: CompanyRole) -> RoleOut:
    n = db.scalar(select(func.count()).select_from(CompanyMember).where(CompanyMember.custom_role_id == r.id)) or 0
    return RoleOut(id=r.id, name=r.name, description=r.description, base_role=r.base_role,
                   permissions=r.permissions or {}, effective=permissions.effective(r.base_role, r.permissions),
                   member_count=n)


def _clean(payload: RoleIn) -> dict[str, str]:
    bad = [a for a in payload.permissions if a not in permissions.AREAS]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown area: {bad[0]}")
    return {a: v for a, v in payload.permissions.items() if v != "full"}


@router.get("/areas", response_model=AreasOut)
def areas(_: User = Depends(OWNERS)) -> AreasOut:
    return AreasOut(areas=permissions.AREAS, base=permissions.BASE)


@router.get("", response_model=list[RoleOut])
def list_roles(db: Session = Depends(get_db), _: User = Depends(OWNERS)) -> list[RoleOut]:
    company = current_company(db)
    return [_out(db, r) for r in db.scalars(select(CompanyRole).where(CompanyRole.company_id == company.id)
                                           .order_by(CompanyRole.name))]


def _unique(db: Session, company_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> None:
    stmt = select(CompanyRole.id).where(CompanyRole.company_id == company_id,
                                        func.lower(CompanyRole.name) == name.strip().lower())
    if exclude:
        stmt = stmt.where(CompanyRole.id != exclude)
    if db.scalar(stmt):
        raise HTTPException(status.HTTP_409_CONFLICT, "A role with that name already exists")


@router.post("", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(payload: RoleIn, db: Session = Depends(get_db), user: User = Depends(OWNERS)) -> RoleOut:
    company = current_company(db)
    _unique(db, company.id, payload.name)
    r = CompanyRole(id=uuid.uuid4(), company_id=company.id, name=payload.name.strip(), description=payload.description,
                    base_role=payload.base_role, permissions=_clean(payload))
    db.add(r)
    audit.record(db, entity_type="company", entity_id=company.id, action="role_created", user_id=user.id,
                 changes={"name": r.name, "base": r.base_role, "permissions": r.permissions})
    db.commit()
    return _out(db, r)


@router.put("/{role_id}", response_model=RoleOut)
def update_role(role_id: uuid.UUID, payload: RoleIn, db: Session = Depends(get_db),
                user: User = Depends(OWNERS)) -> RoleOut:
    company = current_company(db)
    r = db.get(CompanyRole, role_id)
    if r is None or r.company_id != company.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    _unique(db, company.id, payload.name, exclude=r.id)
    before = {"name": r.name, "base": r.base_role, "permissions": r.permissions}
    r.name, r.description, r.base_role, r.permissions = payload.name.strip(), payload.description, payload.base_role, \
        _clean(payload)
    # People with this role move with its base role.
    for m in db.scalars(select(CompanyMember).where(CompanyMember.custom_role_id == r.id)):
        m.role = r.base_role
    audit.record(db, entity_type="company", entity_id=company.id, action="role_changed", user_id=user.id,
                 changes={"before": before, "after": {"name": r.name, "base": r.base_role, "permissions": r.permissions}})
    db.commit()
    return _out(db, r)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(role_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(OWNERS)) -> Response:
    """People who had it keep the base role."""
    company = current_company(db)
    r = db.get(CompanyRole, role_id)
    if r is None or r.company_id != company.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    for m in db.scalars(select(CompanyMember).where(CompanyMember.custom_role_id == r.id)):
        m.custom_role_id = None
    audit.record(db, entity_type="company", entity_id=company.id, action="role_deleted", user_id=user.id,
                 changes={"name": r.name})
    db.delete(r)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
