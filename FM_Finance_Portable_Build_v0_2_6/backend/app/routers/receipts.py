from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import PurePath
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..database import get_db
from ..models import Receipt, User
from ..schemas import ReceiptOut
from ..security import current_user
from ..storage import ReceiptStorage, get_storage
from .expenses import APPROVER_ROLES, _load

log = logging.getLogger(__name__)
router = APIRouter(tags=["receipts"])

ALLOWED: dict[str, str] = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "heic": "image/heic",
}


def _matches_signature(ext: str, head: bytes) -> bool:
    """Check file magic bytes so a renamed executable can't be stored as a 'receipt'."""
    if ext == "pdf":
        return head.startswith(b"%PDF")
    if ext in ("jpg", "jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == "png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == "heic":
        return head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc", b"heim", b"heis")
    return False


def _safe_name(filename: str | None) -> str:
    name = PurePath((filename or "receipt").replace("\\", "/")).name.strip() or "receipt"
    return name[:255]


@router.post("/api/expenses/{expense_id}/receipts", response_model=ReceiptOut, status_code=status.HTTP_201_CREATED)
async def upload_receipt(
    expense_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    storage: ReceiptStorage = Depends(get_storage),
) -> Receipt:
    expense = _load(db, expense_id, user)
    original = _safe_name(file.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in ALLOWED:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Allowed file types: PDF, JPG, PNG, HEIC")

    limit = get_settings().MAX_RECEIPT_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"File exceeds the {get_settings().MAX_RECEIPT_MB} MB limit")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty")
    if not _matches_signature(ext, data[:16]):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "File content does not match its type")

    now = datetime.now(timezone.utc)
    key = f"{now:%Y}/{now:%m}/{expense.id}/{uuid.uuid4()}.{ext}"
    content_type = ALLOWED[ext]
    storage.put(key, data, content_type)
    try:
        receipt = Receipt(expense_id=expense.id, object_key=key, original_filename=original,
                          content_type=content_type, size_bytes=len(data), uploaded_by=user.id)
        db.add(receipt)
        db.flush()
        audit.record(db, entity_type="expense", entity_id=expense.id, action="receipt_added", user_id=user.id,
                     changes={"filename": original})
        db.commit()
        db.refresh(receipt)
    except Exception:
        db.rollback()
        try:
            storage.delete(key)  # don't leave an orphaned object behind
        except Exception:  # noqa: BLE001 - best-effort cleanup
            log.warning("Could not clean up orphaned receipt object %s", key)
        raise
    return receipt


def _load_receipt(db: Session, receipt_id: uuid.UUID, user: User) -> Receipt:
    receipt = db.get(Receipt, receipt_id)
    if receipt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt not found")
    _load(db, receipt.expense_id, user)  # enforces visibility / soft delete
    return receipt


@router.get("/api/receipts/{receipt_id}/content")
def receipt_content(
    receipt_id: uuid.UUID,
    download: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    storage: ReceiptStorage = Depends(get_storage),
) -> StreamingResponse:
    receipt = _load_receipt(db, receipt_id, user)
    stream = storage.open(receipt.object_key)
    disposition = "attachment" if download else "inline"
    return StreamingResponse(
        stream,
        media_type=receipt.content_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(receipt.original_filename)}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/api/receipts/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt(
    receipt_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    storage: ReceiptStorage = Depends(get_storage),
) -> Response:
    receipt = _load_receipt(db, receipt_id, user)
    if user.role not in APPROVER_ROLES and receipt.uploaded_by != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete receipts you uploaded")
    storage.delete(receipt.object_key)
    audit.record(db, entity_type="expense", entity_id=receipt.expense_id, action="receipt_removed",
                 user_id=user.id, changes={"filename": receipt.original_filename})
    db.delete(receipt)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
