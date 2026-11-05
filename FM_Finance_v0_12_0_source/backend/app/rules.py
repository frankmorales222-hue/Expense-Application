"""Company rules (v0.10.0): everything a company decides for itself, with sensible defaults.

Stored as JSON on companies.rules (only what the company changed). Defaults for things the installation
used to fix in .env (approvals and their threshold) come from .env, so existing companies keep working
exactly as before until they change something. What stays fixed on purpose: double-entry, the system
accounts, the audit history, the closing-date lock and company separation.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .config import get_settings

# ---------------------------------------------------------------- building blocks
CODE = r"^[a-z0-9_]{1,20}$"


class Term(BaseModel):
    """A payment term. kind days: due N days after the date. end_of_month: end of that month, plus N days.
    day_of_next_month: on a given day of the following month (for example the 10th)."""

    code: str = Field(pattern=CODE)
    name: str = Field(min_length=1, max_length=40)
    kind: Literal["days", "end_of_month", "day_of_next_month"] = "days"
    days: int = Field(default=0, ge=0, le=365)
    day: int | None = Field(default=None, ge=1, le=31)
    active: bool = True

    @model_validator(mode="after")
    def _day(self) -> "Term":
        if self.kind == "day_of_next_month" and not self.day:
            raise ValueError(f"Choose the day of the month for {self.name}")
        return self

    def due(self, start: date) -> date:
        if self.kind == "end_of_month":
            last = calendar.monthrange(start.year, start.month)[1]
            return date(start.year, start.month, last) + timedelta(days=self.days)
        if self.kind == "day_of_next_month":
            y, m = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
            return date(y, m, min(self.day or 1, calendar.monthrange(y, m)[1]))
        return start + timedelta(days=self.days)


class Choice(BaseModel):
    code: str = Field(pattern=CODE)
    label: str = Field(min_length=1, max_length=60)
    active: bool = True


class CustomField(BaseModel):
    """A field the company adds to a kind of record. Values are kept on the record (custom JSON)."""

    code: str = Field(pattern=CODE)
    label: str = Field(min_length=1, max_length=60)
    entity: Literal["customer", "item", "invoice", "bill", "expense"]
    type: Literal["text", "number", "date", "choice", "yes_no"] = "text"
    options: list[str] = Field(default_factory=list, max_length=50)  # for "choice"
    required: bool = False
    print_on_invoice: bool = False  # invoice fields: printed under the invoice facts; customer fields: under Bill to
    active: bool = True

    @model_validator(mode="after")
    def _options(self) -> "CustomField":
        self.options = [o.strip() for o in self.options if o and o.strip()]
        if self.type == "choice" and not self.options:
            raise ValueError(f"Add the choices for {self.label}")
        return self


DEFAULT_TERMS = [
    Term(code="due_on_receipt", name="Due on receipt", days=0),
    Term(code="net_15", name="Net 15", days=15),
    Term(code="net_30", name="Net 30", days=30),
    Term(code="net_45", name="Net 45", days=45),
    Term(code="net_60", name="Net 60", days=60),
]
DEFAULT_EXPENSE_METHODS = [
    Choice(code="business_card", label="Business card"), Choice(code="business_bank", label="Business bank account"),
    Choice(code="personal_card", label="Personal card"), Choice(code="cash", label="Cash"),
    Choice(code="other", label="Other"),
]
DEFAULT_RECEIVED_METHODS = [
    Choice(code="ach", label="ACH / bank transfer"), Choice(code="check", label="Check"), Choice(code="card", label="Card"),
    Choice(code="cash", label="Cash"), Choice(code="wire", label="Wire"), Choice(code="other", label="Other"),
]
DEFAULT_LABELS = {
    "invoice_title": "INVOICE", "invoice_no": "Invoice no.", "invoice_date": "Invoice date", "due_date": "Due date",
    "terms": "Terms", "bill_to": "BILL TO", "balance_due": "Balance due", "total": "Total",
    "payments": "Payments received", "message": "Message", "payment_instructions": "Payment instructions",
    "col_date": "Date", "col_item": "Product/service", "col_description": "Description", "col_qty": "Qty",
    "col_rate": "Rate", "col_amount": "Amount", "paid_stamp": "PAID", "void_stamp": "VOID", "page": "Page",
}
DEFAULT_EMAIL_SUBJECT = "Invoice {invoice_number} from {company}"
DEFAULT_EMAIL_BODY = (
    "Dear {customer},\n\n"
    "Here's invoice {invoice_number} for {total}.\n"
    "The balance due is {balance}, due {due_date}.\n\n"
    "The invoice is attached as a PDF.\n\n"
    "{payment_instructions}\n\n"
    "Thank you for your business!\n{company}\n{phone}"
)
EMAIL_PLACEHOLDERS = ("customer", "invoice_number", "total", "balance", "due_date", "invoice_date", "terms",
                      "company", "phone", "email", "website", "payment_instructions")

DATE_FORMATS = {"MM/DD/YYYY": "%m/%d/%Y", "DD/MM/YYYY": "%d/%m/%Y", "YYYY-MM-DD": "%Y-%m-%d", "DD.MM.YYYY": "%d.%m.%Y"}
NUMBER_FORMATS = {"1,234.56": (",", "."), "1.234,56": (".", ","), "1 234,56": (" ", ","), "1'234.56": ("'", ".")}
SYMBOLS = {"USD": "$", "CAD": "CA$", "AUD": "A$", "MXN": "MX$", "EUR": "€", "GBP": "£", "PEN": "S/", "COP": "COL$",
           "DOP": "RD$", "CLP": "CLP$", "ARS": "AR$", "BRL": "R$", "JPY": "¥", "INR": "₹", "CHF": "CHF ", "GTQ": "Q",
           "CRC": "₡", "PAB": "B/.", "HNL": "L", "NIO": "C$", "PHP": "₱", "JMD": "J$", "TTD": "TT$", "BSD": "B$"}
ZERO_DECIMAL = {"JPY", "CLP", "KRW", "VND", "ISK"}


class CompanyRules(BaseModel):
    # Approvals (were one switch in .env for the whole installation)
    approvals_required: bool = False
    approval_threshold: Decimal = Field(default=Decimal("500.00"), ge=0, max_digits=12, decimal_places=2)
    # Money and dates
    date_format: Literal["MM/DD/YYYY", "DD/MM/YYYY", "YYYY-MM-DD", "DD.MM.YYYY"] = "MM/DD/YYYY"
    number_format: Literal["1,234.56", "1.234,56", "1 234,56", "1'234.56"] = "1,234.56"
    currency_symbol: str | None = Field(default=None, max_length=6)  # None: the usual symbol for the currency
    # Lists the company keeps
    terms: list[Term] = Field(default_factory=lambda: [t.model_copy() for t in DEFAULT_TERMS], min_length=1, max_length=40)
    default_terms: str | None = None  # for invoices when the customer has none
    bill_default_terms: str | None = None
    expense_methods: list[Choice] = Field(default_factory=lambda: [c.model_copy() for c in DEFAULT_EXPENSE_METHODS],
                                          min_length=1, max_length=30)
    received_methods: list[Choice] = Field(default_factory=lambda: [c.model_copy() for c in DEFAULT_RECEIVED_METHODS],
                                           min_length=1, max_length=30)
    custom_fields: list[CustomField] = Field(default_factory=list, max_length=60)
    # Invoices
    invoice_prefix: str = Field(default="", max_length=10)
    next_invoice_number: int | None = Field(default=None, ge=1, le=99_999_999)  # None: after the last one
    pdf_accent: str = Field(default="#1F4E8C", pattern=r"^#[0-9A-Fa-f]{6}$")
    pdf_labels: dict[str, str] = Field(default_factory=dict)
    email_subject: str = Field(default=DEFAULT_EMAIL_SUBJECT, min_length=1, max_length=200)
    email_body: str = Field(default=DEFAULT_EMAIL_BODY, min_length=1, max_length=5000)
    # Banking and dashboard
    auto_approve_confidence: int = Field(default=90, ge=50, le=100)
    forecast_days: Literal[14, 30, 60, 90] = 30
    coming_up_days: Literal[7, 14, 30, 60] = 14

    @field_validator("pdf_labels")
    @classmethod
    def _labels(cls, v: dict[str, str]) -> dict[str, str]:
        out = {}
        for k, text in (v or {}).items():
            if k in DEFAULT_LABELS and isinstance(text, str) and text.strip():
                out[k] = text.strip()[:40]
        return out

    @model_validator(mode="after")
    def _consistent(self) -> "CompanyRules":
        for name, items in (("payment terms", self.terms), ("payment methods", self.expense_methods),
                            ("payment methods received", self.received_methods), ("custom fields", self.custom_fields)):
            codes = [i.code for i in items]
            dup = next((c for c in codes if codes.count(c) > 1), None)
            if dup:
                raise ValueError(f"Two {name} use the same code: {dup}")
        active_terms = {t.code for t in self.terms if t.active}
        if not active_terms:
            raise ValueError("Keep at least one payment term active")
        for attr in ("default_terms", "bill_default_terms"):
            if getattr(self, attr) and getattr(self, attr) not in active_terms:
                setattr(self, attr, None)
        if not any(m.active for m in self.expense_methods) or not any(m.active for m in self.received_methods):
            raise ValueError("Keep at least one payment method active in each list")
        return self

    # ---------- lookups
    def term(self, code: str | None) -> Term | None:
        return next((t for t in self.terms if t.code == code), None) if code else None

    def due_date(self, start: date, code: str | None) -> date:
        t = self.term(code)
        return t.due(start) if t else start

    def term_name(self, code: str | None) -> str | None:
        t = self.term(code)
        return t.name if t else (code.replace("_", " ").capitalize() if code else None)

    def check_term(self, code: str | None, current: str | None = None) -> None:
        """Raise ValueError unless the term is one of the company's active terms (or the one already saved)."""
        if not code or code == current:
            return
        t = self.term(code)
        if t is None or not t.active:
            raise ValueError(f"Unknown payment term: {code}. Add it in Settings > Rules > Payment terms.")

    def check_method(self, kind: Literal["expense", "received"], code: str | None, current: str | None = None) -> None:
        if not code or code == current:
            return
        items = self.expense_methods if kind == "expense" else self.received_methods
        if not any(m.code == code and m.active for m in items):
            raise ValueError(f"Unknown payment method: {code}. Add it in Settings > Rules > Payment methods.")

    def method_label(self, kind: Literal["expense", "received"], code: str | None) -> str | None:
        items = self.expense_methods if kind == "expense" else self.received_methods
        return next((m.label for m in items if m.code == code), code) if code else None

    def label(self, key: str) -> str:
        return self.pdf_labels.get(key) or DEFAULT_LABELS[key]

    def fields_for(self, entity: str, active_only: bool = True) -> list[CustomField]:
        return [f for f in self.custom_fields if f.entity == entity and (f.active or not active_only)]


