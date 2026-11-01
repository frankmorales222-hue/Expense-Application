"""Posting rules: turn source records into balanced journal entries.

Each source (expense, bank transaction, bill, bill payment, bank opening balance) owns the entries
recorded under its (source_type, source_id). Reposting deletes those entries and writes them again
from the record as it is now, so the ledger always matches the records. Manual journal entries
(source_type "journal") are never touched here.

Sign convention for bank/card transactions: a negative amount is money out of that account. On the
account's own ledger line that is always a credit (cash goes down, or a card balance owed goes up),
and a positive amount is always a debit, whatever the account type.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import (
    Bill, BillPayment, Company, CustomerPayment, Expense, ExpenseCategory, FinancialAccount, Invoice, JournalEntry,
    JournalLine, LedgerAccount, Transaction,
)
from .chart import ledger_for_bank, ledger_for_category, system_account

ZERO = Decimal("0")
POSTED_EXPENSE_STATUSES = ("approved", "paid")


class ClosedPeriod(ValueError):
    """A change would alter the books on or before the company's closing date."""


class Unbalanced(ValueError):
    pass


@dataclass
class Line:
    account_id: uuid.UUID
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    description: str | None = None
    vendor_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None


def _write(db: Session, company_id: uuid.UUID, source_type: str, source_id: uuid.UUID | None, entry_date: date,
           lines: list[Line], memo: str | None = None, number: str | None = None,
           created_by: uuid.UUID | None = None) -> JournalEntry:
    lines = [ln for ln in lines if ln.debit or ln.credit]
    debits = sum((ln.debit for ln in lines), ZERO)
    credits = sum((ln.credit for ln in lines), ZERO)
    if debits != credits or not lines:
        raise Unbalanced(f"{source_type} entry doesn't balance: debits {debits} credits {credits}")
    entry = JournalEntry(id=uuid.uuid4(), company_id=company_id, entry_date=entry_date, source_type=source_type,
                         source_id=source_id, memo=(memo or "")[:500] or None, number=number, created_by=created_by)
    for i, ln in enumerate(lines):
        entry.lines.append(JournalLine(
            id=uuid.uuid4(), company_id=company_id, line_no=i, account_id=ln.account_id, debit=ln.debit,
            credit=ln.credit, description=(ln.description or "")[:500] or None, vendor_id=ln.vendor_id,
            customer_id=ln.customer_id))
    db.add(entry)
    return entry


# ---------------------------------------------------------------- helpers
def _closing(db: Session, company_id: uuid.UUID) -> date | None:
    return db.scalar(select(Company.closing_date).where(Company.id == company_id))


def check_open(db: Session, company_id: uuid.UUID, *dates: date | None) -> None:
    closing = _closing(db, company_id)
    if closing is None:
        return
    for d in dates:
        if d is not None and d <= closing:
            raise ClosedPeriod(f"The books are closed through {closing:%b %d, %Y}. "
                               "An owner can change the closing date in Settings.")


def _existing(db: Session, company_id: uuid.UUID, source_types: tuple[str, ...], source_id: uuid.UUID) -> list[JournalEntry]:
    return list(db.scalars(select(JournalEntry).where(
        JournalEntry.company_id == company_id, JournalEntry.source_type.in_(source_types),
        JournalEntry.source_id == source_id)))


def _replace(db: Session, company_id: uuid.UUID, source_types: tuple[str, ...], source_id: uuid.UUID,
             new_dates: list[date]) -> None:
    """Remove a source's entries after checking neither the old nor the new dates are closed."""
    old = _existing(db, company_id, source_types, source_id)
    check_open(db, company_id, *[e.entry_date for e in old], *new_dates)
    for e in old:
        db.delete(e)
    db.flush()


def category_account(db: Session, cat_id: uuid.UUID | None, company_id: uuid.UUID, fallback: str) -> uuid.UUID:
    cat = db.get(ExpenseCategory, cat_id) if cat_id else None
    if cat is None or cat.company_id != company_id:
        return system_account(db, company_id, fallback).id
    if cat.ledger_account_id is None:
        acct = ledger_for_category(cat)
        db.add(acct)
        cat.ledger_account_id = acct.id
        db.flush()
    return cat.ledger_account_id


def bank_account(db: Session, fa_id: uuid.UUID | None, company_id: uuid.UUID) -> uuid.UUID | None:
    fa = db.get(FinancialAccount, fa_id) if fa_id else None
    if fa is None or fa.company_id != company_id:
        return None
    if fa.ledger_account_id is None:
        acct = ledger_for_bank(fa)
        db.add(acct)
        fa.ledger_account_id = acct.id
        db.flush()
    return fa.ledger_account_id


def expense_is_posted(e: Expense | None) -> bool:
    return e is not None and not e.is_deleted and e.status in POSTED_EXPENSE_STATUSES


