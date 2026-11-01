"""Which companies a user can open, and with which role."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Company, CompanyMember, Reseller, ResellerAdmin, User

COMPANY_COOKIE = "fm_company"


@dataclass
class Access:
    company: Company
    role: str
    via_reseller: bool
    custom_role_id: uuid.UUID | None = None  # v0.10.0


def reseller_ids_administered(db: Session, user: User) -> set[uuid.UUID]:
    return set(db.scalars(select(ResellerAdmin.reseller_id).join(Reseller, Reseller.id == ResellerAdmin.reseller_id)
                          .where(ResellerAdmin.user_id == user.id, Reseller.is_active.is_(True))))


def accessible(db: Session, user: User) -> dict[uuid.UUID, Access]:
    """Explicit memberships first; reseller admins can also open every active client company as owner."""
    out: dict[uuid.UUID, Access] = {}
    for company, role, custom in db.execute(
        select(Company, CompanyMember.role, CompanyMember.custom_role_id)
        .join(CompanyMember, CompanyMember.company_id == Company.id)
        .where(CompanyMember.user_id == user.id, Company.is_active.is_(True))
    ).all():
        out[company.id] = Access(company, role, False, custom)
    resellers = reseller_ids_administered(db, user)
    if resellers:
        for company in db.scalars(select(Company).where(Company.reseller_id.in_(resellers),
                                                        Company.is_active.is_(True))):
            if company.id not in out:
                out[company.id] = Access(company, "owner", True)
    return out


def pick(access: dict[uuid.UUID, Access], wanted: str | None) -> Access | None:
    if wanted:
        try:
            chosen = access.get(uuid.UUID(wanted))
        except ValueError:
            chosen = None
        if chosen is not None:
            return chosen
    if not access:
        return None
    # No remembered choice (new browser): the user's longest-standing company, i.e. their home company.
    return sorted(access.values(), key=lambda a: (a.company.created_at, a.company.name.lower()))[0]


def describe(db: Session, user: User):
    """UserOut for the signed-in user, using the company resolved for this request."""
    from .schemas import UserOut
    from .tenancy import NO_COMPANY, company_of

    from . import modules

    company_id = company_of(db)
    company = db.get(Company, company_id) if company_id and company_id != NO_COMPANY else None
    plan = {}
    default_theme = (company.default_theme if company is not None else None) or "classic"
    plan.update(theme=user.theme, theme_effective=user.theme or default_theme, company_default_theme=default_theme)
    if company is not None:
        plan |= {"plan": company.plan, "plan_label": modules.plan_label(company, db), "modules": modules.enabled_list(company),
                "module_data": modules.data_present(db, company), "user_limit": company.user_limit,
                "seats_used": modules.seats_used(db, company.id)}
    plan.update(permissions=dict(getattr(user, "area_levels", {}) or {}),
                custom_role_name=user.custom_role.name if getattr(user, "custom_role", None) is not None else None)
    return UserOut(**plan,
        id=user.id, email=user.email, name=user.name, role=user.access_role or "none",
        company_role=user.company_role, company_id=company.id if company else None,
        company_name=company.name if company else None, company_count=len(accessible(db, user)),
        is_platform_admin=user.is_platform_admin, is_reseller_admin=bool(reseller_ids_administered(db, user)),
    )


def new_temporary_password() -> str:
    import secrets

    return secrets.token_urlsafe(9)


def find_or_create_user(db: Session, email: str, name: str | None) -> tuple[User, str | None]:
    """Existing user by email, or a new one with a temporary password (returned once)."""
    from sqlalchemy import func

    from .security import hash_password

    email = email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is not None:
        return user, None
    password = new_temporary_password()
    user = User(email=email, name=(name or "").strip() or email.split("@")[0], password_hash=hash_password(password),
                role="submitter")
    db.add(user)
    db.flush()
    return user, password
