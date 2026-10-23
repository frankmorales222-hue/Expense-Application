"""Audit trail helper. Callers commit in the same transaction as the change itself."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def record(
    db: Session,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    user_id: uuid.UUID | None,
    changes: dict[str, Any] | None = None,
    account_level: bool = False,
) -> None:
    """account_level=True for events that belong to no company (passwords, resellers)."""
    entry = AuditLog(entity_type=entity_type, entity_id=entity_id, action=action, user_id=user_id,
                     changes=_jsonable(changes) if changes else None)
    if not account_level:
        db.add(entry)
        return
    from .tenancy import NO_COMPANY, acting_as

    with acting_as(db, NO_COMPANY):
        db.add(entry)
