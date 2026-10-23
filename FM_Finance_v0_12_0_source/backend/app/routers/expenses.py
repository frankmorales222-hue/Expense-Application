# Note: no "from __future__ import annotations" here; FastAPI must resolve the
# _Filters class-dependency annotations at runtime.
import csv
import io
import uuid
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from .. import audit, rules
from ..config import get_settings
from ..database import get_db
from ..models import AuditLog, Expense, ExpenseCategory, ExpenseLine, Receipt, Transaction, User, Vendor
from ..schemas import AuditOut, ExpenseDetail, ExpenseIn, ExpenseListItem, ExpensePage, LineIn, ReceiptOut, StatusIn
from ..security import require_company
from .lines import checked_lines, checked_payment_account, lines_out
from . import ruleutil
from .util import current_company, get_or_create_vendor, like_pattern

router = APIRouter(prefix="/api/expenses", tags=["expenses"])

# Allowed status transitions (business rule #2).
TRANSITIONS: dict[str, set[str]] = {
    "pending": {"approved", "rejected"},
    "approved": {"paid"},
    "paid": {"approved"},
    "rejected": {"pending"},
}
APPROVER_ROLES = {"admin", "approver"}
SortKey = Literal["date_desc", "date_asc", "amount_desc", "amount_asc"]
_SORTS = {
    "date_desc": (Expense.expense_date.desc(), Expense.created_at.desc()),
    "date_asc": (Expense.expense_date.asc(), Expense.created_at.asc()),
    "amount_desc": (Expense.amount.desc(), Expense.expense_date.desc()),
    "amount_asc": (Expense.amount.asc(), Expense.expense_date.desc()),
}
_TRACKED_FIELDS = (
    "expense_date", "vendor", "category", "description", "amount", "payment_account", "lines",
    "payment_method", "is_reimbursable", "notes", "invoice_number", "due_date",
)


# ---------- helpers ----------
def _threshold_for(category: ExpenseCategory, company_rules: rules.CompanyRules) -> Decimal:
    if category.approval_threshold is not None:
        return Decimal(category.approval_threshold)
    return company_rules.approval_threshold


def initial_status(amount: Decimal, category: ExpenseCategory, company_rules: rules.CompanyRules | None = None,
                   db: Session | None = None) -> str:
    """Each company decides whether expenses need approval, and from what amount (v0.10.0)."""
    r = company_rules or (rules.current(db) if db is not None else rules.CompanyRules.model_validate(rules.defaults()))
    if not r.approvals_required:
        return "approved"
    return "pending" if amount >= _threshold_for(category, r) else "approved"


def allowed_transitions(expense: Expense, user: User) -> list[str]:
    options = sorted(TRANSITIONS.get(expense.status, set()))
    if user.access_role == "viewer":
        return []
    if user.access_role in APPROVER_ROLES:
        return options
    # Submitters may only resubmit a rejected expense.
    return [s for s in options if s == "pending"]


def _visible(stmt: Select, user: User) -> Select:
    stmt = stmt.where(Expense.is_deleted.is_(False))
    if user.access_role == "submitter":
        stmt = stmt.where(Expense.submitted_by == user.id)
    return stmt


def _load(db: Session, expense_id: uuid.UUID, user: User) -> Expense:
    expense = db.scalar(_visible(select(Expense).where(Expense.id == expense_id), user))
    if expense is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found")
    return expense


def _category(db: Session, category_id: uuid.UUID, current: uuid.UUID | None = None) -> ExpenseCategory:
    cat = db.get(ExpenseCategory, category_id)
    # An inactive category may stay on an existing expense but can't be newly chosen.
    if cat is None or (not cat.is_active and cat.id != current):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Category not found or inactive")
    return cat


def _snapshot(e: Expense) -> dict[str, object]:
    return {
        "expense_date": e.expense_date,
        "vendor": e.vendor.name if e.vendor else None,
        "category": e.category.name,
        "description": e.description,
        "amount": Decimal(e.amount),
        "payment_account": e.payment_account.name if e.payment_account else None,
        "lines": [f"{ln.category_id}:{Decimal(ln.amount):.2f}:{ln.description or ''}:{ln.billable}:{ln.customer_id}"
                  for ln in e.lines],
        "payment_method": e.payment_method,
        "is_reimbursable": e.is_reimbursable,
        "notes": e.notes,
        "invoice_number": e.invoice_number,
        "due_date": e.due_date,
    }