# ---------------------------------------------------------------- sources
def post_expense(db: Session, expense_id: uuid.UUID, company_id: uuid.UUID) -> None:
    e = db.get(Expense, expense_id)
    dates: list[date] = []
    plan: list[tuple[str, date, list[Line], str | None]] = []
    if expense_is_posted(e) and e.company_id == company_id:
        debit_lines = [
            Line(category_account(db, ln.category_id, company_id, "uncategorized_expense"), debit=Decimal(ln.amount),
                 description=ln.description or e.description, vendor_id=e.vendor_id, customer_id=ln.customer_id)
            for ln in e.lines
        ] or [Line(category_account(db, e.category_id, company_id, "uncategorized_expense"),
                   debit=Decimal(e.amount), description=e.description, vendor_id=e.vendor_id)]
        total = sum((ln.debit for ln in debit_lines), ZERO)
        if e.is_reimbursable:
            credit_acct = system_account(db, company_id, "reimbursements_owed").id
        else:
            credit_acct = (bank_account(db, e.payment_account_id, company_id)
                           or system_account(db, company_id, "payment_account_not_set").id)
        plan.append(("expense", e.expense_date, debit_lines + [
            Line(credit_acct, credit=total, description=e.description, vendor_id=e.vendor_id)], e.description))
        dates.append(e.expense_date)
        # A paid reimbursement moves the amount out of the account it was repaid from.
        repaid_from = bank_account(db, e.payment_account_id, company_id) if e.is_reimbursable else None
        if e.status == "paid" and repaid_from:
            paid_on = e.paid_at.date() if e.paid_at else e.expense_date
            owed = system_account(db, company_id, "reimbursements_owed").id
            plan.append(("reimbursement", paid_on, [
                Line(owed, debit=total, description=f"Reimbursed: {e.description}"),
                Line(repaid_from, credit=total, description=f"Reimbursed: {e.description}")], e.description))
            dates.append(paid_on)
    _replace(db, company_id, ("expense", "reimbursement"), expense_id, dates)
    for source_type, d, lines, memo in plan:
        _write(db, company_id, source_type, expense_id, d, lines, memo)


def _linked_elsewhere(db: Session, t: Transaction) -> bool:
    """A bank transaction that is the payment of an expense or bill is recorded by that record instead."""
    if t.expense_id and expense_is_posted(db.get(Expense, t.expense_id)):
        return True
    if db.scalar(select(BillPayment.id).where(BillPayment.transaction_id == t.id)) is not None:
        return True
    return db.scalar(select(CustomerPayment.id).where(CustomerPayment.transaction_id == t.id)) is not None


def post_transaction(db: Session, txn_id: uuid.UUID, company_id: uuid.UUID) -> None:
    t = db.get(Transaction, txn_id)
    plan: list[Line] = []
    if (t is not None and t.company_id == company_id and t.review_status == "approved"
            and not _linked_elsewhere(db, t)):
        own = bank_account(db, t.account_id, company_id)
        amount = abs(Decimal(t.amount))
        if t.is_transfer:
            peer = db.get(Transaction, t.transfer_peer_id) if t.transfer_peer_id else None
            # The money-out side records the whole transfer; the money-in side records nothing.
            if peer is not None and t.amount < 0:
                plan = [Line(bank_account(db, peer.account_id, company_id), debit=amount, description=t.description),
                        Line(own, credit=amount, description=t.description)]
        else:
            fallback = "uncategorized_income" if t.amount > 0 else "uncategorized_expense"
            allocated = db.get(LedgerAccount, t.allocation_account_id) if t.allocation_account_id else None
            other = (allocated.id if allocated is not None and allocated.company_id == company_id
                     else category_account(db, t.category_id, company_id, fallback))
            if t.amount < 0:
                plan = [Line(other, debit=amount, description=t.description, vendor_id=t.vendor_id,
                             customer_id=t.customer_id),
                        Line(own, credit=amount, description=t.description, vendor_id=t.vendor_id)]
            else:
                plan = [Line(own, debit=amount, description=t.description, customer_id=t.customer_id),
                        Line(other, credit=amount, description=t.description, vendor_id=t.vendor_id,
                             customer_id=t.customer_id)]
    _replace(db, company_id, ("transaction",), txn_id, [t.txn_date] if plan else [])
    if plan:
        _write(db, company_id, "transaction", txn_id, t.txn_date, plan, t.description)


def post_opening_balance(db: Session, fa_id: uuid.UUID, company_id: uuid.UUID) -> None:
    fa = db.get(FinancialAccount, fa_id)
    plan: list[Line] = []
    when: date | None = None
    if fa is not None and fa.company_id == company_id and Decimal(fa.opening_balance) != 0:
        # Fixed date (never derived from activity, so it can't move when statements are imported later).
        when = fa.opening_date or (fa.created_at.date() if fa.created_at else date.today())
        own = bank_account(db, fa.id, company_id)
        obe = system_account(db, company_id, "opening_balance_equity").id
        amount = abs(Decimal(fa.opening_balance))
        if fa.opening_balance > 0:
            plan = [Line(own, debit=amount, description="Opening balance"), Line(obe, credit=amount)]
        else:
            plan = [Line(obe, debit=amount), Line(own, credit=amount, description="Opening balance")]
    _replace(db, company_id, ("opening_balance",), fa_id, [when] if when else [])
    if plan:
        _write(db, company_id, "opening_balance", fa_id, when, plan, f"Opening balance: {fa.name}")


