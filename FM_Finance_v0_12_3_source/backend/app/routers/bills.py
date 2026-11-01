"""Bills (money owed to vendors, Accounts Payable) and bill payments."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import audit, rules
from ..config import get_settings
from .. import modules
from ..database import get_db
from ..models import Bill, BillAttachment, BillLine, BillPayment, FinancialAccount, Transaction, User, Vendor
from ..schemas import (
    BillAttachmentOut, BillDetail, BillIn, BillListItem, BillPage, BillPaymentIn, BillPaymentOut, PeerOut,
)
from ..security import require_roles
from ..storage import ReceiptStorage, get_storage
from . import ruleutil
from .lines import checked_lines, checked_payment_account, lines_out
from .receipts import ALLOWED, _matches_signature, _safe_name
from .util import get_or_create_vendor, like_pattern

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bills", tags=["bills"],
                   dependencies=[Depends(modules.guard("bills"))])
ROLES = ("admin", "approver")
ZERO = Decimal("0")


def _paid(b: Bill) -> Decimal:
    return sum((Decimal(p.amount) for p in b.payments), ZERO)


def _status(b: Bill, today: date | None = None) -> str:
    paid = _paid(b)
    if paid >= Decimal(b.total):
        return "paid"
    if b.due_date < (today or date.today()):
        return "overdue"
    return "partial" if paid > 0 else "open"


def _item(b: Bill) -> BillListItem:
    paid = _paid(b)
    return BillListItem(
        id=b.id, vendor_id=b.vendor_id, vendor_name=b.vendor.name if b.vendor else "", bill_date=b.bill_date,
        due_date=b.due_date, terms=b.terms, bill_number=b.bill_number, total=b.total, paid=paid,
        balance=Decimal(b.total) - paid, status=_status(b), attachment_count=len(b.attachments))


def _detail(db: Session, b: Bill) -> BillDetail:
    accounts = {a.id: a.name for a in db.scalars(select(FinancialAccount))}
    return BillDetail(
        **_item(b).model_dump(), memo=b.memo, lines=lines_out(db, b.lines), custom=b.custom,
        payments=[BillPaymentOut(id=p.id, payment_date=p.payment_date, account_id=p.account_id,
                                 account_name=accounts.get(p.account_id, "?"), amount=p.amount, memo=p.memo,
                                 transaction_id=p.transaction_id) for p in b.payments],
        attachments=[BillAttachmentOut.model_validate(a) for a in b.attachments])


def _load(db: Session, bill_id: uuid.UUID) -> Bill:
    b = db.get(Bill, bill_id)
    if b is None or b.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    return b


@router.get("", response_model=BillPage)
def list_bills(
    show: Literal["unpaid", "paid", "all"] = "unpaid",
    search: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db), _: User = Depends(require_roles(*ROLES)),
) -> BillPage:
    stmt = select(Bill).join(Vendor, Vendor.id == Bill.vendor_id).where(Bill.is_deleted.is_(False))
    if search and search.strip():
        pattern = like_pattern(search.strip())
        stmt = stmt.where(or_(Vendor.name.ilike(pattern, escape="\\"), Bill.bill_number.ilike(pattern, escape="\\"),
                              Bill.memo.ilike(pattern, escape="\\")))
    bills = list(db.scalars(stmt.order_by(Bill.due_date, Bill.created_at)).unique())
    items = [_item(b) for b in bills]
    unpaid = [i for i in items if i.status != "paid"]
    if show == "unpaid":
        items = unpaid
    elif show == "paid":
        items = [i for i in items if i.status == "paid"]
        items.reverse()
    return BillPage(items=items, total_open=sum((i.balance for i in unpaid), ZERO),
                    total_overdue=sum((i.balance for i in unpaid if i.status == "overdue"), ZERO))


def _apply(db: Session, bill: Bill, payload: BillIn, current_categories: set[uuid.UUID] | None = None) -> None:
    total = checked_lines(db, payload.lines, current_categories)
    if bill.payments and total < _paid(bill):
        raise HTTPException(status.HTTP_409_CONFLICT, "The total can't be less than what's already been paid")
    vendor = get_or_create_vendor(db, payload.vendor_name)
    bill.vendor_id = vendor.id
    bill.vendor = vendor
    bill.bill_date = payload.bill_date
    r = rules.current(db)
    terms = payload.terms
    if terms is None and payload.due_date is None:
        terms = r.bill_default_terms
    else:
        ruleutil.term(db, terms, current=bill.terms, r=r)
    bill.terms = terms
    bill.due_date = payload.due_date or r.due_date(payload.bill_date, terms)
    if payload.custom is not None or bill.custom is None:
        bill.custom = ruleutil.custom(db, "bill", payload.custom, before=bill.custom, r=r)
    if bill.due_date < bill.bill_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The due date can't be before the bill date")
    bill.bill_number = payload.bill_number
    bill.memo = payload.memo
    bill.total = total
    bill.lines = [BillLine(id=uuid.uuid4(), line_no=i, category_id=ln.category_id, description=ln.description,
                           amount=ln.amount, billable=ln.billable, customer_id=ln.customer_id)
                  for i, ln in enumerate(payload.lines)]


@router.post("", response_model=BillDetail, status_code=status.HTTP_201_CREATED)
def create_bill(payload: BillIn, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*ROLES))) -> BillDetail:
    bill = Bill(id=uuid.uuid4(), created_by=user.id)
    _apply(db, bill, payload)
    db.add(bill)
    db.flush()
    audit.record(db, entity_type="bill", entity_id=bill.id, action="created", user_id=user.id,
                 changes={"vendor": payload.vendor_name, "total": bill.total, "due": bill.due_date,
                          "number": bill.bill_number})
    db.commit()
    return _detail(db, bill)


@router.get("/{bill_id}", response_model=BillDetail)
def get_bill(bill_id: uuid.UUID, db: Session = Depends(get_db),
             _: User = Depends(require_roles(*ROLES))) -> BillDetail:
    return _detail(db, _load(db, bill_id))


@router.put("/{bill_id}", response_model=BillDetail)
def update_bill(bill_id: uuid.UUID, payload: BillIn, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*ROLES))) -> BillDetail:
    bill = _load(db, bill_id)
    before = {"total": bill.total, "due": bill.due_date, "number": bill.bill_number}
    _apply(db, bill, payload, {ln.category_id for ln in bill.lines})
    audit.record(db, entity_type="bill", entity_id=bill.id, action="updated", user_id=user.id,
                 changes={"before": before, "after": {"total": bill.total, "due": bill.due_date,
                                                      "number": bill.bill_number}})
    db.commit()
    return _detail(db, bill)


@router.delete("/{bill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bill(bill_id: uuid.UUID, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*ROLES))) -> Response:
    bill = _load(db, bill_id)
    if bill.payments:
        raise HTTPException(status.HTTP_409_CONFLICT, "Delete this bill's payments first")
    bill.is_deleted = True
    audit.record(db, entity_type="bill", entity_id=bill.id, action="deleted", user_id=user.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- payments
def _payment_candidates(db: Session, account_id: uuid.UUID, amount: Decimal, near: date) -> list[Transaction]:
    taken = select(BillPayment.transaction_id).where(BillPayment.transaction_id.is_not(None))
    return list(db.scalars(select(Transaction).where(
        Transaction.account_id == account_id, Transaction.amount == -amount, Transaction.is_transfer.is_(False),
        Transaction.expense_id.is_(None), Transaction.review_status != "excluded", Transaction.id.not_in(taken),
        Transaction.txn_date.between(near - timedelta(days=10), near + timedelta(days=10)),
    ).order_by(Transaction.txn_date)))


@router.get("/{bill_id}/payment-candidates", response_model=list[PeerOut])
def payment_candidates(bill_id: uuid.UUID, account_id: uuid.UUID, amount: Decimal, payment_date: date,
                       db: Session = Depends(get_db), _: User = Depends(require_roles(*ROLES))) -> list[PeerOut]:
    _load(db, bill_id)
    account = checked_payment_account(db, account_id)
    return [PeerOut(id=t.id, account_id=t.account_id, account_name=account.name, txn_date=t.txn_date,
                    amount=t.amount, description=t.description, review_status=t.review_status)
            for t in _payment_candidates(db, account.id, amount, payment_date)]


@router.post("/{bill_id}/payments", response_model=BillDetail, status_code=status.HTTP_201_CREATED)
def pay_bill(bill_id: uuid.UUID, payload: BillPaymentIn, db: Session = Depends(get_db),
             user: User = Depends(require_roles(*ROLES))) -> BillDetail:
    bill = _load(db, bill_id)
    account = checked_payment_account(db, payload.account_id)
    balance = Decimal(bill.total) - _paid(bill)
    if payload.amount > balance:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"The bill only has {balance:,.2f} left to pay")
    if payload.payment_date < bill.bill_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The payment can't be before the bill date")
    txn = None
    if payload.transaction_id:
        ok = {t.id for t in _payment_candidates(db, account.id, payload.amount, payload.payment_date)}
        if payload.transaction_id not in ok:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "That bank transaction doesn't match this payment's account and amount")
        txn = db.get(Transaction, payload.transaction_id)
    payment = BillPayment(id=uuid.uuid4(), bill_id=bill.id, payment_date=payload.payment_date, account_id=account.id,
                          amount=payload.amount, memo=payload.memo, transaction_id=txn.id if txn else None,
                          created_by=user.id)
    bill.payments.append(payment)
    if txn is not None and txn.review_status != "approved":
        # Matching a bank charge to the payment is the review: QuickBooks approves it the same way.
        txn.review_status, txn.approved_by, txn.approved_at = "approved", user.id, datetime.now(timezone.utc)
        txn.duplicate_of_id = None
    audit.record(db, entity_type="bill", entity_id=bill.id, action="payment_added", user_id=user.id,
                 changes={"amount": payload.amount, "account": account.name, "date": payload.payment_date,
                          "matched_transaction": txn.id if txn else None})
    db.commit()
    return _detail(db, bill)


@router.delete("/{bill_id}/payments/{payment_id}", response_model=BillDetail)
def delete_payment(bill_id: uuid.UUID, payment_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(require_roles(*ROLES))) -> BillDetail:
    bill = _load(db, bill_id)
    payment = next((p for p in bill.payments if p.id == payment_id), None)
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    if payment.transaction_id:
        txn = db.get(Transaction, payment.transaction_id)
        if txn is not None:
            # The charge goes back to For review so it can be matched or categorized again.
            txn.review_status, txn.approved_by, txn.approved_at = "unreviewed", None, None
    bill.payments.remove(payment)
    db.delete(payment)
    audit.record(db, entity_type="bill", entity_id=bill.id, action="payment_removed", user_id=user.id,
                 changes={"amount": payment.amount, "date": payment.payment_date})
    db.commit()
    db.refresh(bill)
    return _detail(db, bill)


# ---------------------------------------------------------------- attachments
@router.post("/{bill_id}/attachments", response_model=BillAttachmentOut, status_code=status.HTTP_201_CREATED)
async def add_attachment(bill_id: uuid.UUID, file: UploadFile = File(...), db: Session = Depends(get_db),
                         user: User = Depends(require_roles(*ROLES)),
                         storage: ReceiptStorage = Depends(get_storage)) -> BillAttachment:
    bill = _load(db, bill_id)
    original = _safe_name(file.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in ALLOWED:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Attach a PDF, photo, Word file or email")
    limit = get_settings().MAX_RECEIPT_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"File exceeds the {get_settings().MAX_RECEIPT_MB} MB limit")
    if not data or not _matches_signature(ext, data[:16]):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "File content does not match its type")
    now = datetime.now(timezone.utc)
    key = f"{now:%Y}/{now:%m}/{bill.id}/{uuid.uuid4()}.{ext}"
    storage.put(key, data, ALLOWED[ext])
    try:
        att = BillAttachment(bill_id=bill.id, object_key=key, original_filename=original, content_type=ALLOWED[ext],
                             size_bytes=len(data), uploaded_by=user.id)
        db.add(att)
        audit.record(db, entity_type="bill", entity_id=bill.id, action="attachment_added", user_id=user.id,
                     changes={"filename": original})
        db.commit()
        db.refresh(att)
    except Exception:
        db.rollback()
        try:
            storage.delete(key)
        except Exception:  # noqa: BLE001
            log.warning("Could not clean up orphaned bill attachment %s", key)
        raise
    return att


def _load_attachment(db: Session, bill_id: uuid.UUID, attachment_id: uuid.UUID) -> BillAttachment:
    _load(db, bill_id)
    att = db.get(BillAttachment, attachment_id)
    if att is None or att.bill_id != bill_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    return att


@router.get("/{bill_id}/attachments/{attachment_id}/content")
def attachment_content(bill_id: uuid.UUID, attachment_id: uuid.UUID, download: bool = False,
                       db: Session = Depends(get_db), _: User = Depends(require_roles(*ROLES)),
                       storage: ReceiptStorage = Depends(get_storage)) -> StreamingResponse:
    att = _load_attachment(db, bill_id, attachment_id)
    disposition = "attachment" if download else "inline"
    return StreamingResponse(storage.open(att.object_key), media_type=att.content_type, headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(att.original_filename)}",
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/{bill_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(bill_id: uuid.UUID, attachment_id: uuid.UUID, db: Session = Depends(get_db),
                      user: User = Depends(require_roles(*ROLES)),
                      storage: ReceiptStorage = Depends(get_storage)) -> Response:
    att = _load_attachment(db, bill_id, attachment_id)
    key = att.object_key
    db.delete(att)
    audit.record(db, entity_type="bill", entity_id=bill_id, action="attachment_removed", user_id=user.id,
                 changes={"filename": att.original_filename})
    db.commit()
    try:
        storage.delete(key)
    except Exception:  # noqa: BLE001
        log.warning("Bill attachment record removed but file %s could not be deleted", key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
