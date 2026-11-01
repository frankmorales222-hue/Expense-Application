"""Shared validation for expense and bill lines (category splits)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Customer, ExpenseCategory, FinancialAccount
from ..schemas import LineIn, LineOut


def checked_lines(db: Session, lines: list[LineIn], current_categories: set[uuid.UUID] | None = None) -> Decimal:
    """Validate categories and customers (both are filtered to the current company). Returns the total."""
    if not lines:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Add at least one line")
    total = Decimal("0")
    for i, ln in enumerate(lines, start=1):
        cat = db.get(ExpenseCategory, ln.category_id)
        if cat is None or (not cat.is_active and cat.id not in (current_categories or set())):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Line {i}: category not found or inactive")
        if ln.billable and ln.customer_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Line {i}: choose the customer to bill")
        if ln.customer_id is not None and db.get(Customer, ln.customer_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Line {i}: customer not found")
        total += ln.amount
    if total >= Decimal("10000000000"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The total is too large")
    return total


def checked_payment_account(db: Session, account_id: uuid.UUID | None) -> FinancialAccount | None:
    if account_id is None:
        return None
    fa = db.get(FinancialAccount, account_id)
    if fa is None or not fa.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Payment account not found or closed")
    return fa


def lines_out(db: Session, lines) -> list[LineOut]:
    cats = {c.id: c.name for c in db.scalars(select(ExpenseCategory).where(
        ExpenseCategory.id.in_({ln.category_id for ln in lines})))} if lines else {}
    cust_ids = {ln.customer_id for ln in lines if ln.customer_id}
    customers = {c.id: c.name for c in db.scalars(select(Customer).where(Customer.id.in_(cust_ids)))} if cust_ids else {}
    return [LineOut(id=ln.id, category_id=ln.category_id, category_name=cats.get(ln.category_id, "?"),
                    description=ln.description, amount=ln.amount, billable=ln.billable, customer_id=ln.customer_id,
                    customer_name=customers.get(ln.customer_id)) for ln in lines]
