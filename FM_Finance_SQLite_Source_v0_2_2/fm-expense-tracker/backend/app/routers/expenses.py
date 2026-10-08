# Note: no "from __future__ import annotations" here; FastAPI must resolve the
# _Filters class-dependency annotations at runtime.
import csv
import io
import uuid
from collections.abc import Iterator
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..models import AuditLog, Expense, ExpenseCategory, Receipt, User, Vendor
from ..schemas import AuditOut, ExpenseDetail, ExpenseIn, ExpenseListItem, ExpensePage, ReceiptOut, StatusIn
from ..security import current_user
from .util import get_or_create_vendor, like_pattern

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
    "expense_date", "vendor", "category", "description", "amount",
    "payment_method", "is_reimbursable", "notes",
)


# ---------- helpers ----------
def _threshold_for(category: ExpenseCategory) -> Decimal:
    if category.approval_threshold is not None:
        return Decimal(category.approval_threshold)
    return get_settings().DEFAULT_APPROVAL_THRESHOLD


def initial_status(amount: Decimal, category: ExpenseCategory) -> str:
    if not get_settings().APPROVAL_REQUIRED:
        return "approved"
    return "pending" if amount >= _threshold_for(category) else "approved"


def allowed_transitions(expense: Expense, user: User) -> list[str]:
    options = sorted(TRANSITIONS.get(expense.status, set()))
    if user.role in APPROVER_ROLES:
        return options
    # Submitters may only resubmit a rejected expense.
    return [s for s in options if s == "pending"]


def _visible(stmt: Select, user: User) -> Select:
    stmt = stmt.where(Expense.is_deleted.is_(False))
    if user.role == "submitter":
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
        "payment_method": e.payment_method,
        "is_reimbursable": e.is_reimbursable,
        "notes": e.notes,
    }


def _list_item(e: Expense, vendor_name: str | None, category_name: str, receipt_count: int) -> ExpenseListItem:
    return ExpenseListItem(
        id=e.id, expense_date=e.expense_date, vendor_name=vendor_name, category_id=e.category_id,
        category_name=category_name, description=e.description, amount=e.amount, currency=e.currency,
        payment_method=e.payment_method, is_reimbursable=e.is_reimbursable, status=e.status,
        receipt_count=receipt_count, created_at=e.created_at,
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
        notes=e.notes, approved_at=e.approved_at, paid_at=e.paid_at, receipts=receipts,
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
    user: User = Depends(current_user),
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
    user: User = Depends(current_user),
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
    user: User = Depends(current_user),
) -> ExpenseDetail:
    category = _category(db, payload.category_id)
    vendor = get_or_create_vendor(db, payload.vendor_name)
    expense = Expense(
        expense_date=payload.expense_date, vendor_id=vendor.id if vendor else None, category_id=category.id,
        description=payload.description, amount=payload.amount, currency=get_settings().CURRENCY,
        payment_method=payload.payment_method, is_reimbursable=payload.is_reimbursable, notes=payload.notes,
        status=initial_status(payload.amount, category), submitted_by=user.id,
    )
    if expense.status == "approved":
        expense.approved_by, expense.approved_at = user.id, datetime.now(timezone.utc)
    db.add(expense)
    db.flush()
    db.refresh(expense)
    audit.record(db, entity_type="expense", entity_id=expense.id, action="created", user_id=user.id,
                 changes={**_snapshot(expense), "status": expense.status})
    db.commit()
    return _detail(db, expense, user)


@router.get("/{expense_id}", response_model=ExpenseDetail)
def get_expense(
    expense_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ExpenseDetail:
    return _detail(db, _load(db, expense_id, user), user)


@router.put("/{expense_id}", response_model=ExpenseDetail)
def update_expense(
    expense_id: uuid.UUID,
    payload: ExpenseIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ExpenseDetail:
    expense = _load(db, expense_id, user)
    if user.role not in APPROVER_ROLES and expense.status in ("approved", "paid"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Approved or paid expenses can only be edited by an approver")
    before = _snapshot(expense)
    category = _category(db, payload.category_id, current=expense.category_id)
    vendor = get_or_create_vendor(db, payload.vendor_name)
    expense.expense_date = payload.expense_date
    expense.vendor_id = vendor.id if vendor else None
    expense.category_id = category.id
    expense.description = payload.description
    expense.amount = payload.amount
    expense.payment_method = payload.payment_method
    expense.is_reimbursable = payload.is_reimbursable
    expense.notes = payload.notes
    db.flush()
    db.refresh(expense)
    after = _snapshot(expense)
    changes: dict[str, object] = {k: [before[k], after[k]] for k in _TRACKED_FIELDS if before[k] != after[k]}

    # With approval enabled, raising an approved expense to/over its threshold sends it back for approval.
    if (
        get_settings().APPROVAL_REQUIRED
        and expense.status == "approved"
        and ("amount" in changes or "category" in changes)
        and initial_status(Decimal(expense.amount), category) == "pending"
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
    user: User = Depends(current_user),
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
    elif new == "approved" and old == "paid":  # undo "paid"
        expense.paid_at = None
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
    user: User = Depends(current_user),
) -> Response:
    expense = _load(db, expense_id, user)
    if user.role not in APPROVER_ROLES and expense.submitted_by != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete your own expenses")
    expense.is_deleted = True
    audit.record(db, entity_type="expense", entity_id=expense.id, action="deleted", user_id=user.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