# ---------------------------------------------------------------- reading and saving
def defaults() -> dict:
    s = get_settings()
    return {"approvals_required": s.APPROVAL_REQUIRED, "approval_threshold": s.DEFAULT_APPROVAL_THRESHOLD}


def of(company) -> CompanyRules:
    """The company's rules: what it saved on top of the defaults. A saved value that no longer validates
    (should not happen) falls back to the defaults rather than stopping the app."""
    data = dict(company.rules or {}) if company is not None else {}
    try:
        return CompanyRules.model_validate({**defaults(), **data})
    except Exception:  # noqa: BLE001
        return CompanyRules.model_validate(defaults())


def current(db) -> CompanyRules:
    from .models import Company
    from .tenancy import NO_COMPANY, company_of

    cid = company_of(db)
    company = db.get(Company, cid) if cid and cid != NO_COMPANY else None
    return of(company)


def save(company, rules: CompanyRules) -> None:
    """Store only what differs from the defaults, so a later default change still reaches the company."""
    base = CompanyRules.model_validate(defaults()).model_dump(mode="json")
    mine = rules.model_dump(mode="json")
    company.rules = {k: v for k, v in mine.items() if base.get(k) != v}


# ---------------------------------------------------------------- formatting (PDF, email)
class Formatter:
    def __init__(self, rules: CompanyRules, currency: str, ascii_only: bool = False):
        self.rules, self.currency = rules, (currency or "USD").upper()
        sym = rules.currency_symbol if rules.currency_symbol is not None else SYMBOLS.get(self.currency,
                                                                                            self.currency + " ")
        if ascii_only:
            try:
                sym.encode("latin-1")
            except UnicodeEncodeError:
                sym = self.currency + " "
        self.symbol = sym
        self.places = 0 if self.currency in ZERO_DECIMAL else 2

    def number(self, v, places: int | None = None) -> str:
        places = self.places if places is None else places
        q = Decimal(str(v or 0)).quantize(Decimal(1) / (Decimal(10) ** places) if places else Decimal(1))
        thousands, decimal_sep = NUMBER_FORMATS[self.rules.number_format]
        text = f"{abs(q):,.{places}f}"
        whole, _, frac = text.partition(".")
        whole = whole.replace(",", thousands)
        return ("-" if q < 0 else "") + (whole + (decimal_sep + frac if places else ""))

    def money(self, v) -> str:
        n = self.number(v)
        neg = n.startswith("-")
        return ("-" if neg else "") + self.symbol + n.lstrip("-")

    def date(self, d: date | None) -> str:
        return d.strftime(DATE_FORMATS[self.rules.date_format]) if d else ""


