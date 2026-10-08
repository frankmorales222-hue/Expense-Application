from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Expense, ExpenseCategory, User
from ..schemas import NameAmount, SummaryOut
from ..security import current_user

router = APIRouter(prefix="/api/reports", tags=["reports"])

STATUS_LABELS = {"pending": "Pending", "approved": "Approved", "paid": "Paid", "rejected": "Rejected"}


def _add_months(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


@router.get("/summary", response_model=SummaryOut)
def summary(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> SummaryOut:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "date_from must be on or before date_to")

    conds = [Expense.is_deleted.is_(False)]
    if user.role == "submitter":
        conds.append(Expense.submitted_by == user.id)
    ranged = list(conds)
    if date_from:
        ranged.append(Expense.expense_date >= date_from)
    if date_to:
        ranged.append(Expense.expense_date <= date_to)
    counted = [*ranged, Expense.status != "rejected"]  # rejected expenses don't count as spending

    total, count = db.execute(
        select(func.coalesce(func.sum(Expense.amount), 0), func.count(Expense.id)).where(*counted)
    ).one()
    pending_count, pending_amount = db.execute(
        select(func.count(Expense.id), func.coalesce(func.sum(Expense.amount), 0))
        .where(*ranged, Expense.status == "pending")
    ).one()
    reimbursable = db.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0))
        .where(*conds, Expense.is_reimbursable.is_(True), Expense.status.in_(("pending", "approved")))
    )

    by_status_rows = db.execute(
        select(Expense.status, func.coalesce(func.sum(Expense.amount), 0), func.count(Expense.id))
        .where(*ranged).group_by(Expense.status)
    ).all()
    found = {s: (a, n) for s, a, n in by_status_rows}
    by_status = [
        NameAmount(key=s, label=label, amount=Decimal(found.get(s, (0, 0))[0]), count=found.get(s, (0, 0))[1])
        for s, label in STATUS_LABELS.items()
    ]

    by_category_rows = db.execute(
        select(ExpenseCategory.code, ExpenseCategory.name, func.sum(Expense.amount), func.count(Expense.id))
        .join(ExpenseCategory, Expense.category_id == ExpenseCategory.id)
        .where(*counted)
        .group_by(ExpenseCategory.code, ExpenseCategory.name)
        .order_by(func.sum(Expense.amount).desc())
    ).all()
    by_category = [NameAmount(key=c, label=n, amount=Decimal(a), count=k) for c, n, a, k in by_category_rows]

    # Last 12 months ending at date_to (or today), independent of date_from.
    end = date_to or date.today()
    first_month = _add_months(date(end.year, end.month, 1), -11)
    sqlite = db.get_bind().dialect.name == "sqlite"
    month_col = (func.strftime("%Y-%m-01", Expense.expense_date) if sqlite
                 else cast(func.date_trunc("month", Expense.expense_date), Date))
    month_rows = db.execute(
        select(month_col, func.sum(Expense.amount), func.count(Expense.id))
        .where(*conds, Expense.status != "rejected", Expense.expense_date >= first_month, Expense.expense_date <= end)
        .group_by(month_col)
    ).all()
    monthly = {(date.fromisoformat(m) if sqlite else m): (a, k) for m, a, k in month_rows}
    by_month = []
    for i in range(12):
        m = _add_months(first_month, i)
        amount, k = monthly.get(m, (0, 0))
        by_month.append(NameAmount(key=m.strftime("%Y-%m"), label=m.strftime("%b %Y"), amount=Decimal(amount), count=k))

    return SummaryOut(
        date_from=date_from, date_to=date_to, total_spent=Decimal(total), expense_count=count,
        pending_count=pending_count, pending_amount=Decimal(pending_amount),
        reimbursable_owed=Decimal(reimbursable or 0),
        by_status=by_status, by_category=by_category, by_month=by_month,
    )
