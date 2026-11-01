"""Monthly bank and credit-card statement reconciliation."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..models import FinancialAccount, Reconciliation, Transaction, User
from ..schemas import ReconciliationOut, ReconciliationSelectionIn, ReconciliationStartIn, ReconciliationSummary
from ..security import require_roles
from ..storage import ReceiptStorage, get_storage
from .accounts import load_account
from .receipts import ALLOWED, _matches_signature, _safe_name
from .transactions import serialize
from .util import current_company

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reconciliations", tags=["reconciliations"])
ROLES = ("admin", "approver")
ZERO = Decimal("0.00")
STATEMENT_TYPES = {k: v for k, v in ALLOWED.items() if k in ("pdf", "jpg", "jpeg", "png")}


def _load(db: Session, reconciliation_id: uuid.UUID) -> Reconciliation:
    item = db.get(Reconciliation, reconciliation_id)
    if item is None or item.company_id != current_company(db).id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reconciliation not found")
    return item


def _selected(db: Session, item: Reconciliation) -> list[Transaction]:
    return list(db.scalars(select(Transaction).where(Transaction.reconciliation_id == item.id)
                           .order_by(Transaction.txn_date, Transaction.created_at)))


def _recalculate(db: Session, item: Reconciliation) -> None:
    total = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0))
                      .where(Transaction.reconciliation_id == item.id)) or ZERO
    item.cleared_balance = (Decimal(item.beginning_balance) + Decimal(total)).quantize(Decimal("0.01"))
    item.difference = (Decimal(item.ending_balance) - Decimal(item.cleared_balance)).quantize(Decimal("0.01"))


def _summary(db: Session, item: Reconciliation) -> ReconciliationSummary:
    count = db.scalar(select(func.count(Transaction.id)).where(Transaction.reconciliation_id == item.id)) or 0
    completed_name = None
    if item.completed_by:
        completed = db.get(User, item.completed_by)
        completed_name = completed.name if completed else None
    return ReconciliationSummary(
        id=item.id, account_id=item.account_id, account_name=item.account.name, account_kind=item.account.kind,
        statement_date=item.statement_date, beginning_balance=item.beginning_balance,
        ending_balance=item.ending_balance, cleared_balance=item.cleared_balance, difference=item.difference,
        status=item.status, transaction_count=count, statement_filename=item.statement_filename,
        statement_size_bytes=item.statement_size_bytes, notes=item.notes, created_at=item.created_at,
        completed_at=item.completed_at, completed_by_name=completed_name,
    )


def _detail(db: Session, item: Reconciliation) -> ReconciliationOut:
    summary = _summary(db, item)
    if item.status == "completed":
        txns = _selected(db, item)
    else:
        txns = list(db.scalars(select(Transaction).where(
            Transaction.account_id == item.account_id,
            Transaction.txn_date <= item.statement_date,
            Transaction.review_status == "approved",
            Transaction.reconciled.is_(False),
            or_(Transaction.reconciliation_id.is_(None), Transaction.reconciliation_id == item.id),
        ).order_by(Transaction.txn_date, Transaction.created_at)))
    return ReconciliationOut(**summary.model_dump(), transactions=serialize(db, txns))


@router.get("", response_model=list[ReconciliationSummary])
def list_reconciliations(account_id: uuid.UUID | None = None, db: Session = Depends(get_db),
                         _: User = Depends(require_roles(*ROLES))) -> list[ReconciliationSummary]:
    stmt = select(Reconciliation).order_by(Reconciliation.statement_date.desc(), Reconciliation.created_at.desc())
    if account_id:
        stmt = stmt.where(Reconciliation.account_id == account_id)
    return [_summary(db, item) for item in db.scalars(stmt)]


@router.post("", response_model=ReconciliationOut, status_code=status.HTTP_201_CREATED)
def start_reconciliation(payload: ReconciliationStartIn, db: Session = Depends(get_db),
                         user: User = Depends(require_roles(*ROLES))) -> ReconciliationOut:
    account = load_account(db, payload.account_id)
    draft = db.scalar(select(Reconciliation).where(Reconciliation.account_id == account.id,
                                                    Reconciliation.status == "draft"))
    if draft:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{account.name} already has a reconciliation in progress")
    previous = db.scalar(select(Reconciliation).where(
        Reconciliation.account_id == account.id, Reconciliation.status == "completed")
        .order_by(Reconciliation.statement_date.desc()).limit(1))
    if previous and payload.statement_date <= previous.statement_date:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Use a statement date after {previous.statement_date.isoformat()}")
    beginning = Decimal(previous.ending_balance if previous else account.opening_balance)
    item = Reconciliation(account_id=account.id, statement_date=payload.statement_date,
                          beginning_balance=beginning, ending_balance=payload.ending_balance,
                          cleared_balance=beginning, difference=Decimal(payload.ending_balance) - beginning,
                          notes=(payload.notes or "").strip() or None, started_by=user.id)
    db.add(item)
    db.flush()
    audit.record(db, entity_type="reconciliation", entity_id=item.id, action="started", user_id=user.id,
                 changes={"account": account.name, "statement_date": item.statement_date,
                          "beginning_balance": beginning, "ending_balance": item.ending_balance})
    db.commit()
    return _detail(db, item)


@router.get("/{reconciliation_id}", response_model=ReconciliationOut)
def get_reconciliation(reconciliation_id: uuid.UUID, db: Session = Depends(get_db),
                       _: User = Depends(require_roles(*ROLES))) -> ReconciliationOut:
    return _detail(db, _load(db, reconciliation_id))


@router.put("/{reconciliation_id}/selection", response_model=ReconciliationOut)
def save_selection(reconciliation_id: uuid.UUID, payload: ReconciliationSelectionIn,
                   db: Session = Depends(get_db), user: User = Depends(require_roles(*ROLES))) -> ReconciliationOut:
    item = _load(db, reconciliation_id)
    if item.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "A completed reconciliation cannot be changed")
    ids = set(payload.transaction_ids)
    candidates = list(db.scalars(select(Transaction).where(
        Transaction.account_id == item.account_id,
        Transaction.txn_date <= item.statement_date,
        Transaction.review_status == "approved",
        Transaction.reconciled.is_(False),
        or_(Transaction.reconciliation_id.is_(None), Transaction.reconciliation_id == item.id),
    )))
    allowed = {t.id: t for t in candidates}
    if ids - set(allowed):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "One or more selected transactions are not eligible for this statement")
    for txn in candidates:
        txn.reconciliation_id = item.id if txn.id in ids else None
    db.flush()
    _recalculate(db, item)
    audit.record(db, entity_type="reconciliation", entity_id=item.id, action="selection_saved", user_id=user.id,
                 changes={"transaction_count": len(ids), "difference": item.difference})
    db.commit()
    return _detail(db, item)


@router.post("/{reconciliation_id}/complete", response_model=ReconciliationOut)
def complete_reconciliation(reconciliation_id: uuid.UUID, db: Session = Depends(get_db),
                            user: User = Depends(require_roles(*ROLES))) -> ReconciliationOut:
    item = _load(db, reconciliation_id)
    if item.status != "draft":
        return _detail(db, item)
    _recalculate(db, item)
    if Decimal(item.difference) != ZERO:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"The statement is out of balance by {abs(Decimal(item.difference)):,.2f}")
    txns = _selected(db, item)
    for txn in txns:
        txn.reconciled = True
    item.status = "completed"
    item.completed_by = user.id
    item.completed_at = datetime.now(timezone.utc)
    audit.record(db, entity_type="reconciliation", entity_id=item.id, action="completed", user_id=user.id,
                 changes={"account": item.account.name, "statement_date": item.statement_date,
                          "ending_balance": item.ending_balance, "transaction_count": len(txns)})
    db.commit()
    return _detail(db, item)


@router.delete("/{reconciliation_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_reconciliation(reconciliation_id: uuid.UUID, db: Session = Depends(get_db),
                          user: User = Depends(require_roles(*ROLES)),
                          storage: ReceiptStorage = Depends(get_storage)) -> Response:
    item = _load(db, reconciliation_id)
    if item.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "Completed reconciliations are permanent")
    key = item.statement_object_key
    for txn in _selected(db, item):
        txn.reconciliation_id = None
    audit.record(db, entity_type="reconciliation", entity_id=item.id, action="cancelled", user_id=user.id,
                 changes={"account": item.account.name, "statement_date": item.statement_date})
    db.delete(item)
    db.commit()
    if key:
        try:
            storage.delete(key)
        except Exception:  # noqa: BLE001
            log.warning("Could not remove cancelled reconciliation statement %s", key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{reconciliation_id}/statement", response_model=ReconciliationOut)
async def upload_statement(reconciliation_id: uuid.UUID, file: UploadFile = File(...),
                           db: Session = Depends(get_db), user: User = Depends(require_roles(*ROLES)),
                           storage: ReceiptStorage = Depends(get_storage)) -> ReconciliationOut:
    item = _load(db, reconciliation_id)
    original = _safe_name(file.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in STATEMENT_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Attach a PDF, JPG or PNG bank statement")
    limit = get_settings().MAX_RECEIPT_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"File exceeds the {get_settings().MAX_RECEIPT_MB} MB limit")
    if not data or not _matches_signature(ext, data[:16]):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "File content does not match its type")
    now = datetime.now(timezone.utc)
    key = f"{now:%Y}/{now:%m}/{item.id}/{uuid.uuid4()}.{ext}"
    old = item.statement_object_key
    storage.put(key, data, STATEMENT_TYPES[ext])
    item.statement_object_key, item.statement_filename = key, original
    item.statement_content_type, item.statement_size_bytes = STATEMENT_TYPES[ext], len(data)
    audit.record(db, entity_type="reconciliation", entity_id=item.id, action="statement_attached", user_id=user.id,
                 changes={"filename": original})
    db.commit()
    if old:
        try:
            storage.delete(old)
        except Exception:  # noqa: BLE001
            log.warning("Could not remove replaced reconciliation statement %s", old)
    return _detail(db, item)


@router.get("/{reconciliation_id}/statement")
def download_statement(reconciliation_id: uuid.UUID, db: Session = Depends(get_db),
                       _: User = Depends(require_roles(*ROLES)),
                       storage: ReceiptStorage = Depends(get_storage)) -> StreamingResponse:
    item = _load(db, reconciliation_id)
    if not item.statement_object_key or not item.statement_filename:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No statement is attached")
    return StreamingResponse(storage.open(item.statement_object_key), media_type=item.statement_content_type,
                             headers={"Content-Disposition":
                                      f"attachment; filename*=UTF-8''{quote(item.statement_filename)}",
                                      "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
