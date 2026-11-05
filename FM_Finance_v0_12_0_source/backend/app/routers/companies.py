"""Company list, switching and creation (multi-company, v0.5.0)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..access import accessible, describe, reseller_ids_administered
from ..bootstrap import seed_company_categories
from ..ledger.chart import ensure_chart
from ..database import get_db
from ..models import Company, CompanyMember, Reseller, User
from ..schemas import CompanyCreateIn, CompanyListItem, UserOut
from ..security import bind_company, current_user, set_company_cookie
from ..tenancy import acting_as, company_of

router = APIRouter(prefix="/api/companies", tags=["companies"])


def _version(c: Company) -> int:
    return int(c.logo_updated_at.timestamp()) if c.logo_updated_at else 0


@router.get("", response_model=list[CompanyListItem])
def list_companies(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[CompanyListItem]:
    access = accessible(db, user)
    resellers = {r.id: r.name for r in db.scalars(select(Reseller))}
    current = company_of(db)
    return [
        CompanyListItem(
            id=a.company.id, name=a.company.name, role=a.role, via_reseller=a.via_reseller,
            reseller_id=a.company.reseller_id, reseller_name=resellers.get(a.company.reseller_id),
            has_logo=a.company.logo_updated_at is not None, logo_version=_version(a.company),
            is_current=a.company.id == current,
        )
        for a in sorted(access.values(), key=lambda a: a.company.name.lower())
    ]


@router.post("/{company_id}/switch", response_model=UserOut)
def switch_company(company_id: uuid.UUID, request: Request, response: Response, db: Session = Depends(get_db),
                   user: User = Depends(current_user)) -> UserOut:
    if company_id not in accessible(db, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    bind_company(request, db, user, str(company_id))
    set_company_cookie(response, company_id)
    return describe(db, user)


@router.post("", response_model=CompanyListItem, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreateIn, db: Session = Depends(get_db),
                   user: User = Depends(current_user)) -> CompanyListItem:
    """Platform admins create any company; reseller admins create client companies for their reseller."""
    administered = reseller_ids_administered(db, user)
    reseller_id = payload.reseller_id
    if not user.is_platform_admin:
        if not administered:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators can add companies")
        if reseller_id is None and len(administered) == 1:
            reseller_id = next(iter(administered))
        if reseller_id not in administered:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only add companies for your own reseller")
    reseller = db.get(Reseller, reseller_id) if reseller_id else None
    if reseller_id and (reseller is None or not reseller.is_active):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Reseller not found")

    from .. import modules as plans

    plan_row = plans.find_plan(db, payload.plan, reseller_id)
    if plan_row is None or not plan_row.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose one of the available plans")
    plan_modules, plan_users = [m for m in plans.ALL if m in plan_row.modules], plan_row.user_limit
    company = Company(name=payload.name, legal_name=(payload.legal_name or "").strip() or None,
                      reseller_id=reseller_id, fiscal_year_start_month=payload.fiscal_year_start_month,
                      plan=payload.plan, modules=list(plan_modules), user_limit=plan_users)
    db.add(company)
    db.flush()
    # Platform admins become the owner; reseller admins already reach their client companies as owner.
    via_reseller = bool(reseller_id and reseller_id in administered)
    if not via_reseller:
        db.add(CompanyMember(company_id=company.id, user_id=user.id, role="owner"))
    with acting_as(db, company.id):
        seed_company_categories(db, company.id)
        db.flush()
        ensure_chart(db, company.id)
        company.ledger_ready = True
        audit.record(db, entity_type="company", entity_id=company.id, action="created", user_id=user.id,
                     changes={"name": company.name, "reseller": reseller.name if reseller else None})
    db.commit()
    return CompanyListItem(
        id=company.id, name=company.name, role="owner", via_reseller=via_reseller, reseller_id=reseller_id,
        reseller_name=reseller.name if reseller else None, has_logo=False, logo_version=0, is_current=False,
    )
