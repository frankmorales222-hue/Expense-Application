"""Financial statements computed from the journal."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import DEBIT_NORMAL, Company, JournalEntry, JournalLine, LedgerAccount

ZERO = Decimal("0")


def _q(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def raw_balances(db: Session, company_id: uuid.UUID, date_from: date | None = None,
                 date_to: date | None = None) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
    """account_id -> (total debits, total credits) for entries dated within the range (inclusive)."""
    stmt = (select(JournalLine.account_id, func.sum(JournalLine.debit), func.sum(JournalLine.credit))
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(JournalLine.company_id == company_id).group_by(JournalLine.account_id))
    if date_from:
        stmt = stmt.where(JournalEntry.entry_date >= date_from)
    if date_to:
        stmt = stmt.where(JournalEntry.entry_date <= date_to)
    return {a: (_q(d), _q(c)) for a, d, c in db.execute(stmt).all()}


def signed(acct: LedgerAccount, debit: Decimal, credit: Decimal) -> Decimal:
    """Balance on the account's normal side (assets/expenses: debits minus credits; others the reverse)."""
    return debit - credit if acct.type in DEBIT_NORMAL else credit - debit


def accounts(db: Session, company_id: uuid.UUID) -> list[LedgerAccount]:
    return list(db.scalars(select(LedgerAccount).where(LedgerAccount.company_id == company_id)
                           .order_by(LedgerAccount.type, LedgerAccount.code, LedgerAccount.name)))


def fiscal_year_start(db: Session, company_id: uuid.UUID, on: date) -> date:
    month = db.scalar(select(Company.fiscal_year_start_month).where(Company.id == company_id)) or 1
    year = on.year if on.month >= month else on.year - 1
    return date(year, month, 1)


@dataclass
class Row:
    account_id: uuid.UUID
    name: str
    code: str | None
    type: str
    detail_type: str
    amount: Decimal


@dataclass
class Section:
    key: str
    label: str
    rows: list[Row] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((r.amount for r in self.rows), ZERO)


def trial_balance(db: Session, company_id: uuid.UUID, as_of: date) -> list[tuple[LedgerAccount, Decimal, Decimal]]:
    bal = raw_balances(db, company_id, date_to=as_of)
    out = []
    for acct in accounts(db, company_id):
        d, c = bal.get(acct.id, (ZERO, ZERO))
        net = d - c
        if net:
            out.append((acct, net if net > 0 else ZERO, -net if net < 0 else ZERO))
    return out


PL_SECTIONS = (
    ("income", "Income", ("income",), "income"),
    ("cogs", "Cost of goods sold", ("cost_of_goods_sold",), "expense"),
    ("expenses", "Expenses", ("expense",), "expense"),
    ("other_income", "Other income", ("other_income",), "income"),
    ("other_expenses", "Other expenses", ("other_expense",), "expense"),
)


def profit_and_loss(db: Session, company_id: uuid.UUID, date_from: date, date_to: date) -> dict:
    bal = raw_balances(db, company_id, date_from, date_to)
    sections = {key: Section(key, label) for key, label, _, _ in PL_SECTIONS}
    for acct in accounts(db, company_id):
        if acct.type not in ("income", "expense") or acct.id not in bal:
            continue
        amount = signed(acct, *bal[acct.id])
        if not amount:
            continue
        for key, _, details, type_ in PL_SECTIONS:
            if acct.type == type_ and acct.detail_type in details:
                sections[key].rows.append(Row(acct.id, acct.name, acct.code, acct.type, acct.detail_type, amount))
                break
        else:
            target = "income" if acct.type == "income" else "expenses"
            sections[target].rows.append(Row(acct.id, acct.name, acct.code, acct.type, acct.detail_type, amount))
    gross = sections["income"].total - sections["cogs"].total
    operating = gross - sections["expenses"].total
    net = operating + sections["other_income"].total - sections["other_expenses"].total
    return {"sections": list(sections.values()), "gross_profit": gross, "net_operating_income": operating,
            "net_income": net}


def net_income(db: Session, company_id: uuid.UUID, date_from: date | None, date_to: date) -> Decimal:
    bal = raw_balances(db, company_id, date_from, date_to)
    total = ZERO
    for acct in accounts(db, company_id):
        if acct.type in ("income", "expense") and acct.id in bal:
            amount = signed(acct, *bal[acct.id])
            total += amount if acct.type == "income" else -amount
    return total


def balance_sheet(db: Session, company_id: uuid.UUID, as_of: date) -> dict:
    bal = raw_balances(db, company_id, date_to=as_of)
    fy_start = fiscal_year_start(db, company_id, as_of)
    assets, liabilities, equity = Section("assets", "Assets"), Section("liabilities", "Liabilities"), \
        Section("equity", "Equity")
    for acct in accounts(db, company_id):
        if acct.type not in ("asset", "liability", "equity") or acct.id not in bal:
            continue
        amount = signed(acct, *bal[acct.id])
        if not amount:
            continue
        row = Row(acct.id, acct.name, acct.code, acct.type, acct.detail_type, amount)
        {"asset": assets, "liability": liabilities, "equity": equity}[acct.type].rows.append(row)
    # Profit isn't posted to equity by entries; it's calculated, as in QuickBooks.
    retained = net_income(db, company_id, None, _day_before(fy_start))
    current = net_income(db, company_id, fy_start, as_of)
    if retained:
        equity.rows.append(Row(uuid.UUID(int=1), "Retained Earnings", None, "equity", "equity", retained))
    if current:
        equity.rows.append(Row(uuid.UUID(int=2), "Net Income", None, "equity", "equity", current))
    return {"sections": [assets, liabilities, equity], "total_assets": assets.total,
            "total_liabilities_and_equity": liabilities.total + equity.total}


def _day_before(d: date) -> date:
    from datetime import timedelta

    return d - timedelta(days=1)
