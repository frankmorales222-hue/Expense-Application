"""Chart of accounts, account registers, journal entries, financial reports and the closing date."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from .. import modules
from ..database import get_db
from ..ledger import books, reports
from ..ledger.posting import Line, Unbalanced, _write, check_open
from ..models import (
    DETAIL_TYPES, Customer, Expense, ExpenseCategory, FinancialAccount, JournalEntry, JournalLine, LedgerAccount, User,
    Vendor,
)
from ..schemas import (
    BalanceSheetOut, BooksStatusOut, ClosingDateIn, JournalEntryIn, JournalEntryOut, JournalLineOut, LedgerAccountIn,
    LedgerAccountOut, ProfitLossOut, RegisterLine, RegisterOut, ReportRow, ReportSection, TrialBalanceOut,
    TrialBalanceRow,
)
from ..security import require_roles
from .util import current_company, get_or_create_vendor

router = APIRouter(prefix="/api/ledger", tags=["ledger"])
READ = require_roles("admin", "approver")
OWNER = require_roles("admin")
ZERO = Decimal("0")


# ---------------------------------------------------------------- chart of accounts
def _links(db: Session) -> tuple[dict, dict]:
    cats = {c.ledger_account_id: c.id for c in db.scalars(select(ExpenseCategory)) if c.ledger_account_id}
    banks = {b.ledger_account_id: b.id for b in db.scalars(select(FinancialAccount)) if b.ledger_account_id}
    return cats, banks


def _out(acct: LedgerAccount, balance: Decimal, cats: dict, banks: dict) -> LedgerAccountOut:
    linked = ("category" if acct.id in cats else "bank" if acct.id in banks
              else "system" if acct.system_key else "none")
    return LedgerAccountOut(
        id=acct.id, code=acct.code, name=acct.name, type=acct.type, detail_type=acct.detail_type,
        system_key=acct.system_key, description=acct.description, is_active=acct.is_active, balance=balance,
        linked_to=linked, category_id=cats.get(acct.id), bank_account_id=banks.get(acct.id))


TYPE_ORDER = {"asset": 0, "liability": 1, "equity": 2, "income": 3, "expense": 4}


@router.get("/accounts", response_model=list[LedgerAccountOut])
def chart_of_accounts(include_inactive: bool = False, db: Session = Depends(get_db),
                      _: User = Depends(READ)) -> list[LedgerAccountOut]:
    company = current_company(db)
    bal = reports.raw_balances(db, company.id)
    cats, banks = _links(db)
    out = []
    for acct in reports.accounts(db, company.id):
        if not acct.is_active and not include_inactive:
            continue
        d, c = bal.get(acct.id, (ZERO, ZERO))
        out.append(_out(acct, reports.signed(acct, d, c), cats, banks))
    out.sort(key=lambda a: (TYPE_ORDER[a.type], a.code or "~", a.name.lower()))
    return out


def _check_detail(payload: LedgerAccountIn) -> None:
    if payload.detail_type not in DETAIL_TYPES[payload.type]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That detail type doesn't belong to the account type")
    if payload.detail_type in ("bank", "credit_card"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Add bank and credit card accounts on the Accounts page, so you can import their statements")
    if payload.detail_type in ("accounts_payable", "accounts_receivable"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "There is already an Accounts Payable/Receivable account")


def _unique(db: Session, company_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> None:
    stmt = select(LedgerAccount.id).where(LedgerAccount.company_id == company_id,
                                          func.lower(LedgerAccount.name) == name.lower())
    if exclude:
        stmt = stmt.where(LedgerAccount.id != exclude)
    if db.scalar(stmt):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that name already exists")


@router.post("/accounts", response_model=LedgerAccountOut, status_code=status.HTTP_201_CREATED)
def create_account(payload: LedgerAccountIn, db: Session = Depends(get_db),
                   user: User = Depends(OWNER)) -> LedgerAccountOut:
    company = current_company(db)
    _check_detail(payload)
    _unique(db, company.id, payload.name)
    if payload.type in ("income", "expense"):
        # Income and expense accounts are categories, so they can be used on expenses and in Banking.
        from .categories import _slug

        code, n = _slug(payload.name), 2
        while db.scalar(select(ExpenseCategory.id).where(ExpenseCategory.code == code)):
            code, n = f"{_slug(payload.name)}_{n}", n + 1
        top = db.scalar(select(func.max(ExpenseCategory.sort_order))) or 0
        cat = ExpenseCategory(code=code, name=payload.name, kind=payload.type, sort_order=top + 10,
                              is_active=payload.is_active)
        db.add(cat)
        db.flush()  # creates the ledger account through app.ledger.sync
        acct = db.get(LedgerAccount, cat.ledger_account_id)
        acct.code, acct.detail_type, acct.description = payload.code, payload.detail_type, payload.description
    else:
        acct = LedgerAccount(id=uuid.uuid4(), code=payload.code, name=payload.name, type=payload.type,
                             detail_type=payload.detail_type, description=payload.description,
                             is_active=payload.is_active)
        db.add(acct)
    db.flush()
    audit.record(db, entity_type="ledger_account", entity_id=acct.id, action="created", user_id=user.id,
                 changes={"name": acct.name, "type": acct.type, "detail_type": acct.detail_type})
    db.commit()
    cats, banks = _links(db)
    return _out(acct, ZERO, cats, banks)


@router.put("/accounts/{account_id}", response_model=LedgerAccountOut)
def update_account(account_id: uuid.UUID, payload: LedgerAccountIn, db: Session = Depends(get_db),
                   user: User = Depends(OWNER)) -> LedgerAccountOut:
    company = current_company(db)
    acct = db.get(LedgerAccount, account_id)
    if acct is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    cats, banks = _links(db)
    if acct.system_key and (payload.type != acct.type or payload.detail_type != acct.detail_type
                            or not payload.is_active):
        raise HTTPException(status.HTTP_409_CONFLICT, "This built-in account's type can't be changed or hidden")
    if acct.id in banks and (payload.type, payload.detail_type) != (acct.type, acct.detail_type):
        raise HTTPException(status.HTTP_409_CONFLICT, "Change a bank account's type on the Accounts page")
    if payload.type != acct.type:
        used = db.scalar(select(func.count(JournalLine.id)).where(JournalLine.account_id == acct.id))
        if used:
            raise HTTPException(status.HTTP_409_CONFLICT, "An account with transactions can't change type. "
                                                          "Make a new account and move the entries with a journal entry.")
    if payload.detail_type not in DETAIL_TYPES[payload.type]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That detail type doesn't belong to the account type")
    if acct.id in cats and payload.type not in ("income", "expense", "equity"):
        raise HTTPException(status.HTTP_409_CONFLICT, "A category's account must be income, expense or equity")
    _unique(db, company.id, payload.name, exclude=acct.id)
    changes = {k: [getattr(acct, k), getattr(payload, k)] for k in ("code", "name", "type", "detail_type",
                                                                     "description", "is_active")
               if getattr(acct, k) != getattr(payload, k)}
    for k in changes:
        setattr(acct, k, getattr(payload, k))
    # Keep the linked category or bank account in step.
    if acct.id in cats:
        cat = db.get(ExpenseCategory, cats[acct.id])
        cat.name, cat.is_active = acct.name, acct.is_active
        cat.kind = acct.type if acct.type in ("income", "expense", "equity") else cat.kind
    if acct.id in banks:
        db.get(FinancialAccount, banks[acct.id]).name = acct.name
    if changes:
        audit.record(db, entity_type="ledger_account", entity_id=acct.id, action="updated", user_id=user.id,
                     changes=changes)
    db.commit()
    bal = reports.raw_balances(db, company.id).get(acct.id, (ZERO, ZERO))
    return _out(acct, reports.signed(acct, *bal), cats, banks)


@router.get("/accounts/{account_id}/register", response_model=RegisterOut)
def register(account_id: uuid.UUID, date_from: date | None = None, date_to: date | None = None,
             db: Session = Depends(get_db), _: User = Depends(READ)) -> RegisterOut:
    company = current_company(db)
    acct = db.get(LedgerAccount, account_id)
    if acct is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    opening = ZERO
    if date_from:
        from datetime import timedelta

        d, c = reports.raw_balances(db, company.id, date_to=date_from - timedelta(days=1)).get(acct.id, (ZERO, ZERO))
        opening = reports.signed(acct, d, c)
    stmt = (select(JournalLine, JournalEntry).join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(JournalLine.account_id == acct.id)
            .order_by(JournalEntry.entry_date, JournalEntry.created_at, JournalLine.line_no))
    if date_from:
        stmt = stmt.where(JournalEntry.entry_date >= date_from)
    if date_to:
        stmt = stmt.where(JournalEntry.entry_date <= date_to)
    rows = db.execute(stmt.limit(5000)).all()
    names = {a.id: a.name for a in db.scalars(select(LedgerAccount))}
    running = opening
    lines = []
    for jl, je in rows:
        running += reports.signed(acct, Decimal(jl.debit), Decimal(jl.credit))
        others = sorted({names.get(o.account_id, "?") for o in je.lines if o.account_id != acct.id})
        lines.append(RegisterLine(entry_id=je.id, entry_date=je.entry_date, source_type=je.source_type,
                                  source_id=je.source_id, number=je.number, memo=je.memo, description=jl.description,
                                  other_accounts=", ".join(others) if len(others) <= 2 else "-Split-",
                                  debit=jl.debit, credit=jl.credit, balance=running))
    cats, banks = _links(db)
    return RegisterOut(account=_out(acct, running, cats, banks), lines=lines, opening_balance=opening)


# ---------------------------------------------------------------- journal entries
def _entry_out(db: Session, e: JournalEntry) -> JournalEntryOut:
    names = {a.id: a.name for a in db.scalars(select(LedgerAccount))}
    vendor_ids = {ln.vendor_id for ln in e.lines if ln.vendor_id}
    vendors = {v.id: v.name for v in db.scalars(select(Vendor).where(Vendor.id.in_(vendor_ids)))} if vendor_ids else {}
    return JournalEntryOut(
        id=e.id, entry_date=e.entry_date, source_type=e.source_type, source_id=e.source_id, number=e.number,
        memo=e.memo, total=sum((Decimal(ln.debit) for ln in e.lines), ZERO), editable=e.source_type == "journal",
        lines=[JournalLineOut(account_id=ln.account_id, account_name=names.get(ln.account_id, "?"), debit=ln.debit,
                              credit=ln.credit, description=ln.description, customer_id=ln.customer_id,
                              vendor_name=vendors.get(ln.vendor_id)) for ln in e.lines])


@router.get("/journal", response_model=list[JournalEntryOut])
def list_journal(source: Literal["manual", "all"] = "manual", date_from: date | None = None,
                 date_to: date | None = None, limit: int = Query(default=200, le=1000),
                 db: Session = Depends(get_db), _: User = Depends(READ)) -> list[JournalEntryOut]:
    stmt = select(JournalEntry).order_by(JournalEntry.entry_date.desc(), JournalEntry.created_at.desc())
    if source == "manual":
        stmt = stmt.where(JournalEntry.source_type == "journal")
    if date_from:
        stmt = stmt.where(JournalEntry.entry_date >= date_from)
    if date_to:
        stmt = stmt.where(JournalEntry.entry_date <= date_to)
    return [_entry_out(db, e) for e in db.scalars(stmt.limit(limit)).unique()]


def _journal_lines(db: Session, payload: JournalEntryIn) -> list[Line]:
    lines = []
    for i, ln in enumerate(payload.lines, start=1):
        if (ln.debit > 0) == (ln.credit > 0):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Line {i}: enter a debit or a credit, not both")
        acct = db.get(LedgerAccount, ln.account_id)
        if acct is None or not acct.is_active:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Line {i}: account not found")
        if acct.system_key == "accounts_payable":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Line {i}: use Bills to change Accounts Payable, so each vendor's balance stays right")
        if acct.system_key == "accounts_receivable":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Line {i}: use Invoices and Receive payment to change Accounts Receivable, "
                                "so each customer's balance stays right")
        if ln.customer_id is not None and db.get(Customer, ln.customer_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Line {i}: customer not found")
        vendor = get_or_create_vendor(db, (ln.vendor_name or "").strip() or None)
        lines.append(Line(acct.id, debit=ln.debit, credit=ln.credit, description=ln.description,
                          vendor_id=vendor.id if vendor else None, customer_id=ln.customer_id))
    debits = sum((ln.debit for ln in lines), ZERO)
    credits = sum((ln.credit for ln in lines), ZERO)
    if debits != credits:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Debits ({debits:,.2f}) and credits ({credits:,.2f}) must be equal")
    return lines


@router.post("/journal", response_model=JournalEntryOut, status_code=status.HTTP_201_CREATED)
def create_journal(payload: JournalEntryIn, db: Session = Depends(get_db),
                   user: User = Depends(require_roles("admin", "approver"))) -> JournalEntryOut:
    modules.check(db, user, "advanced_accounting", accountant_free=True)
    company = current_company(db)
    lines = _journal_lines(db, payload)
    check_open(db, company.id, payload.entry_date)
    entry = _write(db, company.id, "journal", None, payload.entry_date, lines, payload.memo,
                   (payload.number or "").strip() or None, user.id)
    entry.source_id = entry.id
    db.flush()
    audit.record(db, entity_type="journal_entry", entity_id=entry.id, action="created", user_id=user.id,
                 changes={"date": payload.entry_date, "total": sum((ln.debit for ln in lines), ZERO)})
    db.commit()
    return _entry_out(db, entry)


def _manual(db: Session, entry_id: uuid.UUID) -> JournalEntry:
    e = db.get(JournalEntry, entry_id)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    if e.source_type != "journal":
        raise HTTPException(status.HTTP_409_CONFLICT, "This entry comes from a transaction. Edit that transaction instead.")
    return e


@router.get("/journal/{entry_id}", response_model=JournalEntryOut)
def get_journal(entry_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(READ)) -> JournalEntryOut:
    e = db.get(JournalEntry, entry_id)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    return _entry_out(db, e)


@router.put("/journal/{entry_id}", response_model=JournalEntryOut)
def update_journal(entry_id: uuid.UUID, payload: JournalEntryIn, db: Session = Depends(get_db),
                   user: User = Depends(require_roles("admin", "approver"))) -> JournalEntryOut:
    modules.check(db, user, "advanced_accounting", accountant_free=True)
    company = current_company(db)
    e = _manual(db, entry_id)
    lines = _journal_lines(db, payload)
    check_open(db, company.id, e.entry_date, payload.entry_date)
    db.delete(e)
    db.flush()
    entry = _write(db, company.id, "journal", None, payload.entry_date, lines, payload.memo,
                   (payload.number or "").strip() or None, user.id)
    entry.source_id = entry.id
    audit.record(db, entity_type="journal_entry", entity_id=entry.id, action="updated", user_id=user.id,
                 changes={"replaces": e.id, "date": payload.entry_date})
    db.commit()
    return _entry_out(db, entry)


@router.delete("/journal/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_journal(entry_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(require_roles("admin", "approver"))) -> Response:
    modules.check(db, user, "advanced_accounting", accountant_free=True)
    company = current_company(db)
    e = _manual(db, entry_id)
    check_open(db, company.id, e.entry_date)
    db.delete(e)
    audit.record(db, entity_type="journal_entry", entity_id=entry_id, action="deleted", user_id=user.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- reports
def _section(s: reports.Section) -> ReportSection:
    return ReportSection(key=s.key, label=s.label, total=s.total,
                         rows=[ReportRow(account_id=r.account_id, name=r.name, code=r.code, amount=r.amount)
                               for r in sorted(s.rows, key=lambda r: (r.code or "~", r.name.lower()))])


@router.get("/reports/profit-and-loss", response_model=ProfitLossOut)
def profit_and_loss(date_from: date, date_to: date, db: Session = Depends(get_db),
                    _: User = Depends(READ)) -> ProfitLossOut:
    if date_from > date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The start date must be on or before the end date")
    r = reports.profit_and_loss(db, current_company(db).id, date_from, date_to)
    return ProfitLossOut(date_from=date_from, date_to=date_to, sections=[_section(s) for s in r["sections"]],
                         gross_profit=r["gross_profit"], net_operating_income=r["net_operating_income"],
                         net_income=r["net_income"])


@router.get("/reports/balance-sheet", response_model=BalanceSheetOut)
def balance_sheet(as_of: date, db: Session = Depends(get_db), _: User = Depends(READ)) -> BalanceSheetOut:
    r = reports.balance_sheet(db, current_company(db).id, as_of)
    return BalanceSheetOut(as_of=as_of, sections=[_section(s) for s in r["sections"]],
                           total_assets=r["total_assets"],
                           total_liabilities_and_equity=r["total_liabilities_and_equity"],
                           balanced=r["total_assets"] == r["total_liabilities_and_equity"])


@router.get("/reports/trial-balance", response_model=TrialBalanceOut)
def trial_balance(as_of: date, db: Session = Depends(get_db), user: User = Depends(READ)) -> TrialBalanceOut:
    modules.check(db, user, "advanced_accounting", accountant_free=True)
    rows = [TrialBalanceRow(account_id=a.id, name=a.name, code=a.code, type=a.type, debit=d, credit=c)
            for a, d, c in reports.trial_balance(db, current_company(db).id, as_of)]
    rows.sort(key=lambda r: (TYPE_ORDER[r.type], r.code or "~", r.name.lower()))
    return TrialBalanceOut(as_of=as_of, rows=rows, total_debit=sum((r.debit for r in rows), ZERO),
                           total_credit=sum((r.credit for r in rows), ZERO))


# ---------------------------------------------------------------- books status / closing date
@router.get("/status", response_model=BooksStatusOut)
def books_status(db: Session = Depends(get_db), _: User = Depends(READ)) -> BooksStatusOut:
    company = current_company(db)
    debit, credit = books.totals(db, company.id)
    missing = db.scalar(select(func.count(Expense.id)).where(
        Expense.is_deleted.is_(False), Expense.is_reimbursable.is_(False), Expense.payment_account_id.is_(None),
        Expense.status.in_(("approved", "paid")))) or 0
    return BooksStatusOut(closing_date=company.closing_date, total_debit=debit, total_credit=credit,
                          balanced=debit == credit, unbalanced_entries=len(books.unbalanced_entries(db, company.id)),
                          payment_account_not_set=missing)


@router.put("/closing-date", response_model=BooksStatusOut)
def set_closing_date(payload: ClosingDateIn, db: Session = Depends(get_db),
                     user: User = Depends(OWNER)) -> BooksStatusOut:
    company = current_company(db)
    if company.closing_date != payload.closing_date:
        audit.record(db, entity_type="company", entity_id=company.id, action="closing_date_changed", user_id=user.id,
                     changes={"closing_date": [company.closing_date, payload.closing_date]})
        company.closing_date = payload.closing_date
        db.commit()
    return books_status(db, user)
