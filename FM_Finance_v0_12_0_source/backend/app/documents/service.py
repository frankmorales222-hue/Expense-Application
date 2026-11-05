"""Read a bill and turn it into a pre-filled expense form."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..banking.engine import KEYWORD_CATEGORIES
from ..banking.normalize import merchant_key, searchable
from ..models import Expense, ExpenseCategory, FinancialAccount, Transaction, Vendor
from . import ai, fields, ocr, readers

log = logging.getLogger(__name__)


def _known_vendor(db: Session, text: str, hint: str | None) -> Vendor | None:
    """Match an existing vendor by the hint (email sender etc.) or by its name appearing in the text."""
    vendors = list(db.scalars(select(Vendor).limit(5000)))
    if hint:
        key = merchant_key(hint)
        for v in vendors:
            if v.name.lower() == hint.lower() or (key and merchant_key(v.name) == key):
                return v
    haystack = searchable(text[:4000])
    squashed = haystack.replace(" ", "")  # OCR often drops spaces: "PANTHERCOFFEE"
    best: Vendor | None = None
    for v in vendors:
        name = searchable(v.name).strip()
        key = merchant_key(v.name)
        hit = len(name) >= 4 and f" {name} " in haystack
        # Also try the vendor's first words without spaces (e.g. "Panther Coffee Miami" -> "PANTHERCOFFEE").
        words = name.split()
        for n in range(len(words), 0, -1):
            joined = "".join(words[:n])
            if hit or len(joined) < 7:
                break
            hit = joined in squashed
        if not hit and key and len(key.replace(" ", "")) >= 7:
            hit = key.replace(" ", "") in squashed
        if hit and (best is None or len(v.name) > len(best.name)):
            best = v
    return best


def _suggest_category(db: Session, vendor: Vendor | None, vendor_name: str | None, text: str,
                      ai_category: str | None) -> tuple[ExpenseCategory | None, str]:
    cats = list(db.scalars(select(ExpenseCategory).where(ExpenseCategory.is_active.is_(True),
                                                         ExpenseCategory.kind == "expense")))
    by_id = {c.id: c for c in cats}
    if vendor is not None:
        past = Counter(db.scalars(select(Expense.category_id).where(
            Expense.vendor_id == vendor.id, Expense.is_deleted.is_(False))))
        if past:
            cat_id, n = past.most_common(1)[0]
            if cat_id in by_id:
                return by_id[cat_id], f"Used for {vendor.name} {n} time{'s' if n != 1 else ''} before"
        if vendor.default_category_id in by_id:
            return by_id[vendor.default_category_id], f"Default category for {vendor.name}"
    if ai_category:
        for c in cats:
            if c.name.lower() == ai_category.strip().lower():
                return c, "Suggested by AI reading"
    by_code = {c.code: c for c in cats}
    haystack = searchable(f"{vendor_name or ''} {text[:3000]}")
    pairs = sorted(((kw, code) for code, kws in KEYWORD_CATEGORIES.items() for kw in kws), key=lambda p: -len(p[0]))
    for kw, code in pairs:
        if len(kw) >= 4 and f" {kw} " in haystack and code in by_code:
            return by_code[code], "Matched a common merchant keyword"
    return None, ""


def _ai_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _ai_amount(value: Any) -> Decimal | None:
    try:
        amount = Decimal(str(value).replace(",", "").replace("$", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return amount if Decimal("0") < amount < Decimal("10000000") else None


def _merge_ai(out: fields.Extracted, data: dict[str, Any], prefer_ai: bool) -> None:
    conf = data.get("confidence")
    try:
        score = max(0.5, min(0.97, float(conf))) if conf is not None else 0.85
    except (TypeError, ValueError):
        score = 0.85
    candidates = {
        "vendor": (data.get("vendor_name") or None),
        "expense_date": _ai_date(data.get("invoice_date")),
        "due_date": _ai_date(data.get("due_date")),
        "amount": _ai_amount(data.get("total_amount")),
        "invoice_number": (str(data["invoice_number"]).strip()[:100] if data.get("invoice_number") else None),
        "description": (str(data["description"]).strip()[:200] if data.get("description") else None),
    }
    for name, value in candidates.items():
        if value in (None, ""):
            continue
        current: fields.Field = getattr(out, name)
        if prefer_ai or current.value is None or current.score < 0.75:
            setattr(out, name, fields.Field(value, score, "ai"))
    if isinstance(data.get("currency"), str) and len(data["currency"]) == 3:
        out.currency = data["currency"].upper()


def extract_bill(db: Session, filename: str, data: bytes) -> dict[str, Any]:
    doc = readers.read(filename, data)
    hint = fields._vendor_from_email(doc.email_from_name, doc.email_from_address)
    vendor = _known_vendor(db, doc.text, hint)
    out = fields.extract(doc.text, email_from_name=doc.email_from_name, email_from_address=doc.email_from_address,
                         email_subject=doc.email_subject, email_date=doc.email_date,
                         known_vendor=vendor.name if vendor else None)
    warnings = list(doc.notes)

    mode = ai.enabled_mode()
    used_ai = False
    ai_category: str | None = None
    if mode == "always" or (mode == "fallback" and not out.confident()):
        cat_names = [c.name for c in db.scalars(select(ExpenseCategory).where(
            ExpenseCategory.is_active.is_(True), ExpenseCategory.kind == "expense"))]
        try:
            result = ai.read_bill(text=doc.text, payload=doc.ai_payload, categories=cat_names)
            _merge_ai(out, result, prefer_ai=mode == "always")
            ai_category = result.get("category") if isinstance(result.get("category"), str) else None
            used_ai = True
        except ai.AIUnavailable as exc:
            warnings.append(f"{exc} Showing what could be read offline.")
        if used_ai and vendor is None and out.vendor.value:
            vendor = _known_vendor(db, "", str(out.vendor.value))
            if vendor:
                out.vendor = fields.Field(vendor.name, max(out.vendor.score, 0.9), out.vendor.source)

    category, category_reason = _suggest_category(db, vendor, out.vendor.value and str(out.vendor.value),
                                                  doc.text, ai_category)
    if not doc.text.strip() and not used_ai:
        warnings.append("No text could be read from this file. Fill in the fields yourself; the file will still "
                        "be attached." + ("" if ai.enabled_mode() != "off" else " Turning on AI reading helps with photos and scans."))

    duplicates = _duplicates(db, vendor, out)
    bank = _bank_match(db, out)
    return {
        "filename": filename,
        "method": "ai" if used_ai else ("ocr" if doc.used_ocr else "text"),
        "vendor_name": out.vendor.value, "expense_date": out.expense_date.value, "due_date": out.due_date.value,
        "amount": out.amount.value, "invoice_number": out.invoice_number.value,
        "description": out.description.value, "currency": out.currency,
        "category_id": category.id if category else None, "category_reason": category_reason,
        "confidence": {k: round(getattr(out, k).score, 2) for k in
                       ("vendor", "expense_date", "due_date", "amount", "invoice_number")},
        "sources": {k: getattr(out, k).source for k in ("vendor", "expense_date", "amount")},
        "confident": out.confident(),
        "known_vendor": vendor is not None,
        "warnings": warnings,
        "attachments": doc.attachments,
        "text_preview": doc.text[:1500],
        "duplicates": duplicates,
        "bank_match": bank,
    }


def _duplicates(db: Session, vendor: Vendor | None, out: fields.Extracted) -> list[Expense]:
    conds = []
    if out.invoice_number.value:
        conds.append(func.lower(Expense.invoice_number) == str(out.invoice_number.value).lower())
    if vendor is not None and out.amount.value is not None and out.expense_date.value is not None:
        d = out.expense_date.value
        conds.append((Expense.vendor_id == vendor.id) & (Expense.amount == out.amount.value)
                     & Expense.expense_date.between(d - timedelta(days=3), d + timedelta(days=3)))
    if not conds:
        return []
    return list(db.scalars(select(Expense).where(Expense.is_deleted.is_(False), or_(*conds))
                           .order_by(Expense.expense_date.desc()).limit(5)))


def _bank_match(db: Session, out: fields.Extracted) -> dict[str, Any] | None:
    if out.amount.value is None or out.expense_date.value is None:
        return None
    d = out.expense_date.value
    matches = list(db.execute(
        select(Transaction, FinancialAccount.name).join(FinancialAccount, Transaction.account_id == FinancialAccount.id)
        .where(Transaction.expense_id.is_(None), Transaction.is_transfer.is_(False),
               Transaction.review_status != "excluded", Transaction.amount == -out.amount.value,
               Transaction.txn_date.between(d - timedelta(days=5), d + timedelta(days=5))).limit(2)
    ).all())
    if len(matches) != 1:
        return None
    t, account_name = matches[0]
    return {"id": t.id, "account_name": account_name, "txn_date": t.txn_date, "description": t.description}


def capabilities() -> dict[str, Any]:
    from ..config import get_settings

    s = get_settings()
    return {"ocr": ocr.available(), "ai_mode": ai.enabled_mode(),
            "ai_requested": s.AI_EXTRACTION.strip().lower(), "ai_key_set": bool(s.ANTHROPIC_API_KEY),
            "ai_model": s.ANTHROPIC_MODEL, "formats": list(readers.SUPPORTED)}
