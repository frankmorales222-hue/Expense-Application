from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db

from ..invoicing import service
from ..models import Customer, CustomerPayment, Invoice, User
from ..schemas import CustomerDetail, CustomerIn, CustomerListItem, CustomerOut
from ..security import require_roles
from . import ruleutil
from .util import current_company

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _balances(db: Session) -> tuple[dict, dict]:
    """Open and overdue balance per customer, from live invoices."""
    invoices = list(db.scalars(service.live_invoices(db).where(Invoice.is_void.is_(False))))
    paid = service.paid_map(db, [i.id for i in invoices])
    open_, overdue = {}, {}
    today = date.today()
    for inv in invoices:
        bal = Decimal(inv.total) - paid[inv.id]
        if bal <= 0:
            continue
        open_[inv.customer_id] = open_.get(inv.customer_id, Decimal("0")) + bal
        if inv.due_date < today:
            overdue[inv.customer_id] = overdue.get(inv.customer_id, Decimal("0")) + bal
    return open_, overdue


@router.get("", response_model=list[CustomerListItem])
def list_customers(include_inactive: bool = False, db: Session = Depends(get_db),
                   _: User = Depends(require_roles("admin", "approver"))) -> list[CustomerListItem]:
    stmt = select(Customer).where(Customer.company_id == current_company(db).id)
    if not include_inactive:
        stmt = stmt.where(Customer.is_active.is_(True))
    open_, overdue = _balances(db)
    return [CustomerListItem(**CustomerOut.model_validate(c).model_dump(), open_balance=open_.get(c.id, Decimal("0")),
                             overdue_balance=overdue.get(c.id, Decimal("0")))
            for c in db.scalars(stmt.order_by(Customer.name))]


@router.get("/{customer_id}", response_model=CustomerDetail)
def customer_detail(customer_id: uuid.UUID, db: Session = Depends(get_db),
                    _: User = Depends(require_roles("admin", "approver"))) -> CustomerDetail:
    from .payments import payment_out

    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    invoices = list(db.scalars(service.live_invoices(db).where(Invoice.customer_id == customer.id)
                               .order_by(Invoice.invoice_date.desc(), Invoice.created_at.desc())))
    paid = service.paid_map(db, [i.id for i in invoices])
    items = [service.list_item(i, paid[i.id]) for i in invoices]
    payments = list(db.scalars(select(CustomerPayment).where(CustomerPayment.customer_id == customer.id)
                               .order_by(CustomerPayment.payment_date.desc())))
    # Days to pay: from invoice date to the payment that finished paying it.
    last_payment: dict = {}
    for p in payments:
        for a in p.applications:
            if a.invoice_id not in last_payment or p.payment_date > last_payment[a.invoice_id]:
                last_payment[a.invoice_id] = p.payment_date
    done = [i for i in invoices if not i.is_void and paid[i.id] >= Decimal(i.total) and i.id in last_payment]
    days = [(last_payment[i.id] - i.invoice_date).days for i in done]
    on_time = [last_payment[i.id] <= i.due_date for i in done]
    unbilled = service.unbilled(db, customer.id)
    live = [i for i in items if i.status != "void"]
    return CustomerDetail(
        **CustomerOut.model_validate(customer).model_dump(),
        open_balance=sum((i.balance for i in live), Decimal("0")),
        overdue_balance=sum((i.balance for i in live if i.status == "overdue"), Decimal("0")),
        invoice_count=len(live), paid_invoice_count=len(done),
        avg_days_to_pay=round(sum(days) / len(days), 1) if days else None,
        on_time_percent=round(100 * sum(on_time) / len(on_time)) if on_time else None,
        unbilled_amount=sum((u.amount for u in unbilled), Decimal("0")), unbilled_count=len(unbilled),
        invoices=items, payments=[payment_out(db, p) for p in payments])


def _unique(db: Session, company_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> None:
    stmt = select(Customer.id).where(Customer.company_id == company_id, func.lower(Customer.name) == name.lower())
    if exclude:
        stmt = stmt.where(Customer.id != exclude)
    if db.scalar(stmt):
        raise HTTPException(status.HTTP_409_CONFLICT, "A customer with that name already exists")


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerIn, db: Session = Depends(get_db),
                    user: User = Depends(require_roles("admin", "approver"))) -> Customer:
    company = current_company(db)
    _unique(db, company.id, payload.name)
    ruleutil.term(db, payload.default_terms)
    data = payload.model_dump()
    data["custom"] = ruleutil.custom(db, "customer", payload.custom)
    customer = Customer(company_id=company.id, **data)
    db.add(customer)
    db.flush()
    audit.record(db, entity_type="customer", entity_id=customer.id, action="created", user_id=user.id,
                 changes={"name": customer.name})
    db.commit()
    return customer


@router.put("/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: uuid.UUID, payload: CustomerIn, db: Session = Depends(get_db),
                    user: User = Depends(require_roles("admin", "approver"))) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.company_id != current_company(db).id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    _unique(db, customer.company_id, payload.name, exclude=customer.id)
    ruleutil.term(db, payload.default_terms, current=customer.default_terms)
    changes = {}
    data = payload.model_dump(exclude_unset=True)
    if "custom" in data:
        data["custom"] = ruleutil.custom(db, "customer", payload.custom, before=customer.custom)
    for field, value in data.items():
        if getattr(customer, field) != value:
            changes[field] = [getattr(customer, field), value]
            setattr(customer, field, value)
    if changes:
        audit.record(db, entity_type="customer", entity_id=customer.id, action="updated", user_id=user.id,
                     changes=changes)
        db.commit()
    return customer
