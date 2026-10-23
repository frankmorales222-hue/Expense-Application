from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from .. import modules
from ..database import get_db
from ..documents import readers, service
from ..models import User
from ..schemas import BillCapabilities, BillExtractOut
from ..security import require_company
from .expenses import _list_item

router = APIRouter(prefix="/api/documents", tags=["documents"],
                   dependencies=[Depends(modules.guard("smart_capture"))])


@router.get("/capabilities", response_model=BillCapabilities)
def capabilities(_: User = Depends(require_company)) -> dict:
    return service.capabilities()


@router.post("/extract", response_model=BillExtractOut)
async def extract(file: UploadFile = File(...), db: Session = Depends(get_db),
                  _: User = Depends(require_company)) -> BillExtractOut:
    data = await file.read(readers.MAX_BYTES + 1)
    name = (file.filename or "bill").replace("\\", "/").rsplit("/", 1)[-1][:255] or "bill"
    try:
        # OCR and AI calls are slow and blocking; keep them off the event loop.
        result = await run_in_threadpool(service.extract_bill, db, name, data)
    except readers.UnsupportedDocument as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    dups = result.pop("duplicates")
    out = BillExtractOut(**result, duplicates=[
        _list_item(e, e.vendor.name if e.vendor else None, e.category.name, len(e.receipts)) for e in dups])
    return out
