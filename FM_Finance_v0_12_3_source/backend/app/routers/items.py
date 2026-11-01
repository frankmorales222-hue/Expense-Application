"""Products and services (what you sell)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from .. import modules
from ..database import get_db
from ..models import ExpenseCategory, Item, User
from ..schemas import ItemIn, ItemOut
from ..security import require_roles
from . import ruleutil

router = APIRouter(prefix="/api/items", tags=["items"],
                   dependencies=[Depends(modules.guard("invoicing"))])
ROLES = ("admin", "approver")


def _out(db: Session, item: Item) -> ItemOut:
    cat = db.get(ExpenseCategory, item.category_id)
    out = ItemOut.model_validate(item)
    out.category_name = cat.name if cat else ""
    return out


def _check(db: Session, payload: ItemIn, item: Item | None = None) -> None:
    cat = db.get(ExpenseCategory, payload.category_id)
    if cat is None or cat.kind != "income" or (not cat.is_active and (item is None or item.category_id != cat.id)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose an active income category")
    stmt = select(Item.id).where(func.lower(Item.name) == payload.name.lower())
    if item is not None:
        stmt = stmt.where(Item.id != item.id)
    if db.scalar(stmt):
        raise HTTPException(status.HTTP_409_CONFLICT, "A product or service with that name already exists")


@router.get("", response_model=list[ItemOut])
def list_items(include_inactive: bool = False, db: Session = Depends(get_db),
               _: User = Depends(require_roles(*ROLES))) -> list[ItemOut]:
    stmt = select(Item).order_by(Item.name)
    if not include_inactive:
        stmt = stmt.where(Item.is_active.is_(True))
    return [_out(db, i) for i in db.scalars(stmt)]


@router.post("", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
def create_item(payload: ItemIn, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*ROLES))) -> ItemOut:
    _check(db, payload)
    data = payload.model_dump()
    data["custom"] = ruleutil.custom(db, "item", payload.custom)
    item = Item(id=uuid.uuid4(), **data)
    db.add(item)
    db.flush()
    audit.record(db, entity_type="item", entity_id=item.id, action="created", user_id=user.id,
                 changes={"name": item.name, "rate": item.rate})
    db.commit()
    return _out(db, item)


@router.put("/{item_id}", response_model=ItemOut)
def update_item(item_id: uuid.UUID, payload: ItemIn, db: Session = Depends(get_db),
                user: User = Depends(require_roles(*ROLES))) -> ItemOut:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product or service not found")
    _check(db, payload, item)
    changes = {}
    data = payload.model_dump()
    data["custom"] = (ruleutil.custom(db, "item", payload.custom, before=item.custom) if payload.custom is not None
                      else item.custom)
    for field, value in data.items():
        if getattr(item, field) != value:
            changes[field] = [getattr(item, field), value]
            setattr(item, field, value)
    if changes:
        audit.record(db, entity_type="item", entity_id=item.id, action="updated", user_id=user.id, changes=changes)
        db.commit()
    return _out(db, item)
