"""People with access to the current company, and their roles (owners only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..access import find_or_create_user
from ..database import get_db
from ..models import CompanyMember, CompanyRole, ResellerAdmin, User
from ..schemas import MemberAdded, MemberIn, MemberOut, MemberRoleIn
from ..security import require_roles
from .util import current_company

router = APIRouter(prefix="/api/members", tags=["members"])
OWNERS = require_roles("admin", viewer_can_read=False)  # member emails are for owners only


def _out(m: CompanyMember, u: User, me: User, db: Session | None = None) -> MemberOut:
    custom = db.get(CompanyRole, m.custom_role_id) if (db is not None and m.custom_role_id) else None
    return MemberOut(user_id=u.id, name=u.name, email=u.email, role=m.role, via_reseller=False,
                     is_you=u.id == me.id, is_active=u.is_active, custom_role_id=custom.id if custom else None,
                     custom_role_name=custom.name if custom else None)


def _resolve(db: Session, company_id: uuid.UUID, role: str, custom_role_id: uuid.UUID | None) -> tuple[str, uuid.UUID | None]:
    """A custom role decides the base role (v0.10.0)."""
    if custom_role_id is None:
        return role, None
    custom = db.get(CompanyRole, custom_role_id)
    if custom is None or custom.company_id != company_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Role not found")
    return custom.base_role, custom.id


@router.get("", response_model=list[MemberOut])
def list_members(db: Session = Depends(get_db), me: User = Depends(OWNERS)) -> list[MemberOut]:
    company = current_company(db)
    out = [_out(m, u, me, db) for m, u in db.execute(
        select(CompanyMember, User).join(User, User.id == CompanyMember.user_id)
        .where(CompanyMember.company_id == company.id).order_by(User.name)).all()]
    if company.reseller_id:
        listed = {m.user_id for m in out}
        for u in db.scalars(select(User).join(ResellerAdmin, ResellerAdmin.user_id == User.id)
                            .where(ResellerAdmin.reseller_id == company.reseller_id).order_by(User.name)):
            if u.id not in listed:
                out.append(MemberOut(user_id=u.id, name=u.name, email=u.email, role="owner", via_reseller=True,
                                     is_you=u.id == me.id, is_active=u.is_active))
    return out


def _owner_count(db: Session, company_id: uuid.UUID) -> int:
    """Owners with the full owner role (an owner-based custom role can be narrowed, so it doesn't count)."""
    return db.scalar(select(func.count()).select_from(CompanyMember).where(
        CompanyMember.company_id == company_id, CompanyMember.role == "owner",
        CompanyMember.custom_role_id.is_(None))) or 0


def _check_seat(db: Session, company, role: str, user: User | None = None) -> None:
    """The plan's user limit; the Accountant and the platform owner don't take a seat."""
    from .. import modules

    if role == "accountant" or company.user_limit is None or (user is not None and user.is_platform_admin):
        return
    if modules.seats_used(db, company.id) >= company.user_limit:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This company's plan includes {company.user_limit} user"
                            f"{'s' if company.user_limit != 1 else ''}, and all are in use. Ask your administrator "
                            "for more users, or remove someone first. The Accountant doesn't count.")


@router.post("", response_model=MemberAdded, status_code=status.HTTP_201_CREATED)
def add_member(payload: MemberIn, db: Session = Depends(get_db), me: User = Depends(OWNERS)) -> MemberAdded:
    company = current_company(db)
    user, password = find_or_create_user(db, payload.email, payload.name)
    if db.get(CompanyMember, (company.id, user.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{user.email} already has access to {company.name}")
    role, custom_id = _resolve(db, company.id, payload.role, payload.custom_role_id)
    _check_seat(db, company, role, user)
    member = CompanyMember(company_id=company.id, user_id=user.id, role=role, custom_role_id=custom_id)
    db.add(member)
    audit.record(db, entity_type="company", entity_id=company.id, action="member_added", user_id=me.id,
                 changes={"email": user.email, "role": role, "custom_role": str(custom_id) if custom_id else None,
                          "new_user": password is not None})
    db.commit()
    return MemberAdded(member=_out(member, user, me, db), temporary_password=password)


def _load(db: Session, user_id: uuid.UUID) -> tuple[CompanyMember, User]:
    company = current_company(db)
    member = db.get(CompanyMember, (company.id, user_id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    return member, db.get(User, user_id)


@router.put("/{user_id}", response_model=MemberOut)
def change_role(user_id: uuid.UUID, payload: MemberRoleIn, db: Session = Depends(get_db),
                me: User = Depends(OWNERS)) -> MemberOut:
    member, user = _load(db, user_id)
    role, custom_id = _resolve(db, member.company_id, payload.role, payload.custom_role_id)
    full_owner = member.role == "owner" and member.custom_role_id is None
    if full_owner and (role != "owner" or custom_id is not None) and _owner_count(db, member.company_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A company needs at least one owner with the full Owner role")
    if member.role == "accountant" and role != "accountant":
        _check_seat(db, current_company(db), role, user)
    if member.role != role or member.custom_role_id != custom_id:
        audit.record(db, entity_type="company", entity_id=member.company_id, action="member_role_changed",
                     user_id=me.id, changes={"email": user.email, "role": [member.role, role],
                                             "custom_role": [str(member.custom_role_id) if member.custom_role_id
                                                             else None, str(custom_id) if custom_id else None]})
        member.role, member.custom_role_id = role, custom_id
        db.commit()
    return _out(member, user, me, db)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: uuid.UUID, db: Session = Depends(get_db), me: User = Depends(OWNERS)) -> Response:
    member, user = _load(db, user_id)
    if member.role == "owner" and member.custom_role_id is None and _owner_count(db, member.company_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A company needs at least one owner")
    audit.record(db, entity_type="company", entity_id=member.company_id, action="member_removed", user_id=me.id,
                 changes={"email": user.email, "role": member.role})
    db.delete(member)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