def post_bill(db: Session, bill_id: uuid.UUID, company_id: uuid.UUID) -> None:
    b = db.get(Bill, bill_id)
    plan: list[Line] = []
    if b is not None and b.company_id == company_id and not b.is_deleted:
        plan = [Line(category_account(db, ln.category_id, company_id, "uncategorized_expense"),
                     debit=Decimal(ln.amount), description=ln.description or b.memo, vendor_id=b.vendor_id,
                     customer_id=ln.customer_id) for ln in b.lines]
        total = sum((ln.debit for ln in plan), ZERO)
        plan.append(Line(system_account(db, company_id, "accounts_payable").id, credit=total,
                         description=f"Bill {b.bill_number or ''}".strip(), vendor_id=b.vendor_id))
    _replace(db, company_id, ("bill",), bill_id, [b.bill_date] if plan else [])
    if plan:
        _write(db, company_id, "bill", bill_id, b.bill_date, plan, f"Bill {b.bill_number or ''}".strip())


def post_bill_payment(db: Session, payment_id: uuid.UUID, company_id: uuid.UUID) -> None:
    p = db.get(BillPayment, payment_id)
    plan: list[Line] = []
    bill = db.get(Bill, p.bill_id) if p is not None else None
    if p is not None and bill is not None and not bill.is_deleted and p.company_id == company_id:
        ap = system_account(db, company_id, "accounts_payable").id
        amount = Decimal(p.amount)
        plan = [Line(ap, debit=amount, description=f"Payment for bill {bill.bill_number or ''}".strip(),
                     vendor_id=bill.vendor_id),
                Line(bank_account(db, p.account_id, company_id), credit=amount, vendor_id=bill.vendor_id,
                     description=p.memo or f"Bill payment {bill.vendor.name if bill.vendor else ''}".strip())]
    _replace(db, company_id, ("bill_payment",), payment_id, [p.payment_date] if plan else [])
    if plan:
        _write(db, company_id, "bill_payment", payment_id, p.payment_date, plan,
               f"Bill payment {bill.bill_number or ''}".strip())


def post_invoice(db: Session, invoice_id: uuid.UUID, company_id: uuid.UUID) -> None:
    inv = db.get(Invoice, invoice_id)
    plan: list[Line] = []
    if inv is not None and inv.company_id == company_id and not inv.is_deleted and not inv.is_void:
        label = f"Invoice {inv.invoice_number}"
        for ln in inv.lines:
            acct = (category_account(db, ln.category_id, company_id, "uncategorized_income") if ln.category_id
                    else system_account(db, company_id, "billable_expense_income").id)
            plan.append(Line(acct, credit=Decimal(ln.amount), description=ln.description or label,
                             customer_id=inv.customer_id))
        total = sum((ln.credit for ln in plan), ZERO)
        plan.insert(0, Line(system_account(db, company_id, "accounts_receivable").id, debit=total, description=label,
                            customer_id=inv.customer_id))
    _replace(db, company_id, ("invoice",), invoice_id, [inv.invoice_date] if plan else [])
    if plan:
        _write(db, company_id, "invoice", invoice_id, inv.invoice_date, plan,
               f"Invoice {inv.invoice_number} · {inv.customer.name if inv.customer else ''}".strip(" ·"))


def post_customer_payment(db: Session, payment_id: uuid.UUID, company_id: uuid.UUID) -> None:
    p = db.get(CustomerPayment, payment_id)
    plan: list[Line] = []
    if p is not None and p.company_id == company_id:
        amount = Decimal(p.amount)
        label = f"Payment from {p.customer.name}" if p.customer else "Customer payment"
        plan = [Line(bank_account(db, p.account_id, company_id), debit=amount, description=p.memo or label,
                     customer_id=p.customer_id),
                Line(system_account(db, company_id, "accounts_receivable").id, credit=amount, description=label,
                     customer_id=p.customer_id)]
    _replace(db, company_id, ("customer_payment",), payment_id, [p.payment_date] if plan else [])
    if plan:
        _write(db, company_id, "customer_payment", payment_id, p.payment_date, plan,
               (f"{p.customer.name if p.customer else 'Customer'} payment" + (f" #{p.reference}" if p.reference else "")))


POSTERS = {
    "expense": post_expense,
    "transaction": post_transaction,
    "opening_balance": post_opening_balance,
    "bill": post_bill,
    "bill_payment": post_bill_payment,
    "invoice": post_invoice,
    "customer_payment": post_customer_payment,
}
