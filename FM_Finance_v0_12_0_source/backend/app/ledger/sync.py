"""Keep the journal in step with the records, automatically.

* before_flush notes every changed source record (expense and its lines, bank transaction, bill and
  its lines, bill payment, bank/card opening balance), including the *previous* record a link pointed
  at (an unlinked transfer peer, the bank transaction a deleted bill payment used to cover).
* before_commit reposts each noted source from its current state (app.ledger.posting), then commits.
  A ClosedPeriod or Unbalanced error stops the commit, so the record change is rolled back too.

It also keeps the chart of accounts in step: a new category or bank/card account gets its ledger
account, and renames carry over.
"""

from __future__ import annotations

import uuid

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from ..models import (
    Bill, BillLine, BillPayment, CustomerPayment, Expense, ExpenseCategory, ExpenseLine, FinancialAccount, Invoice,
    InvoiceLine, LedgerAccount, PaymentApplication, Transaction,
)
from ..tenancy import NO_COMPANY, company_of
from .chart import KIND_TO_TYPE, account_type_for_bank, ledger_for_bank, ledger_for_category
from .posting import POSTERS

DIRTY = "ledger_dirty"
ORDER = ("opening_balance", "expense", "bill", "bill_payment", "invoice", "customer_payment", "transaction")


def _mark(session: Session, kind: str, obj_id: uuid.UUID | None, company_id: uuid.UUID | None) -> None:
    if obj_id is None:
        return
    session.info.setdefault(DIRTY, {})
    key = (kind, obj_id)
    if session.info[DIRTY].get(key) is None:
        session.info[DIRTY][key] = company_id


def _old_values(obj, attr: str) -> list:
    hist = inspect(obj).attrs[attr].history
    return [v for v in (hist.deleted or ()) if v is not None]


def _changed(obj, *attrs: str) -> bool:
    state = inspect(obj)
    return any(state.attrs[a].history.has_changes() for a in attrs)


def _company(session: Session, obj) -> uuid.UUID | None:
    company = getattr(obj, "company_id", None)
    if company is None:
        current = company_of(session)
        company = current if current not in (None, NO_COMPANY) else None
    return company


@event.listens_for(Session, "before_flush")
def _track(session: Session, flush_context, instances) -> None:
    new, dirty, deleted = set(session.new), set(session.dirty), set(session.deleted)
    for obj in new:
        # Primary keys are normally generated at INSERT; sources need theirs now to be tracked.
        if isinstance(obj, (Expense, Transaction, Bill, BillPayment, FinancialAccount, Invoice,
                            CustomerPayment)) and obj.id is None:
            obj.id = uuid.uuid4()
    for obj in new | dirty | deleted:
        company = _company(session, obj)
        if isinstance(obj, Expense):
            _mark(session, "expense", obj.id, company)
        elif isinstance(obj, ExpenseLine):
            _mark(session, "expense", obj.expense_id, company)
            for old in _old_values(obj, "expense_id") if obj in dirty else []:
                _mark(session, "expense", old, company)
        elif isinstance(obj, Transaction):
            _mark(session, "transaction", obj.id, company)
            _mark(session, "transaction", obj.transfer_peer_id, company)
            if obj in dirty:
                for old in _old_values(obj, "transfer_peer_id"):
                    _mark(session, "transaction", old, company)
        elif isinstance(obj, Bill):
            _mark(session, "bill", obj.id, company)
        elif isinstance(obj, BillLine):
            _mark(session, "bill", obj.bill_id, company)
        elif isinstance(obj, BillPayment):
            _mark(session, "bill_payment", obj.id, company)
            _mark(session, "transaction", obj.transaction_id, company)
            if obj in dirty:
                for old in _old_values(obj, "transaction_id"):
                    _mark(session, "transaction", old, company)
        elif isinstance(obj, Invoice):
            _mark(session, "invoice", obj.id, company)
        elif isinstance(obj, InvoiceLine):
            _mark(session, "invoice", obj.invoice_id, company)
        elif isinstance(obj, CustomerPayment):
            _mark(session, "customer_payment", obj.id, company)
            _mark(session, "transaction", obj.transaction_id, company)
            if obj in dirty:
                for old in _old_values(obj, "transaction_id"):
                    _mark(session, "transaction", old, company)
        elif isinstance(obj, PaymentApplication):
            _mark(session, "customer_payment", obj.payment_id, company)
        elif isinstance(obj, FinancialAccount):
            if obj in new or obj in deleted or _changed(obj, "opening_balance", "opening_date"):
                _mark(session, "opening_balance", obj.id, company)
            if obj not in deleted:
                _sync_bank_ledger(session, obj, company)
        elif isinstance(obj, ExpenseCategory) and obj not in deleted:
            _sync_category_ledger(session, obj, company)