def render_template(template: str, values: dict[str, str]) -> str:
    """Fill {placeholders}; unknown ones are left as typed. Empty lines from empty values are tidied."""
    def sub(m: re.Match) -> str:
        key = m.group(1)
        return values.get(key, m.group(0)) if key in values else m.group(0)

    text = re.sub(r"\{([a-z_]+)\}", sub, template)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------- custom field values
def clean_custom(rules: CompanyRules, entity: str, values: dict | None, before: dict | None = None) -> dict:
    """Validate the custom values sent for a record. Keeps values of fields that were turned off."""
    values = dict(values or {})
    out = {k: v for k, v in (before or {}).items()}
    defs = {f.code: f for f in rules.fields_for(entity, active_only=False)}
    for code, raw in values.items():
        f = defs.get(code)
        if f is None:
            continue
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            out.pop(code, None)
            continue
        if f.type == "number":
            try:
                raw = float(Decimal(str(raw).replace(",", "")))
            except Exception:  # noqa: BLE001
                raise ValueError(f"{f.label} must be a number") from None
        elif f.type == "date":
            try:
                raw = date.fromisoformat(str(raw)[:10]).isoformat()
            except ValueError:
                raise ValueError(f"{f.label} must be a date") from None
        elif f.type == "yes_no":
            raw = bool(raw) if not isinstance(raw, str) else raw.strip().lower() in ("true", "yes", "1", "on")
        elif f.type == "choice":
            raw = str(raw).strip()
            if raw not in f.options:
                raise ValueError(f"{f.label}: choose one of {', '.join(f.options)}")
        else:
            raw = str(raw).strip()[:500]
        out[code] = raw
    for f in rules.fields_for(entity):
        if f.required and out.get(f.code) in (None, ""):
            raise ValueError(f"{f.label} is required")
    return out


def printable(rules: CompanyRules, entity: str, values: dict | None, fmt: Formatter) -> list[tuple[str, str]]:
    out = []
    for f in rules.fields_for(entity):
        if not f.print_on_invoice:
            continue
        v = (values or {}).get(f.code)
        if v in (None, ""):
            continue
        if f.type == "date":
            v = fmt.date(date.fromisoformat(v))
        elif f.type == "yes_no":
            v = "Yes" if v else "No"
        elif f.type == "number":
            dec = NUMBER_FORMATS[fmt.rules.number_format][1]
            v = fmt.number(v, 2)
            if v.endswith(dec + "00"):
                v = v[:-3]
        out.append((f.label, str(v)))
    return out
