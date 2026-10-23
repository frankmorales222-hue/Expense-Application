from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_settings
from ..database import get_db
from ..models import User
from ..schemas import AppSettingsOut
from ..security import current_user, require_roles
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
        "app": "fm-finance",
        "status": "ok" if db_ok and storage_ok else ("degraded" if db_ok else "down"),
        "version": __version__,
        "database": "ok" if db_ok else "unreachable",
        "storage": "ok" if storage_ok else "unreachable",
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)


@router.get("/health/version", response_class=PlainTextResponse)
def health_version(db: Session = Depends(get_db)) -> PlainTextResponse:
    """One line for the update helper (v0.10.1): fm-finance:<version>:ok when the database answers."""
    try:
        db.execute(text("SELECT 1"))
        state = "ok"
    except Exception:  # noqa: BLE001
        state = "down"
    return PlainTextResponse(f"fm-finance:{__version__}:{state}")


@router.get("/settings", response_model=AppSettingsOut)
def app_settings(request: Request, db: Session = Depends(get_db), _: User = Depends(current_user)) -> AppSettingsOut:
    """The open company's settings (v0.10.0: currency, formats and approvals are each company's own)."""
    from .. import rules

    s = get_settings()
    company = getattr(request.state, "company", None)
    r = rules.of(company)
    return AppSettingsOut(
        version=__version__, currency=company.base_currency if company else s.CURRENCY,
        approval_required=r.approvals_required, date_format=r.date_format, number_format=r.number_format,
        currency_symbol=r.currency_symbol, auto_approve_confidence=r.auto_approve_confidence,
        default_approval_threshold=r.approval_threshold, max_receipt_mb=s.MAX_RECEIPT_MB,
        desktop_mode=s.DESKTOP_MODE, receipt_storage=s.receipt_backend,
        database="sqlite" if s.DATABASE_URL.startswith("sqlite") else "postgresql",
    )


@router.post("/system/shutdown", status_code=status.HTTP_202_ACCEPTED)
def shutdown(request: Request, user: User = Depends(require_roles("admin"))) -> dict[str, str]:
    """Desktop mode only: stop the local server (there is no console window to close)."""
    server = getattr(request.app.state, "server", None)
    if not get_settings().DESKTOP_MODE or server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not available")
    log.info("Shutdown requested by %s", user.email)
    server.should_exit = True
    return {"status": "stopping"}
