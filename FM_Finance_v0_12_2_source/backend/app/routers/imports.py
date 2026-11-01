from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..banking.engine import import_rows, suggest
from ..banking.importers import MAX_FILE_BYTES, ImportFormatError, ParseResult, parse_file
from ..database import get_db
from ..models import FinancialAccount, ImportBatch, Transaction, User
from ..schemas import CsvMapping, ImportBatchOut, ImportPreviewOut, PreviewRow
from ..security import require_roles
from .accounts import load_account
from .util import current_company

router = APIRouter(prefix="/api/imports", tags=["imports"])
ROLES = ("admin", "approver")


async def _read(file: UploadFile) -> tuple[str, bytes]:
    data = await file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The file is larger than 5 MB.")
    name = (file.filename or "statement").replace("\\", "/").rsplit("/", 1)[-1][:255] or "statement"
    return name, data


def _mapping(raw: str | None, account: FinancialAccount) -> dict | None:
    if raw:
        try:
            return CsvMapping.model_validate(json.loads(raw)).model_dump()
        except (ValueError, ValidationError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid column mapping") from None
    return account.csv_profile or None


def _parse(name: str, data: bytes, mapping: dict | None, account: FinancialAccount) -> ParseResult:
    try:
        return parse_file(name, data, mapping, account.kind)
    except ImportFormatError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None


@router.post("/preview", response_model=ImportPreviewOut)
async def preview(
    account_id: uuid.UUID = Form(...),
    mapping: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*ROLES)),
) -> ImportPreviewOut:
    account = load_account(db, account_id)
    name, data = await _read(file)
    result = _parse(name, data, _mapping(mapping, account), account)
    valid = result.valid
    digest = hashlib.sha256(data).hexdigest()
    seen = db.scalar(select(func.count(ImportBatch.id)).where(
        ImportBatch.account_id == account.id, ImportBatch.file_sha256 == digest, ImportBatch.status == "active"))
    dates = [r.txn_date for r in valid if r.txn_date]
    return ImportPreviewOut(
        source=result.source, filename=name, total_rows=len(result.rows), valid_rows=len(valid),
        invalid_rows=len(result.rows) - len(valid),
        date_from=min(dates) if dates else None, date_to=max(dates) if dates else None,
        money_in=sum((r.amount for r in valid if r.amount and r.amount > 0), Decimal("0")),
        money_out=-sum((r.amount for r in valid if r.amount and r.amount < 0), Decimal("0")),
        rows=[PreviewRow(line=r.line, txn_date=r.txn_date, amount=r.amount, description=r.description,
                         error=r.error) for r in result.rows[:25]],
        headers=result.info.get("headers", []), sample=result.info.get("sample", []),
        mapping=CsvMapping(**result.info["mapping"]) if result.source == "csv" else None,
        problems=result.info.get("problems", []),
        file_account_last4=result.info.get("account_last4"),
        previously_imported=bool(seen),
    )


@router.post("", response_model=ImportBatchOut, status_code=status.HTTP_201_CREATED)
async def commit_import(
    account_id: uuid.UUID = Form(...),
    mapping: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ROLES)),
) -> ImportBatchOut:
    account = load_account(db, account_id)
    if not account.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "This account is inactive")
    name, data = await _read(file)
    used_mapping = _mapping(mapping, account)
    result = _parse(name, data, used_mapping, account)
    if result.info.get("problems"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, " ".join(result.info["problems"]))
    if not result.valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No readable transactions in this file.")
    batch = ImportBatch(id=uuid.uuid4(), company_id=account.company_id, account_id=account.id,
                        source=result.source, filename=name, file_sha256=hashlib.sha256(data).hexdigest(),
                        created_by=user.id)
    db.add(batch)
    db.flush()
    import_rows(db, account=account, batch=batch, rows=result.rows)
    db.flush()
    from ..banking.engine import approve_by_rules

    approve_by_rules(db, user)  # v0.10.0: rules set to approve automatically
    if result.source == "csv":
        account.csv_profile = result.info["profile"]
    audit.record(db, entity_type="import", entity_id=batch.id, action="imported", user_id=user.id, changes={
        "account": account.name, "filename": name, "imported": batch.rows_imported,
        "duplicates": batch.rows_duplicate, "invalid": batch.rows_invalid, "flagged": batch.rows_flagged})
    db.commit()
    out = ImportBatchOut.model_validate(batch)
    out.account_name = account.name
    return out


@router.get("", response_model=list[ImportBatchOut])
def list_imports(account_id: uuid.UUID | None = None, db: Session = Depends(get_db),
                 _: User = Depends(require_roles(*ROLES))) -> list[ImportBatchOut]:
    stmt = (select(ImportBatch, FinancialAccount.name)
            .join(FinancialAccount, ImportBatch.account_id == FinancialAccount.id)
            .where(ImportBatch.company_id == current_company(db).id)
            .order_by(ImportBatch.created_at.desc()).limit(100))
    if account_id:
        stmt = stmt.where(ImportBatch.account_id == account_id)
    approved = dict(db.execute(
        select(Transaction.import_batch_id, func.count(Transaction.id))
        .where(Transaction.review_status == "approved", Transaction.import_batch_id.is_not(None))
        .group_by(Transaction.import_batch_id)).all())
    out = []
    for batch, account_name in db.execute(stmt).all():
        item = ImportBatchOut.model_validate(batch)
        item.account_name = account_name
        item.approved_count = approved.get(batch.id, 0)
        out.append(item)
    return out


@router.post("/{batch_id}/undo", response_model=ImportBatchOut)
def undo_import(batch_id: uuid.UUID, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*ROLES))) -> ImportBatchOut:
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.company_id != current_company(db).id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    if batch.status == "undone":
        raise HTTPException(status.HTTP_409_CONFLICT, "This import was already undone")
    txns = list(db.scalars(select(Transaction).where(Transaction.import_batch_id == batch.id)))
    approved = sum(1 for t in txns if t.review_status == "approved")
    if approved:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{approved} transaction(s) from this import are approved. "
                            "Move them back to review before undoing the import.")
    ids = {t.id for t in txns}
    if ids:
        # Detach anything elsewhere that points at these rows.
        orphaned: list[Transaction] = []
        for other in db.scalars(select(Transaction).where(
                Transaction.id.not_in(ids),
                (Transaction.transfer_peer_id.in_(ids)) | (Transaction.duplicate_of_id.in_(ids)))):
            if other.transfer_peer_id in ids:
                other.is_transfer, other.transfer_peer_id, other.confidence, other.suggestion_reason = \
                    False, None, 0, None
                orphaned.append(other)
            if other.duplicate_of_id in ids:
                other.duplicate_of_id = None
        for t in txns:
            t.transfer_peer_id, t.duplicate_of_id = None, None
        db.flush()
        for t in txns:
            db.delete(t)
        db.flush()
        suggest(db, orphaned)
    batch.status = "undone"
    audit.record(db, entity_type="import", entity_id=batch.id, action="undone", user_id=user.id,
                 changes={"removed": len(txns), "filename": batch.filename})
    db.commit()
    account = db.get(FinancialAccount, batch.account_id)
    out = ImportBatchOut.model_validate(batch)
    out.account_name = account.name if account else ""
    return out
