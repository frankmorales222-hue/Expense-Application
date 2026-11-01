"""Sales figures and reports: dashboard summary, A/R aging, sales by customer."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..invoicing import service
from ..models import (
    Customer, CustomerPayment, Invoice, JournalEntry, JournalLine, LedgerAccount, PaymentApplication, Transaction, User,
)
from ..schemas import AgingOut, AgingRow, SalesByCustomerOut, SalesByCustomerRow, SalesSummaryOut
from ..security import require_roles

router = APIRouter(prefix="/api/sales", tags=["sales"])
READ = require_roles("admin", "approver")
ZERO = Decimal("0")


@router.get("/summary", response_model=SalesSummaryOut)
def summary(db: Session = Depends(get_db), _: User = Depends(READ)) -> SalesSummaryOut:
    invoices = list(db.scalars(service.live_invoices(db).where(Invoice.is_void.is_(False))))
    paid = service.paid_map(db, [i.id for i in invoices])
    items = [service.list_item(i, paid[i.id]) for i in invoices]
    unpaid = [i for i in items if i.status not in ("paid", "void")]
    overdue = [i for i in unpaid if i.status == "overdue"]
    since = date.today() - timedelta(days=30)
    recent = sum((Decimal(p.amount) for p in db.scalars(
        select(CustomerPayment).where(CustomerPayment.payment_date >= since))), ZERO)
    deposits = len(list(db.scalars(select(Transaction.id).where(
        Transaction.review_status == "unreviewed", Transaction.amount > 0, Transaction.is_transfer.is_(False)))))
    return SalesSummaryOut(open_total=sum((i.balance for i in unpaid), ZERO), open_count=len(unpaid),
                           overdue_total=sum((i.balance for i in overdue), ZERO), overdue_count=len(overdue),
                           not_sent_count=sum(1 for i in unpaid if i.status == "not_sent"), paid_last_30=recent,
                           deposits_to_match=deposits)


def _bucket(days_late: int) -> str:
    if days_late <= 0:
        return "current"
    if days_late <= 30:
        return "d1_30"
    if days_late <= 60:
        return "d31_60"
    if days_late <= 90:
        return "d61_90"
    return "d91_plus"


@router.get("/aging", response_model=AgingOut)
def ar_aging(as_of: date, db: Session = Depends(get_db), _: User = Depends(READ)) -> AgingOut:
    """What each customer owes on the date, by how late it is (QuickBooks "A/R Aging Summary")."""
    invoices = list(db.scalars(service.live_invoices(db).where(Invoice.is_void.is_(False),
                                                                Invoice.invoice_date <= as_of)))
    paid: dict = defaultdict(lambda: ZERO)
    if invoices:
        for inv_id, amount in db.execute(
                select(PaymentApplication.invoice_id, PaymentApplication.amount)
                .join(CustomerPayment, CustomerPayment.id == PaymentApplication.payment_id)
                .where(PaymentApplication.invoice_id.in_([i.id for i in invoices]),
                       CustomerPayment.payment_date <= as_of)):
            paid[inv_id] += Decimal(amount)
    names = {c.id: c.name for c in db.scalars(select(Customer))}
    rows: dict = {}
    for inv in invoices:
        balance = Decimal(inv.total) - paid[inv.id]
        if balance <= 0:
            continue
        row = rows.setdefault(inv.customer_id, {"current": ZERO, "d1_30": ZERO, "d31_60": ZERO, "d61_90": ZERO,
                                                "d91_plus": ZERO})
        row[_bucket((as_of - inv.due_date).days)] += balance
    out = [AgingRow(customer_id=cid, customer_name=names.get(cid, "?"), total=sum(r.values(), ZERO), **r)
           for cid, r in rows.items()]
    out.sort(key=lambda r: r.customer_name.lower())
    keys = ("current", "d1_30", "d31_60", "d61_90", "d91_plus", "total")
    totals = {k: sum((getattr(r, k) for r in out), ZERO) for k in keys}
    import uuid as _uuid

    return AgingOut(as_of=as_of, rows=out,
                    totals=AgingRow(customer_id=_uuid.UUID(int=0), customer_name="Total", **totals))


@router.get("/by-customer", response_model=SalesByCustomerOut)
def sales_by_customer(date_from: date, date_to: date, db: Session = Depends(get_db),
                      _: User = Depends(READ)) -> SalesByCustomerOut:
    """Income in the period by customer, from the books (invoices and customer-tagged deposits)."""
    if date_to < date_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The end date is before the start date")
    rows = db.execute(
        select(JournalLine.customer_id, JournalLine.debit, JournalLine.credit)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(LedgerAccount, LedgerAccount.id == JournalLine.account_id)
        .where(LedgerAccount.type == "income", JournalEntry.entry_date.between(date_from, date_to))).all()
    sums: dict = defaultdict(lambda: ZERO)
    for cid, debit, credit in rows:
        sums[cid] += Decimal(credit) - Decimal(debit)
    names = {c.id: c.name for c in db.scalars(select(Customer))}
    out = [SalesByCustomerRow(customer_id=cid, customer_name=names.get(cid, "?") if cid else "No customer",
                              amount=amount) for cid, amount in sums.items() if amount != 0]
    out.sort(key=lambda r: (r.customer_id is None, -r.amount))
    return SalesByCustomerOut(date_from=date_from, date_to=date_to, rows=out,
                              total=sum((r.amount for r in out), ZERO))
