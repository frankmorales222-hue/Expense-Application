"""Invoice rules shared by the invoices, payments, customers and report routes."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Bill, BillLine, Company, Customer, Expense, ExpenseCategory, ExpenseLine, Invoice, InvoiceLine, Item,
    PaymentApplication, Vendor,
)
from ..schemas import BillableOut, InvoiceListItem
from .pdf import DocLine, InvoiceDoc

ZERO = Decimal("0")
FIRST_NUMBER = 1001


def paid_map(db: Session, invoice_ids) -> dict[uuid.UUID, Decimal]:
    ids = list(invoice_ids)
    out: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    if not ids:
        return out
    for inv_id, amount in db.execute(select(PaymentApplication.invoice_id, PaymentApplication.amount)
                                     .where(PaymentApplication.invoice_id.in_(ids))):
        out[inv_id] += Decimal(amount)
    return out


def paid_on(db: Session, invoice_id: uuid.UUID) -> Decimal:
    return paid_map(db, [invoice_id])[invoice_id]


def status_of(inv: Invoice, paid: Decimal, today: date | None = None) -> str:
    if inv.is_void:
        return "void"
    if paid >= Decimal(inv.total):
        return "paid"
    if inv.due_date < (today or date.today()):
        return "overdue"
    if paid > 0:
        return "partial"
    return "sent" if inv.sent_at else "not_sent"


def list_item(inv: Invoice, paid: Decimal) -> InvoiceListItem:
    total = ZERO if inv.is_void else Decimal(inv.total)
    return InvoiceListItem(
        id=inv.id, invoice_number=inv.invoice_number, customer_id=inv.customer_id,
        customer_name=inv.customer.name if inv.customer else "", invoice_date=inv.invoice_date,
        due_date=inv.due_date, total=Decimal(inv.total), paid=paid, balance=max(total - paid, ZERO),
        status=status_of(inv, paid), sent_at=inv.sent_at)


def live_invoices(db: Session):
    return select(Invoice).where(Invoice.is_deleted.is_(False))


def due_date_for(invoice_date: date, terms: str | None, db: Session | None = None) -> date:
    """Due date from the company's own payment terms (v0.10.0)."""
    from .. import rules

    r = rules.current(db) if db is not None else rules.CompanyRules()
    return r.due_date(invoice_date, terms)


def next_number(db: Session, company_id: uuid.UUID) -> str:
    """The number after the last invoice entered (like QuickBooks), skipping numbers already used.
    A number with a prefix, like INV-0042, keeps its prefix and width. v0.10.0: the company can set its own
    prefix and the number to start from (Settings > Rules > Invoices)."""
    from .. import rules

    rows = list(db.execute(select(Invoice.invoice_number).where(Invoice.company_id == company_id)
                           .order_by(Invoice.created_at.desc(), Invoice.invoice_number.desc())).scalars())
    used = set(rows)
    r = rules.current(db)
    if r.invoice_prefix or r.next_invoice_number:
        prefix = r.invoice_prefix
        mine = [n for n in rows if n and n.startswith(prefix) and n[len(prefix):].isdigit()]
        width = len(mine[0][len(prefix):]) if mine else 0
        value = max([int(mine[0][len(prefix):]) + 1] if mine else [FIRST_NUMBER])
        if r.next_invoice_number:
            value = max(value, r.next_invoice_number)
        while f"{prefix}{str(value).zfill(width)}" in used:
            value += 1
        return f"{prefix}{str(value).zfill(width)}"
    last = next((n for n in rows if re.match(r"^(.*?)(\d+)$", n or "")), None)
    if last is None:
        candidate = FIRST_NUMBER
        while str(candidate) in used:
            candidate += 1
        return str(candidate)
    m = re.match(r"^(.*?)(\d+)$", last)
    prefix, digits = m.group(1), m.group(2)
    value = int(digits) + 1
    while f"{prefix}{str(value).zfill(len(digits))}" in used:
        value += 1
    return f"{prefix}{str(value).zfill(len(digits))}"


