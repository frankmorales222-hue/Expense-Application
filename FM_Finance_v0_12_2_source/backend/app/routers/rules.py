"""Company rules (v0.10.0): GET for every member (forms need the terms, methods and custom fields);
changing them is for the owner."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from .. import audit, rules
from ..database import get_db
from ..models import User
from ..security import require_company, require_roles
from .util import current_company

router = APIRouter(prefix="/api/rules", tags=["rules"])


class RulesOut(BaseModel):
    currency: str
    rules: rules.CompanyRules
    defaults: rules.CompanyRules
    labels_default: dict[str, str]
    email_placeholders: list[str]
    currency_symbols: dict[str, str]


class RulesIn(BaseModel):
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    rules: dict


def _out(company) -> RulesOut:
    return RulesOut(currency=company.base_currency, rules=rules.of(company),
                    defaults=rules.CompanyRules.model_validate(rules.defaults()),
                    labels_default=rules.DEFAULT_LABELS, email_placeholders=list(rules.EMAIL_PLACEHOLDERS),
                    currency_symbols=rules.SYMBOLS)


@router.get("", response_model=RulesOut)
def get_rules(db: Session = Depends(get_db), _: User = Depends(require_company)) -> RulesOut:
    return _out(current_company(db))


@router.put("", response_model=RulesOut)
def put_rules(payload: RulesIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))) -> RulesOut:
    company = current_company(db)
    before = rules.of(company)
    merged = {**before.model_dump(mode="json"), **payload.rules}
    try:
        new = rules.CompanyRules.model_validate(merged)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = " > ".join(str(p) for p in first.get("loc", ()) if not isinstance(p, int))
        msg = str(first.get("msg", "Invalid value")).removeprefix("Value error, ")
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{msg}" + (f" ({where})" if where else "")) from None
    # Codes in use can't disappear: turning them off (active: false) keeps old records readable.
    for name, old, now in (("payment term", before.terms, new.terms), ("payment method", before.expense_methods,
                           new.expense_methods), ("payment method", before.received_methods, new.received_methods),
                           ("custom field", before.custom_fields, new.custom_fields)):
        gone = {o.code for o in old} - {n.code for n in now}
        if gone:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"The {name} {sorted(gone)[0]} can't be deleted because records may use it. "
                                "Turn it off instead.")
    changed = sorted(k for k in merged if before.model_dump(mode="json").get(k) != new.model_dump(mode="json").get(k))
    rules.save(company, new)
    if payload.currency and payload.currency.upper() != company.base_currency:
        changed.append("currency")
        company.base_currency = payload.currency.upper()
    if changed:
        audit.record(db, entity_type="company", entity_id=company.id, action="rules_changed", user_id=user.id,
                     changes={"changed": changed})
    db.commit()
    return _out(company)
