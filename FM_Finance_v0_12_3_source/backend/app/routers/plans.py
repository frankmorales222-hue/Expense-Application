"""Plans and modules admin (v0.8.0): the platform owner manages every company; a reseller admin manages
the companies of their reseller. Only names and plans are shown here, never a company's books."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, modules
from ..access import reseller_ids_administered
from ..database import get_db
from ..models import Company, Plan, Reseller, User
from ..schemas import (
    CompanyPlanIn, CompanyPlanOut, CompanyThemeIn, ModuleInfo, PlanEditIn, PlanInfo, PlansCatalog,
)
from ..security import current_user
from ..tenancy import acting_as

router = APIRouter(prefix="/api/plans", tags=["plans"])


def _plan_info(p: Plan, resellers: dict, editable: bool) -> PlanInfo:
    return PlanInfo(id=p.id, key=p.key, label=p.label, modules=[m for m in modules.ALL if m in (p.modules or [])],
                    user_limit=p.user_limit, description=p.description, monthly_price=p.monthly_price,
                    is_active=p.is_active, sort_order=p.sort_order, reseller_id=p.reseller_id,
                    reseller_name=resellers.get(p.reseller_id), editable=editable)


def _can_edit(db: Session, user: User, p: Plan) -> bool:
    if user.is_platform_admin:
        return True
    return p.reseller_id is not None and p.reseller_id in reseller_ids_administered(db, user)


@router.get("/catalog", response_model=PlansCatalog)
def catalog(include_inactive: bool = False, db: Session = Depends(get_db),
            user: User = Depends(current_user)) -> PlansCatalog:
    """Modules (features, part of the software) and plans (bundles each seller defines, v0.10.0)."""
    resellers = {r.id: r.name for r in db.scalars(select(Reseller))}
    if user.is_platform_admin:
        stmt = select(Plan)
    else:
        mine = reseller_ids_administered(db, user)
        stmt = select(Plan).where(Plan.reseller_id.is_(None) | Plan.reseller_id.in_(mine)) if mine \
            else select(Plan).where(Plan.reseller_id.is_(None))
    if not include_inactive:
        stmt = stmt.where(Plan.is_active.is_(True))
    rows = list(db.scalars(stmt.order_by(Plan.reseller_id.is_not(None), Plan.sort_order, Plan.label)))
    return PlansCatalog(
        modules=[ModuleInfo(key=k, label=v[0], description=v[1]) for k, v in modules.MODULES.items()],
        plans=[_plan_info(p, resellers, _can_edit(db, user, p)) for p in rows])


def _clean_modules(mods: list[str]) -> list[str]:
    unknown = [m for m in mods if m not in modules.MODULES]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown module: {unknown[0]}")
    return [m for m in modules.ALL if m in mods]


@router.post("/catalog", response_model=PlanInfo, status_code=status.HTTP_201_CREATED)
def create_plan(payload: PlanEditIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> PlanInfo:
    """The platform owner adds plans for everyone (or for one reseller); a reseller admin adds its own."""
    mine = reseller_ids_administered(db, user)
    reseller_id = payload.reseller_id
    if not user.is_platform_admin:
        if not mine:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators can manage plans")
        if reseller_id is None and len(mine) == 1:
            reseller_id = next(iter(mine))
        if reseller_id not in mine:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only add plans for your own reseller")
    if not payload.key or payload.key == "custom":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give the plan a short code (letters, numbers, _)")
    clash = db.scalar(select(Plan.id).where(Plan.key == payload.key,
                                            (Plan.reseller_id == reseller_id) if reseller_id else Plan.reseller_id.is_(None)))
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, "A plan with that code already exists")
    p = Plan(id=uuid.uuid4(), reseller_id=reseller_id, key=payload.key, label=payload.label,
             description=payload.description, modules=_clean_modules(payload.modules), user_limit=payload.user_limit,
             monthly_price=payload.monthly_price, is_active=payload.is_active, sort_order=payload.sort_order)
    db.add(p)
    db.commit()
    resellers = {r.id: r.name for r in db.scalars(select(Reseller))}
    return _plan_info(p, resellers, True)


@router.put("/catalog/{plan_id}", response_model=PlanInfo)
def edit_plan(plan_id: uuid.UUID, payload: PlanEditIn, apply_to_companies: bool = False,
              db: Session = Depends(get_db), user: User = Depends(current_user)) -> PlanInfo:
    """Change a plan. With apply_to_companies, companies on it get the new modules and user limit too
    (otherwise only companies put on it from now on)."""
    p = db.get(Plan, plan_id)
    if p is None or not _can_edit(db, user, p):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    p.label, p.description = payload.label, payload.description
    p.modules, p.user_limit = _clean_modules(payload.modules), payload.user_limit
    p.monthly_price, p.is_active, p.sort_order = payload.monthly_price, payload.is_active, payload.sort_order
    if apply_to_companies:
        for c in db.scalars(select(Company).where(Company.plan == p.key)):
            if modules.find_plan(db, c.plan, c.reseller_id) is p:
                c.modules, c.user_limit = list(p.modules), p.user_limit
    db.commit()
    resellers = {r.id: r.name for r in db.scalars(select(Reseller))}
    return _plan_info(p, resellers, True)


def _managed(db: Session, user: User) -> list[Company]:
    if user.is_platform_admin:
        return list(db.scalars(select(Company).order_by(Company.name)))
    resellers = reseller_ids_administered(db, user)
    if not resellers:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators can manage plans")
    return list(db.scalars(select(Company).where(Company.reseller_id.in_(resellers)).order_by(Company.name)))


def _out(db: Session, c: Company, resellers: dict) -> CompanyPlanOut:
    return CompanyPlanOut(id=c.id, name=c.name, reseller_name=resellers.get(c.reseller_id), is_active=c.is_active,
                          plan=c.plan, plan_label=modules.plan_label(c, db), modules=modules.enabled_list(c),
                          user_limit=c.user_limit, seats_used=modules.seats_used(db, c.id), created_at=c.created_at,
                          default_theme=c.default_theme or "classic")


@router.get("/companies", response_model=list[CompanyPlanOut])
def companies(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[CompanyPlanOut]:
    resellers = {r.id: r.name for r in db.scalars(select(Reseller))}
    return [_out(db, c, resellers) for c in _managed(db, user)]


@router.put("/companies/{company_id}", response_model=CompanyPlanOut)
def set_plan(company_id: uuid.UUID, payload: CompanyPlanIn, db: Session = Depends(get_db),
             user: User = Depends(current_user)) -> CompanyPlanOut:
    company = next((c for c in _managed(db, user) if c.id == company_id), None)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    plan_row = None
    if payload.plan == "custom":
        if payload.modules is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose the modules for a custom plan")
        chosen, limit = payload.modules, payload.user_limit
    else:
        plan_row = modules.find_plan(db, payload.plan, company.reseller_id)
        if plan_row is None or not plan_row.is_active:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That plan isn't available for this company")
        chosen = payload.modules if payload.modules is not None else list(plan_row.modules)
        limit = payload.user_limit if "user_limit" in payload.model_fields_set else plan_row.user_limit
    unknown = [m for m in chosen if m not in modules.MODULES]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown module: {unknown[0]}")
    ordered = [m for m in modules.ALL if m in chosen]
    plan = payload.plan
    if plan_row is not None:
        if tuple(ordered) != tuple(m for m in modules.ALL if m in plan_row.modules) or limit != plan_row.user_limit:
            plan = "custom"  # adjusted by hand
    before = {"plan": company.plan, "modules": modules.enabled_list(company), "user_limit": company.user_limit}
    company.plan, company.modules, company.user_limit = plan, ordered, limit
    with acting_as(db, company.id):
        audit.record(db, entity_type="company", entity_id=company.id, action="plan_changed", user_id=user.id,
                     changes={"before": before, "after": {"plan": plan, "modules": ordered, "user_limit": limit}})
    db.commit()
    resellers = {r.id: r.name for r in db.scalars(select(Reseller))}
    return _out(db, company, resellers)


@router.put("/companies/{company_id}/theme", response_model=CompanyPlanOut)
def set_default_theme(company_id: uuid.UUID, payload: CompanyThemeIn, db: Session = Depends(get_db),
                      user: User = Depends(current_user)) -> CompanyPlanOut:
    """The look a client company's people get until they choose their own (v0.9.0)."""
    company = next((c for c in _managed(db, user) if c.id == company_id), None)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    before = company.default_theme or "classic"
    company.default_theme = None if payload.default_theme == "classic" else payload.default_theme
    with acting_as(db, company.id):
        audit.record(db, entity_type="company", entity_id=company.id, action="default_theme_changed", user_id=user.id,
                     changes={"before": before, "after": payload.default_theme})
    db.commit()
    resellers = {r.id: r.name for r in db.scalars(select(Reseller))}
    return _out(db, company, resellers)
