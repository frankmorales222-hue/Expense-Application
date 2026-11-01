from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from .. import audit
from ..access import COMPANY_COOKIE
from ..database import get_db
from ..models import Company, User
from ..schemas import BrandingOut, CompanyIn, CompanyOut
from ..security import require_company, require_roles
from .util import current_company

router = APIRouter(prefix="/api/company", tags=["company"])
MAX_LOGO_BYTES = 1024 * 1024
MAX_LOGO_PIXELS = 4000
STORED_MAX_W, STORED_MAX_H = 1200, 400


def _version(c: Company) -> int:
    return int(c.logo_updated_at.timestamp()) if c.logo_updated_at else 0


def _out(c: Company) -> CompanyOut:
    out = CompanyOut.model_validate(c)
    out.has_logo = c.logo_updated_at is not None
    out.logo_version = _version(c)
    return out


@router.get("", response_model=CompanyOut)
def get_company(db: Session = Depends(get_db), _: User = Depends(require_company)) -> CompanyOut:
    return _out(current_company(db))


def _remembered(request: Request, db: Session) -> Company | None:
    """The company this browser last worked in (set at sign-in / switch). No sign-in needed."""
    raw = request.cookies.get(COMPANY_COOKIE)
    try:
        company = db.get(Company, uuid.UUID(raw)) if raw else None
    except ValueError:
        return None
    return company if company is not None and company.is_active else None


@router.get("/branding", response_model=BrandingOut)
def branding(request: Request, db: Session = Depends(get_db)) -> BrandingOut:
    """Public on purpose: the sign-in page shows the remembered company's name and logo,
    or the default F&M Finance mark for a browser that hasn't signed in yet."""
    c = _remembered(request, db)
    if c is None:
        return BrandingOut(name="F&M Finance", has_logo=False, logo_version=0, company_id=None)
    return BrandingOut(name=c.name, has_logo=c.logo_updated_at is not None, logo_version=_version(c),
                       company_id=c.id)


@router.put("", response_model=CompanyOut)
def update_company(payload: CompanyIn, db: Session = Depends(get_db),
                   user: User = Depends(require_roles("admin"))) -> CompanyOut:
    company = current_company(db)
    changes = {}
    for field in ("name", "legal_name", "fiscal_year_start_month", "address", "phone", "email", "website",
                  "invoice_footer"):
        if field not in payload.model_fields_set and field not in ("name",):
            continue
        new = getattr(payload, field)
        if getattr(company, field) != new:
            changes[field] = [getattr(company, field), new]
            setattr(company, field, new)
    if changes:
        audit.record(db, entity_type="company", entity_id=company.id, action="updated", user_id=user.id,
                     changes=changes)
        db.commit()
    return _out(company)


@router.get("/logo")
def get_logo(request: Request, db: Session = Depends(get_db)) -> Response:
    """Logo of the remembered company (sign-in page)."""
    company = _remembered(request, db)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No logo")
    return _logo_response(request, company)


@router.get("/{company_id}/logo")
def get_company_logo(company_id: uuid.UUID, request: Request, db: Session = Depends(get_db)) -> Response:
    """A company's logo by id (sidebar, company switcher). Logos are not confidential."""
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No logo")
    return _logo_response(request, company)


def _logo_response(request: Request, company: Company) -> Response:
    """Cached; URLs carry ?v=<logo_version> so a new upload shows at once."""
    if company.logo_updated_at is None or not company.logo_data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No logo")
    etag = f'"logo-{_version(company)}"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=company.logo_data, media_type=company.logo_content_type or "image/png", headers=headers)


def _clean_logo(data: bytes) -> bytes:
    """Validate an uploaded logo and re-encode it as PNG (drops metadata and anything that isn't pixels)."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    sig_ok = (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")
              or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))
    if not sig_ok:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Use a PNG, JPG or WEBP image.")
    Image.MAX_IMAGE_PIXELS = MAX_LOGO_PIXELS * MAX_LOGO_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        if max(img.size) > MAX_LOGO_PIXELS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The image is too large. Use one under 4000 pixels wide.")
        img = img.convert("RGBA")
        img.thumbnail((STORED_MAX_W, STORED_MAX_H))
        out = io.BytesIO()
        img.save(out, "PNG", optimize=True)
        return out.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "This image can't be read.") from None


@router.put("/logo", response_model=CompanyOut)
async def upload_logo(file: UploadFile = File(...), db: Session = Depends(get_db),
                      user: User = Depends(require_roles("admin"))) -> CompanyOut:
    data = await file.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The logo must be 1 MB or smaller.")
    png = _clean_logo(data)
    company = current_company(db)
    company.logo_data, company.logo_content_type = png, "image/png"
    company.logo_updated_at = datetime.now(timezone.utc)
    audit.record(db, entity_type="company", entity_id=company.id, action="logo_updated", user_id=user.id,
                 changes={"bytes": len(png)})
    db.commit()
    return _out(company)


@router.delete("/logo", response_model=CompanyOut)
def remove_logo(db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))) -> CompanyOut:
    company = current_company(db)
    company.logo_data = company.logo_content_type = company.logo_updated_at = None
    audit.record(db, entity_type="company", entity_id=company.id, action="logo_removed", user_id=user.id)
    db.commit()
    return _out(company)
