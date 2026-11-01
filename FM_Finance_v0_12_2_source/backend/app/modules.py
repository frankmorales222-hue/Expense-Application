"""Sellable modules and plans (v0.8.0).

Core (dashboard, expenses, accounts, banking, chart of accounts, profit and loss, balance sheet, closing date,
history, export, settings) is in every plan. Optional modules are switched on per company by the platform
owner or the company's reseller admin.

When a module is off its records stay readable (view, print, export) but nothing new can be created or
changed: the guard below blocks writes only. The books keep working underneath either way.
The company's Accountant always gets the Advanced accounting tools, whatever the plan.
"""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Company, User

MODULES: dict[str, tuple[str, str]] = {
    "invoicing": ("Invoicing", "Invoices with PDF and email, products and services, receive payment, A/R aging, "
                               "sales by customer"),
    "bills": ("Bills", "Bills from vendors, due dates and paying bills"),
    "smart_capture": ("Smart capture", "Fill in expenses and bills from PDF, Word, email and photos"),
    "advanced_accounting": ("Advanced accounting", "Journal entries and trial balance for the company's own staff "
                                                   "(the Accountant always has them)"),
}
ALL = tuple(MODULES)

# v0.10.0: plans are data (table "plans"), not code. The platform owner's plans (reseller_id NULL) are offered to
# every company; a reseller can add its own plans for its clients. These four are created at upgrade.
DEFAULT_PLANS = ("starter", "essentials", "plus", "advanced")
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def enabled(company: Company | None, key: str) -> bool:
    if company is None:
        return False
    mods = company.modules
    return True if mods is None else key in mods  # None: companies from before v0.8.0 keep everything


def enabled_list(company: Company | None) -> list[str]:
    return [k for k in ALL if enabled(company, k)]


def plans_for(db: Session, reseller_id=None, include_inactive: bool = False) -> list:
    """Plans a company of this reseller can be on: the platform's plans, then the reseller's own."""
    from sqlalchemy import or_

    from .models import Plan

    stmt = select(Plan).where(or_(Plan.reseller_id.is_(None), Plan.reseller_id == reseller_id) if reseller_id
                              else Plan.reseller_id.is_(None))
    if not include_inactive:
        stmt = stmt.where(Plan.is_active.is_(True))
    return list(db.scalars(stmt.order_by(Plan.reseller_id.is_not(None), Plan.sort_order, Plan.label)))


def find_plan(db: Session, key: str | None, reseller_id=None):
    if not key:
        return None
    from .models import Plan

    rows = [p for p in db.scalars(select(Plan).where(Plan.key == key))
            if p.reseller_id is None or p.reseller_id == reseller_id]
    rows.sort(key=lambda p: p.reseller_id is None)  # the reseller's own plan wins over a platform plan
    return rows[0] if rows else None


def plan_label(company: Company, db: Session | None = None) -> str:
    if db is not None and company.plan and company.plan != "custom":
        p = find_plan(db, company.plan, company.reseller_id)
        if p is not None:
            return p.label
    return "Custom" if company.modules is not None else "All modules"


def blocked_message(key: str) -> str:
    return (f"{MODULES[key][0]} isn't included in this company's plan. You can still view, print and export what's "
            "already here. Ask your administrator to add it.")


def _company(db: Session) -> Company | None:
    from .tenancy import NO_COMPANY, company_of

    cid = company_of(db)
    return db.get(Company, cid) if cid and cid != NO_COMPANY else None


def check(db: Session, user: User, key: str, accountant_free: bool = False) -> None:
    if accountant_free and user.company_role == "accountant":
        return
    if not enabled(_company(db), key):
        raise HTTPException(status.HTTP_403_FORBIDDEN, blocked_message(key))


def guard(key: str, accountant_free: bool = False, reads_too: bool = False) -> Callable[..., None]:
    """Router dependency: blocks creating and changing records when the module is off (reads still work)."""
    from .security import current_user

    def dependency(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
        if reads_too or request.method in WRITE_METHODS:
            check(db, user, key, accountant_free)

    return dependency


def data_present(db: Session, company: Company | None) -> list[str]:
    """Modules that are off but already hold records, so their pages show read-only."""
    from .models import Bill, CustomerPayment, Invoice, Item, JournalEntry

    if company is None:
        return []
    out = []
    probes = {
        "invoicing": [select(Invoice.id), select(CustomerPayment.id), select(Item.id)],
        "bills": [select(Bill.id).where(Bill.is_deleted.is_(False))],
        "advanced_accounting": [select(JournalEntry.id).where(JournalEntry.source_type == "journal")],
    }
    for key, stmts in probes.items():
        if not enabled(company, key) and any(db.scalar(s.limit(1)) is not None for s in stmts):
            out.append(key)
    return out


def seats_used(db: Session, company_id) -> int:
    """People counted against the user limit: members except the Accountant and the platform owner."""
    from sqlalchemy import func

    from .models import CompanyMember

    return db.scalar(select(func.count()).select_from(CompanyMember).join(User, User.id == CompanyMember.user_id)
                     .where(CompanyMember.company_id == company_id, CompanyMember.role != "accountant",
                            User.is_platform_admin.is_(False))) or 0