def billed_sources(db: Session, exclude_invoice: uuid.UUID | None = None) -> tuple[set, set]:
    """Billable expense and bill lines already on a live (not void, not deleted) invoice."""
    stmt = (select(InvoiceLine.expense_line_id, InvoiceLine.bill_line_id)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(Invoice.is_deleted.is_(False), Invoice.is_void.is_(False)))
    if exclude_invoice:
        stmt = stmt.where(Invoice.id != exclude_invoice)
    exp, bill = set(), set()
    for e, b in db.execute(stmt):
        if e:
            exp.add(e)
        if b:
            bill.add(b)
    return exp, bill


def unbilled(db: Session, customer_id: uuid.UUID, exclude_invoice: uuid.UUID | None = None) -> list[BillableOut]:
    used_exp, used_bill = billed_sources(db, exclude_invoice)
    cats = {c.id: c.name for c in db.scalars(select(ExpenseCategory))}
    out: list[BillableOut] = []
    rows = db.execute(
        select(ExpenseLine, Expense).join(Expense, Expense.id == ExpenseLine.expense_id)
        .where(ExpenseLine.billable.is_(True), ExpenseLine.customer_id == customer_id,
               Expense.is_deleted.is_(False), Expense.status.in_(("approved", "paid")))
        .order_by(Expense.expense_date)).all()
    for ln, e in rows:
        if ln.id in used_exp:
            continue
        out.append(BillableOut(source="expense", line_id=ln.id, record_id=e.id, date=e.expense_date,
                               vendor_name=e.vendor.name if getattr(e, "vendor", None) else None,
                               description=ln.description or e.description, category_name=cats.get(ln.category_id, ""),
                               amount=ln.amount))
    rows = db.execute(
        select(BillLine, Bill).join(Bill, Bill.id == BillLine.bill_id)
        .where(BillLine.billable.is_(True), BillLine.customer_id == customer_id, Bill.is_deleted.is_(False))
        .order_by(Bill.bill_date)).all()
    for ln, b in rows:
        if ln.id in used_bill:
            continue
        out.append(BillableOut(source="bill", line_id=ln.id, record_id=b.id, date=b.bill_date,
                               vendor_name=b.vendor.name if b.vendor else None,
                               description=ln.description or b.memo or (f"Bill {b.bill_number}" if b.bill_number
                                                                        else "Bill"),
                               category_name=cats.get(ln.category_id, ""), amount=ln.amount))
    out.sort(key=lambda r: r.date)
    return out


def build_doc(db: Session, inv: Invoice, company: Company) -> InvoiceDoc:
    paid = paid_on(db, inv.id)
    items = {i.id: i.name for i in db.scalars(select(Item).where(
        Item.id.in_({ln.item_id for ln in inv.lines if ln.item_id})))} if any(ln.item_id for ln in inv.lines) else {}
    logo = None
    if company.logo_updated_at is not None:
        logo = db.scalar(select(Company.logo_data).where(Company.id == company.id))
    cust: Customer = inv.customer
    status = status_of(inv, paid)
    from .. import rules

    r = rules.of(company)
    fmt = rules.Formatter(r, company.base_currency, ascii_only=True)
    return InvoiceDoc(
        company_name=company.name, company_legal_name=company.legal_name, company_address=company.address,
        company_phone=company.phone, company_email=company.email, company_website=company.website, logo_png=logo,
        invoice_number=inv.invoice_number, invoice_date=inv.invoice_date, due_date=inv.due_date, terms=inv.terms,
        customer_name=cust.name if cust else "", customer_address=cust.billing_address if cust else None,
        customer_email=inv.bill_email or (cust.email if cust else None),
        lines=[DocLine(description=ln.description or items.get(ln.item_id, "") or "", quantity=Decimal(ln.quantity),
                       rate=Decimal(ln.rate), amount=Decimal(ln.amount), item=items.get(ln.item_id),
                       service_date=ln.service_date) for ln in inv.lines],
        total=Decimal(inv.total), paid=paid, message=inv.message, footer=company.invoice_footer,
        status=status if status in ("paid", "void") else "",
        fmt=fmt, labels=r.pdf_labels, accent=r.pdf_accent, terms_label=r.term_name(inv.terms),
        extra_facts=rules.printable(r, "invoice", inv.custom, fmt),
        customer_extra=rules.printable(r, "customer", cust.custom if cust else None, fmt))


def vendor_name(db: Session, vendor_id) -> str | None:
    v = db.get(Vendor, vendor_id) if vendor_id else None
    return v.name if v else None