def _sync_category_ledger(session: Session, cat: ExpenseCategory, company: uuid.UUID | None) -> None:
    type_, detail = KIND_TO_TYPE.get(cat.kind, ("expense", "expense"))
    if cat.ledger_account_id is None:
        if company is None:
            return  # ensure_chart picks it up at startup
        cat.company_id = cat.company_id or company
        acct = ledger_for_category(cat)
        session.add(acct)
        cat.ledger_account_id = acct.id
        return
    acct = session.get(LedgerAccount, cat.ledger_account_id)
    if acct is not None:
        if acct.name != cat.name:
            acct.name = cat.name
        if (acct.type, acct.detail_type) != (type_, detail):
            acct.type, acct.detail_type = type_, detail
        if acct.is_active != cat.is_active:
            acct.is_active = cat.is_active


def _sync_bank_ledger(session: Session, fa: FinancialAccount, company: uuid.UUID | None) -> None:
    type_, detail = account_type_for_bank(fa.kind)
    if fa.ledger_account_id is None:
        if company is None:
            return
        fa.company_id = fa.company_id or company
        acct = ledger_for_bank(fa)
        session.add(acct)
        fa.ledger_account_id = acct.id
        return
    acct = session.get(LedgerAccount, fa.ledger_account_id)
    if acct is not None:
        if acct.name != fa.name:
            acct.name = fa.name
        if (acct.type, acct.detail_type) != (type_, detail):
            acct.type, acct.detail_type = type_, detail


def _expand(session: Session, work: dict) -> None:
    """Records whose posting depends on the ones that changed."""
    for (kind, obj_id), company in list(work.items()):
        if kind == "expense":
            for t in session.scalars(select(Transaction.id).where(Transaction.expense_id == obj_id)):
                work.setdefault(("transaction", t), company)
        elif kind == "bill":
            for p in session.scalars(select(BillPayment.id).where(BillPayment.bill_id == obj_id)):
                work.setdefault(("bill_payment", p), company)


def _resolve_company(session: Session, kind: str, obj_id: uuid.UUID) -> uuid.UUID | None:
    model = {"expense": Expense, "transaction": Transaction, "bill": Bill, "bill_payment": BillPayment,
             "opening_balance": FinancialAccount, "invoice": Invoice, "customer_payment": CustomerPayment}[kind]
    obj = session.get(model, obj_id)
    return obj.company_id if obj is not None else None


@event.listens_for(Session, "before_commit")
def _repost(session: Session) -> None:
    for _ in range(10):
        session.flush()
        work = session.info.pop(DIRTY, None)
        if not work:
            return
        _expand(session, work)
        for kind in ORDER:
            for (k, obj_id), company in list(work.items()):
                if k != kind:
                    continue
                company = company or _resolve_company(session, k, obj_id)
                if company is not None:
                    POSTERS[k](session, obj_id, company)
    raise RuntimeError("The ledger didn't settle after 10 passes")


@event.listens_for(Session, "after_rollback")
def _forget(session: Session) -> None:
    session.info.pop(DIRTY, None)
