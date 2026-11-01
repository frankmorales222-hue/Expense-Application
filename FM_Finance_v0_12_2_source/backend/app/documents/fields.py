"""Offline field extraction from bill/receipt text using labels and patterns."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

MONEY = re.compile(r"(?<![\d.])(?:USD\s*)?\$?\s?(\d{1,3}(?:,\d{3})+|\d+)\.(\d{2})(?!\d)")
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december"
DATE_PATTERNS = [
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy"),
    # OCR often glues the time onto the date: "10/06/20268:14AM"
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})(?=\d{1,2}:\d{2})"), "mdy"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"), "mdy2"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b"), "mdy"),
    (re.compile(rf"\b({MONTHS})\.?\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I), "Mdy"),
    (re.compile(rf"\b(\d{{1,2}})\s+({MONTHS})\.?,?\s+(\d{{4}})\b", re.I), "dMy"),
]
# (pattern, score). Order matters: the first label found wins within a score band.
AMOUNT_LABELS = [
    (r"amount\s+due|balance\s+due|total\s+due|total\s+amount\s+due|please\s+pay|pay\s+this\s+amount", 0.92),
    (r"grand\s+total|invoice\s+total|total\s+charges|order\s+total|total\s+\(usd\)|total\s+usd", 0.88),
    (r"amount\s+paid|total\s+paid|payment\s+amount|charged|you\s+paid", 0.85),
    (r"(?<!sub)(?<!sub-)(?<!sub )\btotal\b(?!\s+(tax|savings|discount|items|before))", 0.78),
]
NEGATIVE_CONTEXT = re.compile(r"subtotal|sub-total|tax|discount|savings|previous\s+balance|credit|tip\b|shipping", re.I)
DUE_LABEL = re.compile(r"due\s+date|payment\s+due|due\s+by|due\s+on|pay\s+by", re.I)
ISSUE_LABEL = re.compile(r"invoice\s+date|date\s+of\s+issue|issue\s+date|bill\s+date|statement\s+date|"
                         r"order\s+date|date\s+paid|transaction\s+date|receipt\s+date|\bdate\b", re.I)
INVOICE_NO = re.compile(
    r"\b(?:invoice|inv|receipt|order|bill|statement)\s*(?:number|no\.?|num|#|id)\s*[:#.]?\s*([A-Z0-9][A-Z0-9\-_/]{2,30})"
    r"|\b(?:invoice|receipt)\s*#\s*([A-Z0-9][A-Z0-9\-_/]{2,30})",
    re.I,
)
NOT_VENDOR = re.compile(
    r"invoice|receipt|statement|bill\s+to|ship\s+to|page\s+\d|date|total|amount|thank|customer|account|"
    r"phone|tel\b|fax|email|www\.|http|@|p\.?o\.?\s+box|suite|street|\bst\b|ave\b|road|\bfl\s+\d{5}|\d{5}",
    re.I,
)
GENERIC_SENDERS = re.compile(r"no-?reply|do-?not-?reply|notifications?|billing|invoice|receipts?|support|accounts?", re.I)


@dataclass
class Field:
    value: object = None
    score: float = 0.0
    source: str = "offline"


@dataclass
class Extracted:
    vendor: Field = field(default_factory=Field)
    expense_date: Field = field(default_factory=Field)
    due_date: Field = field(default_factory=Field)
    amount: Field = field(default_factory=Field)
    invoice_number: Field = field(default_factory=Field)
    description: Field = field(default_factory=Field)
    currency: str = "USD"

    def confident(self) -> bool:
        return self.amount.score >= 0.75 and self.expense_date.score >= 0.6 and self.vendor.score >= 0.6


def _money(m: re.Match[str]) -> Decimal | None:
    try:
        value = Decimal(m.group(1).replace(",", "") + "." + m.group(2))
    except InvalidOperation:
        return None
    return value if Decimal("0") < value < Decimal("10000000") else None


def _parse_date(m: re.Match[str], kind: str) -> date | None:
    try:
        if kind == "mdy":
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if kind == "mdy2":
            return date(2000 + int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if kind == "ymd":
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if kind == "Mdy":
            return datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
        if kind == "dMy":
            return datetime.strptime(f"{m.group(2)[:3]} {m.group(1)} {m.group(3)}", "%b %d %Y").date()
    except ValueError:
        return None
    return None


def find_dates(text: str) -> list[date]:
    found = []
    for pattern, kind in DATE_PATTERNS:
        for m in pattern.finditer(text):
            d = _parse_date(m, kind)
            if d and 2000 <= d.year <= 2100:
                found.append(d)
    return found


def _lines(text: str) -> list[str]:
    return [" ".join(l.split()) for l in text.splitlines() if l.strip()]


def _labelled_amount(lines: list[str]) -> Field:
    best = Field()
    for pattern, score in AMOUNT_LABELS:
        rx = re.compile(pattern, re.I)
        for i, line in enumerate(lines):
            m_label = rx.search(line)
            if not m_label:
                continue
            after = line[m_label.end():]
            if NEGATIVE_CONTEXT.search(line[: m_label.start()] + line[m_label.start(): m_label.end()]) and score < 0.85:
                continue
            candidates = [v for v in (_money(m) for m in MONEY.finditer(after)) if v is not None]
            if not candidates and i + 1 < len(lines):
                candidates = [v for v in (_money(m) for m in MONEY.finditer(lines[i + 1])) if v is not None]
            if candidates and score > best.score:
                best = Field(candidates[-1], score)
        if best.value is not None:
            return best
    return best


def _labelled_date(lines: list[str], label: re.Pattern[str], exclude: re.Pattern[str] | None = None) -> date | None:
    for i, line in enumerate(lines):
        m = label.search(line)
        if not m or (exclude and exclude.search(line)):
            continue
        for chunk in (line[m.end():], lines[i + 1] if i + 1 < len(lines) else ""):
            ds = find_dates(chunk)
            if ds:
                return ds[0]
    return None


def _vendor_from_email(name: str | None, address: str | None) -> str | None:
    if name and not GENERIC_SENDERS.fullmatch(name.strip()) and not GENERIC_SENDERS.search(name.split()[0] if name.split() else ""):
        cleaned = re.sub(r"\s+(billing|invoices?|receipts?|payments?|team|support)$", "", name.strip(), flags=re.I)
        return cleaned or None
    if address and "@" in address:
        domain = address.split("@", 1)[1].split(".")
        core = [p for p in domain if p not in ("com", "net", "org", "io", "co", "us", "email", "mail", "billing", "e", "em")]
        if core:
            return core[-1].capitalize() if len(core[-1]) > 3 else core[-1].upper()
    return None


def _vendor_from_text(lines: list[str]) -> str | None:
    for line in lines[:12]:
        clean = line.strip(" -:|*")
        if 3 <= len(clean) <= 60 and re.search(r"[A-Za-z]{3}", clean) and not NOT_VENDOR.search(clean) \
                and not MONEY.search(clean) and not find_dates(clean):
            return clean
    return None


def extract(text: str, *, email_from_name: str | None = None, email_from_address: str | None = None,
            email_subject: str | None = None, email_date: date | None = None,
            known_vendor: str | None = None) -> Extracted:
    lines = _lines(text)
    out = Extracted()
    if re.search(r"\b(EUR|€)\b|€", text):
        out.currency = "EUR"

    out.amount = _labelled_amount(lines)
    if out.amount.value is None:
        amounts = [v for v in (_money(m) for m in MONEY.finditer(text)) if v is not None]
        if amounts:
            out.amount = Field(max(amounts), 0.45)

    due = _labelled_date(lines, DUE_LABEL)
    if due:
        out.due_date = Field(due, 0.85)
    issue = _labelled_date(lines, ISSUE_LABEL, exclude=DUE_LABEL)
    if issue:
        out.expense_date = Field(issue, 0.85)
    else:
        dates = [d for d in find_dates(text) if d != due]
        if dates:
            out.expense_date = Field(dates[0], 0.55)
        elif email_date:
            out.expense_date = Field(email_date, 0.6)

    for m in INVOICE_NO.finditer(text):
        value = (m.group(1) or m.group(2) or "").strip(".-/")
        if re.search(r"\d", value) and not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", value):
            out.invoice_number = Field(value[:100], 0.8)
            break

    if known_vendor:
        out.vendor = Field(known_vendor, 0.9)
    else:
        v = _vendor_from_email(email_from_name, email_from_address)
        if v:
            out.vendor = Field(v, 0.75)
        else:
            v = _vendor_from_text(lines)
            if v:
                # A top line that names a business ("... LLC", "... Inc") is a strong vendor signal.
                strong = re.search(r"\b(llc|inc|corp|co|company|ltd|pllc|pa|group|services)\b\.?$", v, re.I)
                out.vendor = Field(v, 0.65 if strong or v == lines[0].strip(" -:|*") else 0.5)

    if email_subject:
        out.description = Field(email_subject[:200], 0.7)
    else:
        kind = ("invoice" if re.search(r"invoice", text, re.I)
                else "statement" if re.search(r"statement|amount\s+due|due\s+date", text, re.I) else "receipt")
        who = str(out.vendor.value) if out.vendor.value else ""
        number = f" {out.invoice_number.value}" if out.invoice_number.value else ""
        out.description = Field(f"{who} {kind}{number}".strip().capitalize() if not who else f"{who} {kind}{number}", 0.5)
    return out
