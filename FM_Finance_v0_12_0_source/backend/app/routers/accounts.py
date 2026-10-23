from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..banking.engine import account_balances
from ..database import get_db
from ..models import FinancialAccount, Transaction, User
from ..schemas import AccountIn, AccountOut
from ..security import require_roles
from .util import current_company

router = APIRouter(prefix="/api/accounts", tags=["accounts"])
BANKING_ROLES = ("admin", "approver")


def to_out(db: Session, accounts: list[FinancialAccount]) -> list[AccountOut]:
    balances = account_balances(db)
    counts = dict(db.execute(
        select(Transaction.account_id, func.count(Transaction.id))
        .where(Transaction.review_status == "unreviewed").group_by(Transaction.account_id)
    ).all())
    totals = dict(db.execute(
        select(Transaction.account_id, func.count(Transaction.id)).group_by(Transaction.account_id)
    ).all())
    out = []
    for a in accounts:
        item = AccountOut.model_validate(a)
        item.balance = a.opening_balance + balances.get(a.id, 0)
        item.unreviewed_count = counts.get(a.id, 0)
        item.transaction_count = totals.get(a.id, 0)
        item.has_csv_profile = bool(a.csv_profile)
        out.append(item)
    return out


def load_account(db: Session, account_id: uuid.UUID) -> FinancialAccount:
    account = db.get(FinancialAccount, account_id)
    if account is None or account.company_id != current_company(db).id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return account


@router.get("", response_model=list[AccountOut])
def list_accounts(include_inactive: bool = False, db: Session = Depends(get_db),
                  _: User = Depends(require_roles(*BANKING_ROLES))) -> list[AccountOut]:
    stmt = select(FinancialAccount).where(FinancialAccount.company_id == current_company(db).id)
    if not include_inactive:
        stmt = stmt.where(FinancialAccount.is_active.is_(True))
    return to_out(db, list(db.scalars(stmt.order_by(FinancialAccount.kind, FinancialAccount.name))))


def _check_name(db: Session, company_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> None:
    stmt = select(FinancialAccount.id).where(FinancialAccount.company_id == company_id,
                                             func.lower(FinancialAccount.name) == name.lower())
    if exclude:
        stmt = stmt.where(FinancialAccount.id != exclude)
    if db.scalar(stmt):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that name already exists")


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountIn, db: Session = Depends(get_db),
                   user: User = Depends(require_roles("admin"))) -> AccountOut:
    company = current_company(db)
    _check_name(db, company.id, payload.name)
    account = FinancialAccount(company_id=company.id, currency=company.base_currency, **payload.model_dump())
    db.add(account)
    db.flush()
    audit.record(db, entity_type="account", entity_id=account.id, action="created", user_id=user.id,
                 changes=payload.model_dump())
    db.commit()
    return to_out(db, [account])[0]


@router.put("/{account_id}", response_model=AccountOut)
def update_account(account_id: uuid.UUID, payload: AccountIn, db: Session = Depends(get_db),
                   user: User = Depends(require_roles("admin"))) -> AccountOut:
    account = load_account(db, account_id)
    _check_name(db, account.company_id, payload.name, exclude=account.id)
    changes = {}
    for field, value in payload.model_dump().items():
        if getattr(account, field) != value:
            changes[field] = [getattr(account, field), value]
            setattr(account, field, value)
    if changes:
        audit.record(db, entity_type="account", entity_id=account.id, action="updated", user_id=user.id,
                     changes=changes)
        db.commit()
    return to_out(db, [account])[0]


@router.delete("/{account_id}/csv-profile", status_code=status.HTTP_204_NO_CONTENT)
def forget_csv_profile(account_id: uuid.UUID, db: Session = Depends(get_db),
                       _: User = Depends(require_roles("admin"))) -> Response:
    account = load_account(db, account_id)
    account.csv_profile = None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
