"""Receive payment: money from a customer, applied to their invoices and matched to the bank deposit."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from .. import modules
from ..database import get_db
from ..invoicing import service
from ..models import BillPayment, Customer, CustomerPayment, FinancialAccount, Invoice, PaymentApplication, Transaction, User
from ..schemas import ApplicationOut, PaymentIn, PaymentOut, PeerOut
from ..security import require_roles
from . import ruleutil
from .lines import checked_payment_account

router = APIRouter(prefix="/api/payments", tags=["payments"],
                   dependencies=[Depends(modules.guard("invoicing"))])
ROLES = ("admin", "approver")
ZERO = Decimal("0")


def payment_out(db: Session, p: CustomerPayment) -> PaymentOut:
    numbers = {i.id: i.invoice_number for i in db.scalars(select(Invoice).where(
        Invoice.id.in_({a.invoice_id for a in p.applications})))} if p.applications else {}
    account = db.get(FinancialAccount, p.account_id)
    return PaymentOut(
        id=p.id, customer_id=p.customer_id, customer_name=p.customer.name if p.customer else "",
        payment_date=p.payment_date, account_id=p.account_id, account_name=account.name if account else "?",
        amount=p.amount, method=p.method, reference=p.reference, memo=p.memo, transaction_id=p.transaction_id,
        applications=[ApplicationOut(invoice_id=a.invoice_id, invoice_number=numbers.get(a.invoice_id, "?"),
                                     amount=a.amount) for a in p.applications])


def _load(db: Session, payment_id: uuid.UUID) -> CustomerPayment:
    p = db.get(CustomerPayment, payment_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    return p


def deposit_candidates(db: Session, account_id: uuid.UUID, amount: Decimal, near: date) -> list[Transaction]:
    """Bank deposits that could be this payment: same account and amount, within 10 days, not used yet."""
    taken = select(CustomerPayment.transaction_id).where(CustomerPayment.transaction_id.is_not(None))
    taken_bills = select(BillPayment.transaction_id).where(BillPayment.transaction_id.is_not(None))
    return list(db.scalars(select(Transaction).where(
        Transaction.account_id == account_id, Transaction.amount == amount, Transaction.is_transfer.is_(False),
        Transaction.expense_id.is_(None), Transaction.review_status != "excluded",
        Transaction.id.not_in(taken), Transaction.id.not_in(taken_bills),
        Transaction.txn_date.between(near - timedelta(days=10), near + timedelta(days=10)),
    ).order_by(Transaction.txn_date)))


@router.get("", response_model=list[PaymentOut])
def list_payments(customer_id: uuid.UUID | None = None, db: Session = Depends(get_db),
                  _: User = Depends(require_roles(*ROLES))) -> list[PaymentOut]:
    stmt = select(CustomerPayment).order_by(CustomerPayment.payment_date.desc(), CustomerPayment.created_at.desc())
    if customer_id:
        stmt = stmt.where(CustomerPayment.customer_id == customer_id)
    return [payment_out(db, p) for p in db.scalars(stmt.limit(500)).unique()]


@router.get("/deposit-candidates", response_model=list[PeerOut])
def candidates(account_id: uuid.UUID, amount: Decimal, payment_date: date, db: Session = Depends(get_db),
               _: User = Depends(require_roles(*ROLES))) -> list[PeerOut]:
    account = checked_payment_account(db, account_id)
    return [PeerOut(id=t.id, account_id=t.account_id, account_name=account.name, txn_date=t.txn_date,
                    amount=t.amount, description=t.description, review_status=t.review_status)
            for t in deposit_candidates(db, account.id, amount, payment_date)]


@router.get("/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: uuid.UUID, db: Session = Depends(get_db),
                _: User = Depends(require_roles(*ROLES))) -> PaymentOut:
    return payment_out(db, _load(db, payment_id))


@router.post("", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def receive_payment(payload: PaymentIn, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(*ROLES))) -> PaymentOut:
    customer = db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Customer not found")
    account = checked_payment_account(db, payload.account_id)
    ruleutil.method(db, "received", payload.method)
    ids = [a.invoice_id for a in payload.applications]
    if len(set(ids)) != len(ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Each invoice can appear once")
    paid = service.paid_map(db, ids)
    applied = ZERO
    for a in payload.applications:
        inv = db.get(Invoice, a.invoice_id)
        if inv is None or inv.is_deleted or inv.is_void or inv.customer_id != customer.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Invoice not found for {customer.name} (or it's void)")
        balance = Decimal(inv.total) - paid[inv.id]
        if a.amount > balance:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Invoice {inv.invoice_number} only has {balance:,.2f} open")
        applied += a.amount
    if applied != payload.amount:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Apply the whole payment: {applied:,.2f} applied of {payload.amount:,.2f} received")
    txn = None
    if payload.transaction_id:
        ok = {t.id for t in deposit_candidates(db, account.id, payload.amount, payload.payment_date)}
        if payload.transaction_id not in ok:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "That bank deposit doesn't match this payment's account and amount")
        txn = db.get(Transaction, payload.transaction_id)
    p = CustomerPayment(id=uuid.uuid4(), customer_id=customer.id, payment_date=payload.payment_date,
                        account_id=account.id, amount=payload.amount, method=payload.method,
                        reference=payload.reference, memo=payload.memo, transaction_id=txn.id if txn else None,
                        created_by=user.id)
    p.customer = customer
    p.applications = [PaymentApplication(id=uuid.uuid4(), invoice_id=a.invoice_id, amount=a.amount)
                      for a in payload.applications]
    db.add(p)
    if txn is not None:
        # Matching the deposit is its review, as in QuickBooks; it now belongs to this payment.
        if txn.review_status != "approved":
            txn.review_status, txn.approved_by, txn.approved_at = "approved", user.id, datetime.now(timezone.utc)
        txn.duplicate_of_id = None
        if txn.customer_id is None:
            txn.customer_id = customer.id
    db.flush()
    audit.record(db, entity_type="customer_payment", entity_id=p.id, action="created", user_id=user.id,
                 changes={"customer": customer.name, "amount": payload.amount, "account": account.name,
                          "date": payload.payment_date, "invoices": [str(i) for i in ids],
                          "matched_transaction": txn.id if txn else None})
    for a in payload.applications:
        audit.record(db, entity_type="invoice", entity_id=a.invoice_id, action="payment_received", user_id=user.id,
                     changes={"amount": a.amount, "date": payload.payment_date})
    db.commit()
    db.refresh(p)
    return payment_out(db, p)


@router.delete("/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payment(payment_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(require_roles(*ROLES))) -> Response:
    p = _load(db, payment_id)
    if p.transaction_id:
        txn = db.get(Transaction, p.transaction_id)
        if txn is not None:
            # The deposit goes back to For review so it can be matched or categorized again.
            txn.review_status, txn.approved_by, txn.approved_at = "unreviewed", None, None
    invoices = [a.invoice_id for a in p.applications]
    db.delete(p)
    audit.record(db, entity_type="customer_payment", entity_id=p.id, action="deleted", user_id=user.id,
                 changes={"amount": p.amount, "date": p.payment_date})
    for inv_id in invoices:
        audit.record(db, entity_type="invoice", entity_id=inv_id, action="payment_removed", user_id=user.id,
                     changes={"amount": p.amount, "date": p.payment_date})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
