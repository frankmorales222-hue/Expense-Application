"""Dashboard overview (v0.9.0): cash, the 30-day cash forecast, what's coming up, profit and the month so far.

Cash is the bank feed: each bank, savings and cash account's opening balance plus its transactions (excluded
ones don't count). Credit cards are listed but aren't cash. The forecast starts from today's cash and adds open
invoices and unpaid bills on their due dates; bills already past due are counted tomorrow, and late invoices
aren't counted (they're listed under "Coming up" so someone can chase them).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..banking.engine import account_balances
from ..database import get_db
from ..invoicing import service
from ..ledger import reports
from ..ledger.chart import system_account
from ..models import (
    Bill, CustomerPayment, FinancialAccount, Invoice, JournalEntry, JournalLine, LedgerAccount, Transaction, User,
)
from ..schemas import (
    DashAccount, DashboardOut, DashEvent, DashInvoice, DashMonth, DashPnl, DashPnlRow, DashPoint,
)
from ..security import require_roles
from .util import current_company

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
READ = require_roles("admin", "approver")
ZERO = Decimal("0")
CENT = Decimal("0.01")
NOT_CASH = ("credit_card",)
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _q(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(CENT)


def _shift_year(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29
        return d.replace(year=d.year + years, day=28)


def _month_start(d: date, back: int = 0) -> date:
    m = d.month - 1 - back
    return date(d.year + m // 12, m % 12 + 1, 1)


def _pl_totals(pl: dict) -> tuple[Decimal, Decimal]:
    s = {sec.key: sec.total for sec in pl["sections"]}
    return s["income"] + s["other_income"], s["cogs"] + s["expenses"] + s["other_expenses"]


def _bill_balance(b: Bill) -> Decimal:
    return Decimal(b.total) - sum((Decimal(p.amount) for p in b.payments), ZERO)


@router.get("/overview", response_model=DashboardOut)
def overview(db: Session = Depends(get_db), _: User = Depends(READ)) -> DashboardOut:
    today = date.today()
    company = current_company(db)
    cid = company.id
    from .. import rules

    r = rules.of(company)
    horizon, soon = r.forecast_days, r.coming_up_days  # v0.10.0: each company picks its periods

    # ---- cash
    accts = list(db.scalars(select(FinancialAccount).where(FinancialAccount.is_active.is_(True))
                            .order_by(FinancialAccount.kind, FinancialAccount.name)))
    sums = account_balances(db)
    unreviewed = dict(db.execute(select(Transaction.account_id, func.count(Transaction.id))
                                 .where(Transaction.review_status == "unreviewed").group_by(Transaction.account_id)).all())
    accounts = [DashAccount(id=a.id, name=a.name, kind=a.kind, institution=a.institution, last4=a.last4,
                            balance=_q(Decimal(a.opening_balance) + sums.get(a.id, ZERO)),
                            unreviewed=unreviewed.get(a.id, 0)) for a in accts]
    cash_ids = [a.id for a in accts if a.kind not in NOT_CASH]
    cash_all = sum((a.balance for a in accounts if a.kind not in NOT_CASH), ZERO)
    later: dict[date, Decimal] = defaultdict(lambda: ZERO)  # money movements after the start of the window
    window_start = min(today - timedelta(days=30), _month_start(today) - timedelta(days=1))
    if cash_ids:
        for d, amt in db.execute(select(Transaction.txn_date, Transaction.amount).where(
                Transaction.account_id.in_(cash_ids), Transaction.review_status != "excluded",
                Transaction.txn_date > window_start)).all():
            later[d] += Decimal(amt)

    def cash_on(day: date) -> Decimal:
        return _q(cash_all - sum((v for d, v in later.items() if d > day), ZERO))

    cash_today = cash_on(today)
    history = [DashPoint(date=today - timedelta(days=i), balance=cash_on(today - timedelta(days=i)))
               for i in range(30, -1, -1)]

    # ---- invoices and bills
    invoices = list(db.scalars(service.live_invoices(db).where(Invoice.is_void.is_(False))))
    paid = service.paid_map(db, [i.id for i in invoices])
    items = [(inv, service.list_item(inv, paid[inv.id])) for inv in invoices]
    unpaid = [(inv, it) for inv, it in items if it.status not in ("paid", "void") and it.balance > 0]
    overdue = [(inv, it) for inv, it in unpaid if it.status == "overdue"]
    since = today - timedelta(days=30)
    paid_30 = sum((Decimal(p.amount) for p in db.scalars(
        select(CustomerPayment).where(CustomerPayment.payment_date >= since))), ZERO)
    bills = [b for b in db.scalars(select(Bill).where(Bill.is_deleted.is_(False))) if _bill_balance(b) > 0]

    events: dict[date, Decimal] = defaultdict(lambda: ZERO)
    coming: list[DashEvent] = []
    for inv, it in unpaid:
        late = (today - it.due_date).days
        if late > 0:
            coming.append(DashEvent(kind="invoice", id=inv.id, date=it.due_date, name=it.customer_name,
                                    reference=it.invoice_number, amount=it.balance, days_late=late))
            continue
        if it.due_date <= today + timedelta(days=horizon):
            events[max(it.due_date, today + timedelta(days=1))] += it.balance
        if it.due_date <= today + timedelta(days=soon):
            coming.append(DashEvent(kind="invoice", id=inv.id, date=it.due_date, name=it.customer_name,
                                    reference=it.invoice_number, amount=it.balance))
    for b in bills:
        bal = _bill_balance(b)
        late = (today - b.due_date).days
        if b.due_date <= today + timedelta(days=horizon):
            events[max(b.due_date, today + timedelta(days=1))] -= bal
        if b.due_date <= today + timedelta(days=soon):
            coming.append(DashEvent(kind="bill", id=b.id, date=b.due_date, name=b.vendor.name if b.vendor else "",
                                    reference=b.bill_number, amount=-bal, days_late=max(late, 0)))
    coming.sort(key=lambda e: (e.days_late == 0, -e.days_late, e.date))

    forecast, running = [DashPoint(date=today, balance=cash_today)], cash_today
    for i in range(1, horizon + 1):
        day = today + timedelta(days=i)
        running += events.get(day, ZERO)
        forecast.append(DashPoint(date=day, balance=_q(running)))
    low = min(forecast, key=lambda p: (p.balance, p.date))

    overdue_first = sorted((x for x in items if x[1].status == "overdue"), key=lambda x: x[1].due_date)
    rest = sorted((x for x in items if x[1].status != "overdue"), key=lambda x: (x[0].invoice_date, x[0].created_at),
                  reverse=True)
    dash_invoices = [DashInvoice(id=inv.id, invoice_number=it.invoice_number, customer_name=it.customer_name,
                                 due_date=it.due_date, total=it.total, balance=it.balance, status=it.status,
                                 days_late=max((today - it.due_date).days, 0) if it.status == "overdue" else 0)
                     for inv, it in (overdue_first + rest)[:5]]

    # ---- profit
    fy_start = reports.fiscal_year_start(db, cid, today)
    income_ytd, expenses_ytd = _pl_totals(reports.profit_and_loss(db, cid, fy_start, today))
    prior = reports.net_income(db, cid, _shift_year(fy_start, -1), _shift_year(today, -1))

    first = _month_start(today, 11)
    by_month: dict[str, list[Decimal]] = {}
    for i in range(11, -1, -1):
        m = _month_start(today, i)
        by_month[f"{m.year}-{m.month:02d}"] = [ZERO, ZERO]
    rows = db.execute(
        select(JournalEntry.entry_date, LedgerAccount.type, JournalLine.debit, JournalLine.credit)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(LedgerAccount, LedgerAccount.id == JournalLine.account_id)
        .where(JournalLine.company_id == cid, JournalEntry.entry_date >= first, JournalEntry.entry_date <= today,
               LedgerAccount.type.in_(("income", "expense")))).all()
    for d, kind, debit, credit in rows:
        slot = by_month.get(f"{d.year}-{d.month:02d}")
        if slot is None:
            continue
        if kind == "income":
            slot[0] += Decimal(credit or 0) - Decimal(debit or 0)
        else:
            slot[1] += Decimal(debit or 0) - Decimal(credit or 0)
    months = [DashMonth(key=k, label=MONTHS[int(k[5:]) - 1], income=_q(v[0]), expenses=_q(v[1]))
              for k, v in by_month.items()]

    this_from, last_from = _month_start(today), _month_start(today, 1)
    last_to = this_from - timedelta(days=1)
    pl_this = reports.profit_and_loss(db, cid, this_from, today)
    pl_last = reports.profit_and_loss(db, cid, last_from, last_to)
    inc_this, exp_this = _pl_totals(pl_this)
    inc_last, exp_last = _pl_totals(pl_last)

    def expense_amounts(pl: dict) -> dict[str, Decimal]:
        out: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for sec in pl["sections"]:
            if sec.key in ("cogs", "expenses", "other_expenses"):
                for r in sec.rows:
                    out[r.name] += r.amount
        return out

    e_this, e_last = expense_amounts(pl_this), expense_amounts(pl_last)
    names = sorted(set(e_this) | set(e_last), key=lambda n: (-e_this.get(n, ZERO), -e_last.get(n, ZERO), n))
    top, others = names[:4], names[4:]
    expense_rows = [DashPnlRow(name=n, this_month=_q(e_this.get(n)), last_month=_q(e_last.get(n))) for n in top]
    if others:
        expense_rows.append(DashPnlRow(name="Everything else", this_month=_q(sum((e_this.get(n, ZERO) for n in others), ZERO)),
                                       last_month=_q(sum((e_last.get(n, ZERO) for n in others), ZERO))))
    pnl = DashPnl(this_from=this_from, this_to=today, last_from=last_from, last_to=last_to,
                  income_this=_q(inc_this), income_last=_q(inc_last), expense_rows=expense_rows,
                  expenses_this=_q(exp_this), expenses_last=_q(exp_last),
                  net_this=_q(inc_this - exp_this), net_last=_q(inc_last - exp_last))

    review = db.scalar(select(func.count(Transaction.id)).where(Transaction.review_status == "unreviewed")) or 0
    raw = reports.raw_balances(db, cid, date_to=today)
    due_owner = system_account(db, cid, "due_to_owner")
    reimbursements = system_account(db, cid, "reimbursements_owed")
    od, oc = raw.get(due_owner.id, (ZERO, ZERO))
    rd, rc = raw.get(reimbursements.id, (ZERO, ZERO))
    owner_loan = reports.signed(due_owner, od, oc)
    owner_reimbursements = reports.signed(reimbursements, rd, rc)
    return DashboardOut(
        as_of=today, cash_total=cash_today, cash_month_start=cash_on(this_from - timedelta(days=1)),
        has_bank_accounts=bool(accts), accounts=accounts,
        income_ytd=_q(income_ytd), expenses_ytd=_q(expenses_ytd), profit_ytd=_q(income_ytd - expenses_ytd),
        profit_prior_ytd=_q(prior), fiscal_year_start=fy_start,
        receivable_total=_q(sum((it.balance for _, it in unpaid), ZERO)), receivable_open_count=len(unpaid),
        overdue_total=_q(sum((it.balance for _, it in overdue), ZERO)), overdue_count=len(overdue),
        paid_last_30=_q(paid_30),
        payable_total=_q(sum((_bill_balance(b) for b in bills), ZERO)), payable_count=len(bills),
        payable_due_14=_q(sum((_bill_balance(b) for b in bills if b.due_date <= today + timedelta(days=soon)), ZERO)),
        payable_overdue=_q(sum((_bill_balance(b) for b in bills if b.due_date < today), ZERO)),
        owner_loan_balance=_q(owner_loan), owner_reimbursements=_q(owner_reimbursements),
        owner_total_owed=_q(owner_loan + owner_reimbursements),
        review_count=review, months=months, history=history, forecast=forecast, forecast_low=low,
        coming_up=coming[:8], invoices=dash_invoices, pnl=pnl, forecast_days=horizon, coming_up_days=soon)
