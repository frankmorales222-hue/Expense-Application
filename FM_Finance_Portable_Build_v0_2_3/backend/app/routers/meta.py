from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_settings
from ..database import get_db
from ..models import User
from ..schemas import AppSettingsOut
from ..security import current_user
from ..storage import ReceiptStorage, get_storage

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health")
def health(db: Session = Depends(get_db), storage: ReceiptStorage = Depends(get_storage)) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        log.exception("Health check: database unreachable")
        db_ok = False
    try:
        storage_ok = storage.ping()
    except Exception:  # noqa: BLE001
        storage_ok = False
    body = {
        "status": "ok" if db_ok and storage_ok else ("degraded" if db_ok else "down"),
        "version": __version__,
        "database": "ok" if db_ok else "unreachable",
        "storage": "ok" if storage_ok else "unreachable",
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)


@router.get("/settings", response_model=AppSettingsOut)
def app_settings(_: User = Depends(current_user)) -> AppSettingsOut:
    s = get_settings()
    return AppSettingsOut(
        version=__version__, currency=s.CURRENCY, approval_required=s.APPROVAL_REQUIRED,
        default_approval_threshold=s.DEFAULT_APPROVAL_THRESHOLD, max_receipt_mb=s.MAX_RECEIPT_MB,
    )
