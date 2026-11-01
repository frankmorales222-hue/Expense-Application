from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..models import ExpenseCategory, User
from ..schemas import CategoryIn, CategoryOut, CategoryUpdate
from ..security import require_company, require_roles

router = APIRouter(prefix="/api/categories", tags=["categories"])


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:45] or "category"


@router.get("", response_model=list[CategoryOut])
def list_categories(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_company),
) -> list[ExpenseCategory]:
    stmt = select(ExpenseCategory).order_by(ExpenseCategory.sort_order, ExpenseCategory.name)
    if not include_inactive:
        stmt = stmt.where(ExpenseCategory.is_active.is_(True))
    return list(db.scalars(stmt))


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> ExpenseCategory:
    exists = db.scalar(select(ExpenseCategory).where(func.lower(ExpenseCategory.name) == payload.name.lower()))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "A category with that name already exists")
    base = _slug(payload.name)
    code, n = base, 2
    while db.scalar(select(ExpenseCategory.id).where(ExpenseCategory.code == code)):
        code, n = f"{base}_{n}", n + 1
    sort_order = payload.sort_order
    if sort_order is None:
        sort_order = (db.scalar(select(func.max(ExpenseCategory.sort_order))) or 0) + 10
    cat = ExpenseCategory(code=code, name=payload.name, approval_threshold=payload.approval_threshold,
                          sort_order=sort_order, kind=payload.kind, tax_line=(payload.tax_line or "").strip() or None)
    db.add(cat)
    db.flush()
    audit.record(db, entity_type="category", entity_id=cat.id, action="created", user_id=user.id,
                 changes={"name": cat.name, "approval_threshold": cat.approval_threshold, "kind": cat.kind})
    db.commit()
    return cat


@router.put("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
) -> ExpenseCategory:
    cat = db.get(ExpenseCategory, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    changes: dict[str, object] = {}
    if payload.name is not None and payload.name.strip() != cat.name:
        name = payload.name.strip()
        clash = db.scalar(
            select(ExpenseCategory).where(func.lower(ExpenseCategory.name) == name.lower(), ExpenseCategory.id != cat.id)
        )
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, "A category with that name already exists")
        changes["name"] = [cat.name, name]
        cat.name = name
    if payload.clear_threshold:
        if cat.approval_threshold is not None:
            changes["approval_threshold"] = [cat.approval_threshold, None]
        cat.approval_threshold = None
    elif payload.approval_threshold is not None and payload.approval_threshold != cat.approval_threshold:
        changes["approval_threshold"] = [cat.approval_threshold, payload.approval_threshold]
        cat.approval_threshold = payload.approval_threshold
    if payload.is_active is not None and payload.is_active != cat.is_active:
        changes["is_active"] = [cat.is_active, payload.is_active]
        cat.is_active = payload.is_active
    if payload.kind is not None and payload.kind != cat.kind:
        changes["kind"] = [cat.kind, payload.kind]
        cat.kind = payload.kind
    if "tax_line" in payload.model_fields_set:
        tax_line = (payload.tax_line or "").strip() or None
        if tax_line != cat.tax_line:
            changes["tax_line"] = [cat.tax_line, tax_line]
            cat.tax_line = tax_line
    if payload.sort_order is not None and payload.sort_order != cat.sort_order:
        changes["sort_order"] = [cat.sort_order, payload.sort_order]
        cat.sort_order = payload.sort_order
    if changes:
        audit.record(db, entity_type="category", entity_id=cat.id, action="updated", user_id=user.id, changes=changes)
        db.commit()
    return cat