def _list_item(e: Expense, vendor_name: str | None, category_name: str, receipt_count: int) -> ExpenseListItem:
    return ExpenseListItem(
        id=e.id, expense_date=e.expense_date, vendor_name=vendor_name, category_id=e.category_id,
        category_name=category_name, description=e.description, amount=e.amount, currency=e.currency,
        payment_method=e.payment_method, is_reimbursable=e.is_reimbursable, status=e.status,
        receipt_count=receipt_count, created_at=e.created_at, payment_account_id=e.payment_account_id,
        payment_account_name=e.payment_account.name if e.payment_account else None,
        line_count=len(e.lines) or 1,
    )


def _detail(db: Session, e: Expense, user: User) -> ExpenseDetail:
    history_rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "expense", AuditLog.entity_id == e.id)
        .order_by(AuditLog.created_at.desc())
    ).unique()
    receipts = [ReceiptOut.model_validate(r) for r in e.receipts]
    return ExpenseDetail(
        **_list_item(e, e.vendor.name if e.vendor else None, e.category.name, len(receipts)).model_dump(),
        lines=lines_out(db, e.lines), notes=e.notes, invoice_number=e.invoice_number, due_date=e.due_date,
        bank_transaction_id=db.scalar(select(Transaction.id).where(Transaction.expense_id == e.id).limit(1)),
        approved_at=e.approved_at, paid_at=e.paid_at, receipts=receipts, custom=e.custom,
        history=[
            AuditOut(id=h.id, action=h.action, user_name=h.user.name if h.user else None,
                     changes=h.changes, created_at=h.created_at)
            for h in history_rows
        ],
        allowed_transitions=allowed_transitions(e, user),
    )


def _filtered(
    user: User,
    status_: str | None,
    category_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
    search: str | None,
    reimbursable: bool | None,
) -> Select:
    receipt_counts = (
        select(Receipt.expense_id, func.count(Receipt.id).label("n")).group_by(Receipt.expense_id).subquery()
    )
    stmt = (
        select(Expense, Vendor.name, ExpenseCategory.name, func.coalesce(receipt_counts.c.n, 0))
        .join(ExpenseCategory, Expense.category_id == ExpenseCategory.id)
        .outerjoin(Vendor, Expense.vendor_id == Vendor.id)
        .outerjoin(receipt_counts, receipt_counts.c.expense_id == Expense.id)
    )
    stmt = _visible(stmt, user)
    if status_:
        stmt = stmt.where(Expense.status == status_)
    if category_id:
        stmt = stmt.where(Expense.category_id == category_id)
    if date_from:
        stmt = stmt.where(Expense.expense_date >= date_from)
    if date_to:
        stmt = stmt.where(Expense.expense_date <= date_to)
    if reimbursable is not None:
        stmt = stmt.where(Expense.is_reimbursable.is_(reimbursable))
    if search and search.strip():
        pattern = like_pattern(search.strip())
        stmt = stmt.where(
            Expense.description.ilike(pattern, escape="\\")
            | Expense.notes.ilike(pattern, escape="\\")
            | Vendor.name.ilike(pattern, escape="\\")
        )
    return stmt


class _Filters:
    """Shared query parameters for list and CSV export."""

    def __init__(
        self,
        status: Literal["pending", "approved", "paid", "rejected"] | None = None,
        category_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        search: str | None = Query(default=None, max_length=200),
        reimbursable: bool | None = None,
        sort: SortKey = "date_desc",
    ) -> None:
        self.status = status
        self.category_id = category_id
        self.date_from = date_from
        self.date_to = date_to
        self.search = search
        self.reimbursable = reimbursable
        self.sort = sort

    def query(self, user: User) -> Select:
        stmt = _filtered(user, self.status, self.category_id, self.date_from, self.date_to,
                         self.search, self.reimbursable)
        return stmt.order_by(*_SORTS[self.sort])


# ---------- endpoints ----------
@router.get("", response_model=ExpensePage)
def list_expenses(
    filters: _Filters = Depends(),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_company),
) -> ExpensePage:
    base = filters.query(user)
    sub = base.order_by(None).with_only_columns(Expense.amount).subquery()
    total, total_amount = db.execute(
        select(func.count(), func.coalesce(func.sum(sub.c.amount), 0)).select_from(sub)
    ).one()
    rows = db.execute(base.limit(page_size).offset((page - 1) * page_size)).unique().all()
    return ExpensePage(
        items=[_list_item(e, v, c, n) for e, v, c, n in rows],
        total=total, total_amount=Decimal(total_amount), page=page, page_size=page_size,
    )


