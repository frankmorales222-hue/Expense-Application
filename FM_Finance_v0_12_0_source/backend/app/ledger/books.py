"""Building the books for existing records, and checks that they balance."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import (
    Bill, BillPayment, Company, CustomerPayment, Expense, FinancialAccount, Invoice, JournalEntry, JournalLine,
    Transaction,
)
from . import sync  # noqa: F401  (registers the automatic posting events)
from .chart import ensure_chart
from .posting import POSTERS

log = logging.getLogger(__name__)


def _post_everything(db: Session, company_id: uuid.UUID) -> int:
    count = 0
    sources = [
        ("opening_balance", select(FinancialAccount.id).where(FinancialAccount.company_id == company_id)),
        ("expense", select(Expense.id).where(Expense.company_id == company_id)),
        ("bill", select(Bill.id).where(Bill.company_id == company_id)),
        ("bill_payment", select(BillPayment.id).where(BillPayment.company_id == company_id)),
        ("invoice", select(Invoice.id).where(Invoice.company_id == company_id)),
        ("customer_payment", select(CustomerPayment.id).where(CustomerPayment.company_id == company_id)),
        ("transaction", select(Transaction.id).where(Transaction.company_id == company_id,
                                                     Transaction.review_status == "approved")),
    ]
    for kind, stmt in sources:
        for obj_id in list(db.scalars(stmt)):
            POSTERS[kind](db, obj_id, company_id)
            count += 1
    return count


def rebuild(db: Session, company_id: uuid.UUID) -> int:
    """Delete every automatically posted entry and post all records again. Manual journal entries stay.
    Ignores the closing date on purpose: it reproduces the same entries the records already imply."""
    from ..models import Company as _Company

    company = db.get(_Company, company_id)
    closing, company.closing_date = company.closing_date, None
    db.flush()
    ids = select(JournalEntry.id).where(JournalEntry.company_id == company_id, JournalEntry.source_type != "journal")
    db.execute(delete(JournalLine).where(JournalLine.entry_id.in_(ids)))
    db.execute(delete(JournalEntry).where(JournalEntry.company_id == company_id, JournalEntry.source_type != "journal"))
    db.flush()
    ensure_chart(db, company_id)
    count = _post_everything(db, company_id)
    company.closing_date = closing
    return count


def ensure_books(db: Session) -> None:
    """Startup: every company gets its chart of accounts; companies upgraded from v0.5 get their
    journal built from their existing records once."""
    for company in list(db.scalars(select(Company))):
        ensure_chart(db, company.id)
        if not company.ledger_ready:
            count = rebuild(db, company.id)
            company.ledger_ready = True
            log.info("Built the books for %s from %d existing records", company.name, count)
    db.commit()


def totals(db: Session, company_id: uuid.UUID) -> tuple[Decimal, Decimal]:
    debit, credit = db.execute(select(func.coalesce(func.sum(JournalLine.debit), 0),
                                      func.coalesce(func.sum(JournalLine.credit), 0))
                               .where(JournalLine.company_id == company_id)).one()
    return Decimal(str(debit)), Decimal(str(credit))


def unbalanced_entries(db: Session, company_id: uuid.UUID) -> list[uuid.UUID]:
    rows = db.execute(select(JournalLine.entry_id).where(JournalLine.company_id == company_id)
                      .group_by(JournalLine.entry_id)
                      .having(func.sum(JournalLine.debit) != func.sum(JournalLine.credit))).all()
    return [r[0] for r in rows]
