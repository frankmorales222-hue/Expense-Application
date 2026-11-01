"""Owner money without journal-entry guesswork (v0.11.0).

Loans and repayments are balance-sheet movements, not income or expenses. Personally paid business expenses
continue to use the existing reimbursable-expense workflow; this page brings both balances together.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..banking import engine
from ..banking.normalize import merchant_key
from ..database import get_db
from ..ledger import reports
from ..ledger.chart import system_account
from ..ledger.posting import Line, _write, check_open
from ..models import FinancialAccount, JournalEntry, JournalLine, LedgerAccount, Transaction, User
from ..schemas import OwnerFundsActivity, OwnerFundsIn, OwnerFundsOut
from ..security import require_roles
from .util import current_company

router = APIRouter(prefix="/api/owner-funds", tags=["owner funds"])
READ = require_roles("admin", "approver")
WRITE = require_roles("admin", "approver")
ZERO = Decimal("0")


def _balances(db: Session, company_id: uuid.UUID, due_id: uuid.UUID,
              reimburse_id: uuid.UUID) -> tuple[Decimal, Decimal]:
    raw = reports.raw_balances(db, company_id)
    due = db.get(LedgerAccount, due_id)
    reimburse = db.get(LedgerAccount, reimburse_id)
    assert due is not None and reimburse is not None
    dd, dc = raw.get(due_id, (ZERO, ZERO))
    rd, rc = raw.get(reimburse_id, (ZERO, ZERO))
    return reports.signed(due, dd, dc), reports.signed(reimburse, rd, rc)


def _out(db: Session) -> OwnerFundsOut:
    company = current_company(db)
    due = system_account(db, company.id, "due_to_owner")
    reimburse = system_account(db, company.id, "reimbursements_owed")
    loan_balance, reimbursement_balance = _balances(db, company.id, due.id, reimburse.id)
    rows = db.execute(
        select(JournalLine, JournalEntry).join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalLine.account_id.in_((due.id, reimburse.id)))
        .order_by(JournalEntry.entry_date.desc(), JournalEntry.created_at.desc()).limit(100)
    ).all()
    activity = []
    for line, entry in rows:
        loan = line.account_id == due.id
        change = Decimal(line.credit) - Decimal(line.debit)  # liabilities increase with a credit
        activity.append(OwnerFundsActivity(
            entry_id=entry.id, entry_date=entry.entry_date, account="loan" if loan else "reimbursement",
            source_type=entry.source_type, source_id=entry.source_id,
            description=line.description or entry.memo or ("Owner loan" if loan else "Personally paid expense"),
            change=change))
    return OwnerFundsOut(
        due_to_owner_account_id=due.id, reimbursements_account_id=reimburse.id,
        loan_balance=loan_balance, reimbursement_balance=reimbursement_balance,
        total_owed=loan_balance + reimbursement_balance, activity=activity)


@router.get("", response_model=OwnerFundsOut)
def summary(db: Session = Depends(get_db), _: User = Depends(READ)) -> OwnerFundsOut:
    return _out(db)


def _bank(db: Session, account_id: uuid.UUID | None, company_id: uuid.UUID) -> FinancialAccount:
    account = db.get(FinancialAccount, account_id) if account_id else None
    if account is None or account.company_id != company_id or not account.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose an active business bank account")
    if account.kind == "credit_card":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Choose the bank account that received or sent the money")
    return account


@router.post("", response_model=OwnerFundsOut, status_code=status.HTTP_201_CREATED)
def record(payload: OwnerFundsIn, db: Session = Depends(get_db), user: User = Depends(WRITE)) -> OwnerFundsOut:
    company = current_company(db)
    due = system_account(db, company.id, "due_to_owner")
    amount = Decimal(payload.amount)
    memo = (payload.memo or "").strip()

    if payload.action == "opening_balance":
        if payload.transaction_id or payload.account_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "An opening-balance reclassification doesn't use a bank transaction")
        obe = system_account(db, company.id, "opening_balance_equity")
        raw = reports.raw_balances(db, company.id)
        d, c = raw.get(obe.id, (ZERO, ZERO))
        available = reports.signed(obe, d, c)
        if amount > available:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Opening Balance Equity only has {available:,.2f} available to reclassify")
        check_open(db, company.id, payload.entry_date)
        label = memo or "Opening balance funded by owner"
        entry = _write(db, company.id, "owner_funds", None, payload.entry_date, [
            Line(obe.id, debit=amount, description=label),
            Line(due.id, credit=amount, description=label),
        ], label, created_by=user.id)
        entry.source_id = entry.id
        audit.record(db, entity_type="owner_funds", entity_id=entry.id, action="opening_balance_reclassified",
                     user_id=user.id, changes={"amount": amount})
        db.commit()
        return _out(db)

    reimburse = system_account(db, company.id, "reimbursements_owed")
    loan_balance, _ = _balances(db, company.id, due.id, reimburse.id)
    if payload.action == "repayment" and amount > loan_balance:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"The business only owes the owner {loan_balance:,.2f} on loans")

    wanted = amount if payload.action == "loan" else -amount
    if payload.transaction_id:
        txn = db.get(Transaction, payload.transaction_id)
        if txn is None or txn.company_id != company.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank transaction not found")
        if txn.review_status != "unreviewed" or txn.is_transfer or txn.expense_id:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Choose an unreviewed bank transaction that isn't already linked")
        if Decimal(txn.amount) != wanted:
            direction = "deposit" if wanted > 0 else "withdrawal"
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Choose a {direction} for exactly {amount:,.2f}")
        if payload.account_id and payload.account_id != txn.account_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "The selected bank account doesn't match the transaction")
        check_open(db, company.id, txn.txn_date)
    else:
        account = _bank(db, payload.account_id, company.id)
        check_open(db, company.id, payload.entry_date)
        description = memo or ("Owner loan to business" if payload.action == "loan" else "Repayment to owner")
        txn = Transaction(
            id=uuid.uuid4(), company_id=company.id, account_id=account.id, source="manual",
            txn_date=payload.entry_date, amount=wanted, description=description,
            normalized=merchant_key(description), memo=memo or None, fingerprint=f"manual:{uuid.uuid4().hex}")
        db.add(txn)

    txn.category_id = None
    txn.suggested_category_id = None
    txn.allocation_account_id = due.id
    txn.confidence = 100
    txn.suggestion_reason = "Owner loan" if payload.action == "loan" else "Owner loan repayment"
    if memo:
        txn.memo = memo
    engine.approve(db, txn, user, learn=False)
    audit.record(db, entity_type="owner_funds", entity_id=txn.id,
                 action="loan_recorded" if payload.action == "loan" else "repayment_recorded",
                 user_id=user.id, changes={"amount": amount, "bank_transaction": payload.transaction_id})
    db.commit()
    return _out(db)