def _csv_safe(value: object) -> str:
    """Prevent spreadsheet formula injection when the CSV is opened in Excel."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/export.csv")
def export_csv(
    filters: _Filters = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(require_company),
) -> StreamingResponse:
    rows = db.execute(filters.query(user)).unique().all()

    def generate() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Date", "Vendor", "Description", "Category", "Amount", "Currency",
                         "Payment method", "Reimbursable", "Status", "Receipts", "Notes"])
        for e, vendor, category, n in rows:
            writer.writerow([
                e.expense_date.isoformat(), _csv_safe(vendor), _csv_safe(e.description), _csv_safe(category),
                f"{Decimal(e.amount):.2f}", e.currency, e.payment_method or "",
                "Yes" if e.is_reimbursable else "No", e.status, n, _csv_safe(e.notes),
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
        if not rows:
            yield buf.getvalue()

    filename = f"expenses_{date.today().isoformat()}.csv"
    return StreamingResponse(
        generate(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("", response_model=ExpenseDetail, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_company),
) -> ExpenseDetail:
    lines = _lines_or_422(payload)
    total = checked_lines(db, lines)
    category = _category(db, lines[0].category_id)
    r = rules.current(db)
    ruleutil.method(db, "expense", payload.payment_method, r=r)
    custom = ruleutil.custom(db, "expense", payload.custom, r=r)
    account = None if payload.is_reimbursable else checked_payment_account(db, payload.payment_account_id)
    vendor = get_or_create_vendor(db, payload.vendor_name)
    expense = Expense(
        expense_date=payload.expense_date, vendor_id=vendor.id if vendor else None, category_id=category.id,
        description=payload.description, amount=total, currency=current_company(db).base_currency,
        payment_method=payload.payment_method, is_reimbursable=payload.is_reimbursable, notes=payload.notes,
        invoice_number=payload.invoice_number, due_date=payload.due_date,
        payment_account_id=account.id if account else None,
        status=initial_status(total, category, r), submitted_by=user.id,
        lines=_make_lines(lines), custom=custom,
    )
    if expense.status == "approved":
        expense.approved_by, expense.approved_at = user.id, datetime.now(timezone.utc)
    db.add(expense)
    db.flush()
    db.refresh(expense)
    audit.record(db, entity_type="expense", entity_id=expense.id, action="created", user_id=user.id,
                 changes={**_snapshot(expense), "status": expense.status})
    link_to_bank_transaction(db, expense)
    db.commit()
    return _detail(db, expense, user)


def _lines_or_422(payload: ExpenseIn) -> list[LineIn]:
    try:
        return payload.resolved_lines()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None


def _make_lines(lines: list[LineIn]) -> list[ExpenseLine]:
    return [ExpenseLine(id=uuid.uuid4(), line_no=i, category_id=ln.category_id, description=ln.description,
                        amount=ln.amount, billable=ln.billable, customer_id=ln.customer_id if ln.billable or
                        ln.customer_id else None) for i, ln in enumerate(lines)]


def link_to_bank_transaction(db: Session, expense: Expense) -> None:
    """If exactly one unlinked bank charge matches this expense (same amount within 5 days, and the same
    account when the payment account is known), link them. The charge then isn't posted twice, and an
    expense without a payment account takes the charge's account."""
    if expense.is_reimbursable:
        return
    linked = select(Transaction.id).where(Transaction.expense_id == expense.id)
    if db.scalar(linked):
        return
    window = timedelta(days=5)
    stmt = select(Transaction).where(
        Transaction.expense_id.is_(None), Transaction.is_transfer.is_(False),
        Transaction.review_status != "excluded", Transaction.amount == -Decimal(expense.amount),
        Transaction.txn_date.between(expense.expense_date - window, expense.expense_date + window),
    )
    if expense.payment_account_id:
        stmt = stmt.where(Transaction.account_id == expense.payment_account_id)
    matches = list(db.scalars(stmt.limit(2)))
    if len(matches) == 1:
        matches[0].expense_id = expense.id
        if expense.payment_account_id is None:
            expense.payment_account_id = matches[0].account_id


