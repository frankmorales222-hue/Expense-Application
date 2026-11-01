"""Bank rules (v0.10.0): a company's own rules for categorizing bank transactions, checked before the built-in
suggestions. Example: description contains "ADP" -> Payroll, payee ADP, approve automatically."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..banking import engine
from ..database import get_db
from ..models import BankRule, Customer, ExpenseCategory, FinancialAccount, Transaction, User
from ..security import require_roles
from .util import current_company

router = APIRouter(prefix="/api/bank-rules", tags=["bank rules"])
ROLES = ("admin", "approver")


class BankRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    priority: int = Field(default=100, ge=1, le=10000)
    is_active: bool = True
    match_type: Literal["contains", "starts_with", "equals", "not_contains"] = "contains"
    match_text: str = Field(min_length=1, max_length=200)
    direction: Literal["any", "in", "out"] = "any"
    amount_min: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    amount_max: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    account_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    vendor_name: str | None = Field(default=None, max_length=255)
    customer_id: uuid.UUID | None = None
    memo: str | None = Field(default=None, max_length=500)
    auto_approve: bool = False

    @field_validator("name", "match_text", "vendor_name", "memo")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return (v.strip() or None) if isinstance(v, str) else v


class BankRuleOut(BankRuleIn):
    id: uuid.UUID
    times_used: int
    category_name: str | None = None
    account_name: str | None = None
    customer_name: str | None = None
    would_match: int = 0  # transactions waiting for review that this rule matches now


def _out(db: Session, r: BankRule, waiting: list[Transaction] | None = None) -> BankRuleOut:
    cat = db.get(ExpenseCategory, r.category_id) if r.category_id else None
    acct = db.get(FinancialAccount, r.account_id) if r.account_id else None
    cust = db.get(Customer, r.customer_id) if r.customer_id else None
    return BankRuleOut(
        id=r.id, name=r.name, priority=r.priority, is_active=r.is_active, match_type=r.match_type,
        match_text=r.match_text, direction=r.direction, amount_min=r.amount_min, amount_max=r.amount_max,
        account_id=r.account_id, category_id=r.category_id, vendor_name=r.vendor_name, customer_id=r.customer_id,
        memo=r.memo, auto_approve=r.auto_approve, times_used=r.times_used or 0,
        category_name=cat.name if cat else None, account_name=acct.name if acct else None,
        customer_name=cust.name if cust else None,
        would_match=sum(1 for t in (waiting or []) if engine.rule_matches(r, t)))


def _waiting(db: Session) -> list[Transaction]:
    return list(db.scalars(select(Transaction).where(Transaction.review_status == "unreviewed",
                                                     Transaction.is_transfer.is_(False))))


def _check(db: Session, p: BankRuleIn) -> None:
    if p.category_id is None and not p.vendor_name and p.customer_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a category, payee or customer to set")
    if p.amount_min is not None and p.amount_max is not None and p.amount_min > p.amount_max:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The smallest amount is larger than the largest")
    for model, value, what in ((ExpenseCategory, p.category_id, "Category"), (FinancialAccount, p.account_id, "Account"),
                               (Customer, p.customer_id, "Customer")):
        if value is not None and db.get(model, value) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{what} not found")


@router.get("", response_model=list[BankRuleOut])
def list_rules(db: Session = Depends(get_db), _: User = Depends(require_roles(*ROLES))) -> list[BankRuleOut]:
    waiting = _waiting(db)
    rows = db.scalars(select(BankRule).order_by(BankRule.priority, BankRule.created_at))
    return [_out(db, r, waiting) for r in rows]


@router.post("", response_model=BankRuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(payload: BankRuleIn, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*ROLES))) -> BankRuleOut:
    _check(db, payload)
    r = BankRule(id=uuid.uuid4(), company_id=current_company(db).id, **payload.model_dump())
    db.add(r)
    db.flush()
    audit.record(db, entity_type="bank_rule", entity_id=r.id, action="created", user_id=user.id,
                 changes={"name": r.name, "match": f"{r.match_type} {r.match_text}"})
    db.commit()
    return _out(db, r, _waiting(db))


@router.put("/{rule_id}", response_model=BankRuleOut)
def update_rule(rule_id: uuid.UUID, payload: BankRuleIn, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*ROLES))) -> BankRuleOut:
    r = db.get(BankRule, rule_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    _check(db, payload)
    for k, v in payload.model_dump().items():
        setattr(r, k, v)
    audit.record(db, entity_type="bank_rule", entity_id=r.id, action="updated", user_id=user.id,
                 changes={"name": r.name})
    db.commit()
    return _out(db, r, _waiting(db))


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_roles(*ROLES))) -> Response:
    r = db.get(BankRule, rule_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    audit.record(db, entity_type="bank_rule", entity_id=r.id, action="deleted", user_id=user.id, changes={"name": r.name})
    db.delete(r)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ApplyOut(BaseModel):
    matched: int
    approved: int


@router.post("/apply", response_model=ApplyOut)
def apply_rules(db: Session = Depends(get_db), user: User = Depends(require_roles(*ROLES))) -> ApplyOut:
    """Run the rules over everything waiting for review now (new imports get them automatically)."""
    waiting = _waiting(db)
    engine.suggest(db, waiting)
    matched = sum(1 for t in waiting if (t.suggestion_reason or "").startswith("Your rule:"))
    db.flush()
    approved = engine.approve_by_rules(db, user)
    db.commit()
    return ApplyOut(matched=matched, approved=approved)