@router.get("/{expense_id}", response_model=ExpenseDetail)
def get_expense(
    expense_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_company),
) -> ExpenseDetail:
    return _detail(db, _load(db, expense_id, user), user)


@router.put("/{expense_id}", response_model=ExpenseDetail)
def update_expense(
    expense_id: uuid.UUID,
    payload: ExpenseIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_company),
) -> ExpenseDetail:
    expense = _load(db, expense_id, user)
    if user.access_role not in APPROVER_ROLES and expense.status in ("approved", "paid"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Approved or paid expenses can only be edited by an approver")
    before = _snapshot(expense)
    ruleutil.method(db, "expense", payload.payment_method, current=expense.payment_method)
    if payload.custom is not None:
        expense.custom = ruleutil.custom(db, "expense", payload.custom, before=expense.custom)
    lines = _lines_or_422(payload)
    current = {ln.category_id for ln in expense.lines} | {expense.category_id}
    total = checked_lines(db, lines, current_categories=current)
    category = db.get(ExpenseCategory, lines[0].category_id)  # validated by checked_lines
    account = None if payload.is_reimbursable else checked_payment_account(db, payload.payment_account_id)
    if payload.is_reimbursable and expense.is_reimbursable:
        account = expense.payment_account  # keep the account they were repaid from
    vendor = get_or_create_vendor(db, payload.vendor_name)
    expense.expense_date = payload.expense_date
    expense.vendor_id = vendor.id if vendor else None
    expense.category_id = category.id
    expense.description = payload.description
    expense.amount = total
    expense.payment_account_id = account.id if account else None
    expense.lines = _make_lines(lines)
    expense.payment_method = payload.payment_method
    expense.is_reimbursable = payload.is_reimbursable
    expense.notes = payload.notes
    expense.invoice_number = payload.invoice_number
    expense.due_date = payload.due_date
    db.flush()
    db.refresh(expense)
    after = _snapshot(expense)
    changes: dict[str, object] = {k: [before[k], after[k]] for k in _TRACKED_FIELDS if before[k] != after[k]}

    # With approval enabled, raising an approved expense to/over its threshold sends it back for approval.
    if (
        rules.current(db).approvals_required
        and expense.status == "approved"
        and ("amount" in changes or "category" in changes)
        and initial_status(Decimal(expense.amount), category, db=db) == "pending"
    ):
        changes["status"] = [expense.status, "pending"]
        expense.status, expense.approved_by, expense.approved_at = "pending", None, None

    if changes:
        audit.record(db, entity_type="expense", entity_id=expense.id, action="updated", user_id=user.id,
                     changes=changes)
    db.commit()
    return _detail(db, expense, user)


@router.post("/{expense_id}/status", response_model=ExpenseDetail)
def change_status(
    expense_id: uuid.UUID,
    payload: StatusIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_company),
) -> ExpenseDetail:
    expense = _load(db, expense_id, user)
    old, new = expense.status, payload.status
    if new not in TRANSITIONS.get(old, set()):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot change status from '{old}' to '{new}'")
    if new not in allowed_transitions(expense, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission for this status change")
    now = datetime.now(timezone.utc)
    if new == "approved" and old == "pending":
        expense.approved_by, expense.approved_at = user.id, now
    elif new == "paid":
        expense.paid_at = now
        if expense.is_reimbursable and payload.payment_account_id:
            expense.payment_account_id = checked_payment_account(db, payload.payment_account_id).id
    elif new == "approved" and old == "paid":  # undo "paid"
        expense.paid_at = None
        if expense.is_reimbursable:
            expense.payment_account_id = None
    elif new in ("rejected", "pending"):
        expense.approved_by, expense.approved_at, expense.paid_at = None, None, None
    expense.status = new
    changes: dict[str, object] = {"status": [old, new]}
    if payload.note:
        changes["note"] = payload.note
    audit.record(db, entity_type="expense", entity_id=expense.id, action="status_changed", user_id=user.id,
                 changes=changes)
    db.commit()
    return _detail(db, expense, user)


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    expense_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_company),
) -> Response:
    expense = _load(db, expense_id, user)
    if user.access_role not in APPROVER_ROLES and expense.submitted_by != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete your own expenses")
    expense.is_deleted = True
    audit.record(db, entity_type="expense", entity_id=expense.id, action="deleted", user_id=user.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
