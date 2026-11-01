"""Invoices (Accounts Receivable): create, edit, void, PDF, email."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import audit, rules
from .. import modules
from ..database import get_db
from ..invoicing import mailer, outbox, service
from ..invoicing.pdf import render_invoice
from ..invoicing.secretbox import SecretUnavailable
from ..models import (
    Bill, BillLine, Customer, CustomerPayment, EmailSettings, Expense, ExpenseCategory, ExpenseLine, FinancialAccount,
    Invoice, InvoiceEmail, InvoiceLine, Item, PaymentApplication, User,
)
from ..schemas import (
    BillableOut, EmailDraftOut, InvoiceDetail, InvoiceEmailOut, InvoiceIn, InvoiceLineOut, InvoicePage,
    InvoicePaymentRef, SendInvoiceIn,
)
from ..security import require_roles
from . import ruleutil
from .util import current_company, like_pattern

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/invoices", tags=["invoices"],
                   dependencies=[Depends(modules.guard("invoicing"))])
ROLES = ("admin", "approver")
ZERO = Decimal("0")
CENT = Decimal("0.01")
MAX_TOTAL = Decimal("10000000000")


def _load(db: Session, invoice_id: uuid.UUID) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if inv is None or inv.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return inv


def _detail(db: Session, inv: Invoice) -> InvoiceDetail:
    paid = service.paid_on(db, inv.id)
    cats = {c.id: c.name for c in db.scalars(select(ExpenseCategory))}
    item_ids = {ln.item_id for ln in inv.lines if ln.item_id}
    items = {i.id: i.name for i in db.scalars(select(Item).where(Item.id.in_(item_ids)))} if item_ids else {}
    accounts = {a.id: a.name for a in db.scalars(select(FinancialAccount))}
    payments = []
    for app_, pay in db.execute(select(PaymentApplication, CustomerPayment)
                                .join(CustomerPayment, CustomerPayment.id == PaymentApplication.payment_id)
                                .where(PaymentApplication.invoice_id == inv.id)
                                .order_by(CustomerPayment.payment_date)).all():
        payments.append(InvoicePaymentRef(
            payment_id=pay.id, payment_date=pay.payment_date, amount=app_.amount, payment_total=pay.amount,
            account_name=accounts.get(pay.account_id, "?"), method=pay.method, reference=pay.reference,
            transaction_id=pay.transaction_id))
    emails = list(db.scalars(select(InvoiceEmail).where(InvoiceEmail.invoice_id == inv.id)
                             .order_by(InvoiceEmail.sent_at.desc())))
    base = service.list_item(inv, paid).model_dump()
    cust = inv.customer
    return InvoiceDetail(
        **base, terms=inv.terms, bill_email=inv.bill_email, customer_email=cust.email if cust else None,
        customer_cc=cust.cc_emails if cust else None, message=inv.message, memo=inv.memo, voided_at=inv.voided_at,
        custom=inv.custom,
        lines=[InvoiceLineOut(id=ln.id, service_date=ln.service_date, item_id=ln.item_id, item_name=items.get(ln.item_id),
                              description=ln.description, quantity=ln.quantity, rate=ln.rate, amount=ln.amount,
                              category_id=ln.category_id,
                              category_name=cats.get(ln.category_id) if ln.category_id else "Billable Expense Income",
                              expense_line_id=ln.expense_line_id, bill_line_id=ln.bill_line_id) for ln in inv.lines],
        payments=payments, emails=[InvoiceEmailOut.model_validate(e) for e in emails])


# ---------------------------------------------------------------- list
@router.get("", response_model=InvoicePage)
def list_invoices(
    show: Literal["unpaid", "paid", "all"] = "unpaid",
    customer_id: uuid.UUID | None = None,
    search: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db), _: User = Depends(require_roles(*ROLES, viewer_can_read=True)),
) -> InvoicePage:
    stmt = service.live_invoices(db).join(Customer, Customer.id == Invoice.customer_id)
    if customer_id:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if search and search.strip():
        pattern = like_pattern(search.strip())
        stmt = stmt.where(or_(Customer.name.ilike(pattern, escape="\\"),
                              Invoice.invoice_number.ilike(pattern, escape="\\"),
                              Invoice.memo.ilike(pattern, escape="\\")))
    invoices = list(db.scalars(stmt.order_by(Invoice.invoice_date.desc(), Invoice.created_at.desc())).unique())
    paid = service.paid_map(db, [i.id for i in invoices])
    items = [service.list_item(i, paid[i.id]) for i in invoices]
    unpaid = [i for i in items if i.status not in ("paid", "void")]
    if show == "unpaid":
        items = sorted(unpaid, key=lambda i: i.due_date)
    elif show == "paid":
        items = [i for i in items if i.status == "paid"]
    since = date.today() - timedelta(days=30)
    recent = sum((Decimal(a.amount) for a, p in db.execute(
        select(PaymentApplication, CustomerPayment).join(CustomerPayment, CustomerPayment.id == PaymentApplication.payment_id)
        .where(CustomerPayment.payment_date >= since)).all()), ZERO)
    overdue = [i for i in unpaid if i.status == "overdue"]
    return InvoicePage(items=items, total_open=sum((i.balance for i in unpaid), ZERO),
                       total_overdue=sum((i.balance for i in overdue), ZERO), paid_last_30=recent,
                       count_open=len(unpaid), count_overdue=len(overdue))


@router.get("/next-number")
def next_number(db: Session = Depends(get_db), _: User = Depends(require_roles(*ROLES))) -> dict:
    return {"invoice_number": service.next_number(db, current_company(db).id)}


@router.get("/billable", response_model=list[BillableOut])
def billable(customer_id: uuid.UUID, invoice_id: uuid.UUID | None = None, db: Session = Depends(get_db),
             _: User = Depends(require_roles(*ROLES))) -> list[BillableOut]:
    if db.get(Customer, customer_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return service.unbilled(db, customer_id, exclude_invoice=invoice_id)


# ---------------------------------------------------------------- create / edit
def _apply(db: Session, inv: Invoice, payload: InvoiceIn, company_id: uuid.UUID) -> None:
    customer = db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Customer not found")
    if not customer.is_active and inv.customer_id != customer.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That customer is inactive")
    paid = service.paid_on(db, inv.id) if inv.id else ZERO
    if paid and inv.customer_id != customer.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "This invoice has payments, so its customer can't change")

    number = payload.invoice_number or inv.invoice_number or service.next_number(db, company_id)
    clash = db.scalar(select(Invoice.id).where(Invoice.company_id == company_id, Invoice.invoice_number == number,
                                               Invoice.id != (inv.id or uuid.UUID(int=0))))
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Invoice number {number} is already used")

    used_exp, used_bill = service.billed_sources(db, exclude_invoice=inv.id)
    current_cats = {ln.category_id for ln in inv.lines if ln.category_id}
    lines: list[InvoiceLine] = []
    total = ZERO
    for i, ln in enumerate(payload.lines, start=1):
        category_id = ln.category_id
        item = None
        if ln.item_id:
            item = db.get(Item, ln.item_id)
            if item is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Line {i}: product or service not found")
            category_id = category_id or item.category_id
        if ln.expense_line_id and ln.bill_line_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Line {i}: one billable expense per line")
        if ln.expense_line_id:
            src = db.get(ExpenseLine, ln.expense_line_id)
            exp = db.get(Expense, src.expense_id) if src else None
            if (src is None or exp is None or exp.is_deleted or not src.billable or src.customer_id != customer.id
                    or exp.status not in ("approved", "paid")):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    f"Line {i}: that billable expense isn't available for {customer.name}")
            if src.id in used_exp:
                raise HTTPException(status.HTTP_409_CONFLICT, f"Line {i}: that expense is already on another invoice")
        if ln.bill_line_id:
            src = db.get(BillLine, ln.bill_line_id)
            bill = db.get(Bill, src.bill_id) if src else None
            if src is None or bill is None or bill.is_deleted or not src.billable or src.customer_id != customer.id:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    f"Line {i}: that billable expense isn't available for {customer.name}")
            if src.id in used_bill:
                raise HTTPException(status.HTTP_409_CONFLICT, f"Line {i}: that expense is already on another invoice")
        if category_id:
            cat = db.get(ExpenseCategory, category_id)
            if cat is None or cat.kind != "income" or (not cat.is_active and cat.id not in current_cats):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    f"Line {i}: choose an active income category")
        elif not (ln.expense_line_id or ln.bill_line_id):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Line {i}: choose a product or service (or an income category)")
        amount = (ln.quantity * ln.rate).quantize(CENT, rounding=ROUND_HALF_UP)
        if amount <= 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Line {i}: the amount must be more than zero")
        total += amount
        lines.append(InvoiceLine(id=uuid.uuid4(), line_no=i - 1, service_date=ln.service_date,
                                 item_id=item.id if item else None,
                                 description=ln.description or (item.description if item else None),
                                 quantity=ln.quantity, rate=ln.rate, amount=amount, category_id=category_id,
                                 expense_line_id=ln.expense_line_id, bill_line_id=ln.bill_line_id))
    if total >= MAX_TOTAL:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The total is too large")
    if paid and total < paid:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"The total can't be less than the {paid:,.2f} already received")
    r = rules.current(db)
    terms = payload.terms
    if terms is None and payload.due_date is None:
        # Nothing chosen: the customer's usual terms, else the company's (skipping one that was turned off).
        usual = r.term(customer.default_terms)
        terms = customer.default_terms if usual is not None and usual.active else r.default_terms
    else:
        ruleutil.term(db, terms, current=inv.terms, r=r)
    due = payload.due_date or r.due_date(payload.invoice_date, terms)
    if due < payload.invoice_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The due date can't be before the invoice date")

    inv.customer_id = customer.id
    inv.customer = customer
    inv.invoice_number = number
    inv.invoice_date = payload.invoice_date
    inv.terms = terms
    inv.due_date = due
    inv.bill_email = payload.bill_email
    inv.message = payload.message
    inv.memo = payload.memo
    inv.total = total
    inv.lines = lines
    if payload.custom is not None or inv.custom is None:
        inv.custom = ruleutil.custom(db, "invoice", payload.custom, before=inv.custom, r=r)


def _snapshot(inv: Invoice) -> dict:
    return {"number": inv.invoice_number, "customer": inv.customer.name if inv.customer else None,
            "total": inv.total, "date": inv.invoice_date, "due": inv.due_date}


@router.post("", response_model=InvoiceDetail, status_code=status.HTTP_201_CREATED)
def create_invoice(payload: InvoiceIn, db: Session = Depends(get_db),
                   user: User = Depends(require_roles(*ROLES))) -> InvoiceDetail:
    company = current_company(db)
    inv = Invoice(created_by=user.id)
    _apply(db, inv, payload, company.id)
    inv.id = uuid.uuid4()
    db.add(inv)
    db.flush()
    audit.record(db, entity_type="invoice", entity_id=inv.id, action="created", user_id=user.id,
                 changes=_snapshot(inv))
    db.commit()
    return _detail(db, inv)


@router.get("/{invoice_id}", response_model=InvoiceDetail)
def get_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db),
                _: User = Depends(require_roles(*ROLES, viewer_can_read=True))) -> InvoiceDetail:
    return _detail(db, _load(db, invoice_id))


@router.put("/{invoice_id}", response_model=InvoiceDetail)
def update_invoice(invoice_id: uuid.UUID, payload: InvoiceIn, db: Session = Depends(get_db),
                   user: User = Depends(require_roles(*ROLES))) -> InvoiceDetail:
    inv = _load(db, invoice_id)
    if inv.is_void:
        raise HTTPException(status.HTTP_409_CONFLICT, "A void invoice can't be changed")
    before = _snapshot(inv)
    _apply(db, inv, payload, inv.company_id)
    audit.record(db, entity_type="invoice", entity_id=inv.id, action="updated", user_id=user.id,
                 changes={"before": before, "after": _snapshot(inv)})
    db.commit()
    return _detail(db, inv)


def _has_payments(db: Session, inv: Invoice) -> bool:
    return db.scalar(select(PaymentApplication.id).where(PaymentApplication.invoice_id == inv.id).limit(1)) is not None


@router.post("/{invoice_id}/void", response_model=InvoiceDetail)
def void_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(require_roles(*ROLES))) -> InvoiceDetail:
    """QuickBooks-style void: the invoice stays (number and history) but is worth zero."""
    inv = _load(db, invoice_id)
    if inv.is_void:
        return _detail(db, inv)
    if _has_payments(db, inv):
        raise HTTPException(status.HTTP_409_CONFLICT, "Remove the payments on this invoice before voiding it")
    inv.is_void, inv.voided_at = True, datetime.now(timezone.utc)
    audit.record(db, entity_type="invoice", entity_id=inv.id, action="voided", user_id=user.id,
                 changes=_snapshot(inv))
    db.commit()
    return _detail(db, inv)


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(require_roles(*ROLES))) -> Response:
    inv = _load(db, invoice_id)
    if _has_payments(db, inv):
        raise HTTPException(status.HTTP_409_CONFLICT, "Remove the payments on this invoice before deleting it")
    inv.is_deleted = True
    audit.record(db, entity_type="invoice", entity_id=inv.id, action="deleted", user_id=user.id,
                 changes=_snapshot(inv))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{invoice_id}/mark-sent", response_model=InvoiceDetail)
def mark_sent(invoice_id: uuid.UUID, sent: bool = True, db: Session = Depends(get_db),
              user: User = Depends(require_roles(*ROLES))) -> InvoiceDetail:
    """For invoices sent outside the app (printed, or the PDF emailed by hand)."""
    inv = _load(db, invoice_id)
    inv.sent_at = datetime.now(timezone.utc) if sent else None
    audit.record(db, entity_type="invoice", entity_id=inv.id, action="marked_sent" if sent else "marked_not_sent",
                 user_id=user.id)
    db.commit()
    return _detail(db, inv)


# ---------------------------------------------------------------- PDF
def _pdf_name(inv: Invoice) -> str:
    safe = "".join(ch for ch in inv.invoice_number if ch.isalnum() or ch in "-_") or "invoice"
    return f"Invoice-{safe}.pdf"


def _pdf_bytes(db: Session, inv: Invoice) -> bytes:
    return render_invoice(service.build_doc(db, inv, current_company(db)))


@router.get("/{invoice_id}/pdf")
def invoice_pdf(invoice_id: uuid.UUID, download: bool = False, db: Session = Depends(get_db),
                _: User = Depends(require_roles(*ROLES, viewer_can_read=True))) -> Response:
    inv = _load(db, invoice_id)
    data = _pdf_bytes(db, inv)
    disposition = "attachment" if download else "inline"
    return Response(content=data, media_type="application/pdf", headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(_pdf_name(inv))}",
        "Cache-Control": "private, no-store"})


# ---------------------------------------------------------------- email
def _draft(db: Session, inv: Invoice) -> EmailDraftOut:
    company = current_company(db)
    settings = db.scalar(select(EmailSettings))
    paid = service.paid_on(db, inv.id)
    balance = max(Decimal(inv.total) - paid, ZERO)
    cust = inv.customer
    to = [a for a in [inv.bill_email or (cust.email if cust else None)] if a]
    cc = [a.strip() for a in (cust.cc_emails or "").split(",") if a.strip()] if cust else []
    sender = company.legal_name or company.name
    r = rules.of(company)
    fmt = rules.Formatter(r, company.base_currency)
    values = {"customer": cust.name if cust else "customer", "invoice_number": inv.invoice_number,
              "total": fmt.money(inv.total), "balance": fmt.money(balance), "due_date": fmt.date(inv.due_date),
              "invoice_date": fmt.date(inv.invoice_date), "terms": r.term_name(inv.terms) or "",
              "company": sender, "phone": company.phone or "", "email": company.email or "",
              "website": company.website or "", "payment_instructions": (company.invoice_footer or "").strip()}
    body = rules.render_template(r.email_body, values)
    subject = rules.render_template(r.email_subject, values)
    return EmailDraftOut(
        to=to, cc=cc, subject=subject, body=body,
        configured=outbox.is_ready(settings), from_label=outbox.from_label(settings))


@router.get("/{invoice_id}/email-draft", response_model=EmailDraftOut)
def email_draft(invoice_id: uuid.UUID, db: Session = Depends(get_db),
                _: User = Depends(require_roles(*ROLES))) -> EmailDraftOut:
    return _draft(db, _load(db, invoice_id))


def _html(body: str) -> str:
    import html

    paras = "".join(f"<p style=\"margin:0 0 12px\">{html.escape(p).replace(chr(10), '<br>')}</p>"
                    for p in body.split("\n\n") if p.strip())
    return (f"<div style=\"font-family:Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.5;color:#1b2430\">"
            f"{paras}</div>")


@router.post("/{invoice_id}/send", response_model=InvoiceDetail)
def send_invoice(invoice_id: uuid.UUID, payload: SendInvoiceIn, db: Session = Depends(get_db),
                 user: User = Depends(require_roles(*ROLES))) -> InvoiceDetail:
    inv = _load(db, invoice_id)
    if inv.is_void:
        raise HTTPException(status.HTTP_409_CONFLICT, "A void invoice can't be sent")
    if not outbox.is_ready(outbox.settings_row(db)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Set up email in Settings > Email first")
    mail = outbox.OutMail(to=payload.to, cc=payload.cc, subject=payload.subject, text=payload.body,
                          html=_html(payload.body), attachment=(_pdf_name(inv), _pdf_bytes(db, inv), "application/pdf"))
    sent_to = ", ".join(payload.to + payload.cc)
    try:
        outbox.send(db, mail)
    except SecretUnavailable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except mailer.MailError as exc:
        db.add(InvoiceEmail(invoice_id=inv.id, sent_to=sent_to[:1000], subject=payload.subject[:255], status="failed",
                            error=str(exc)[:1000], sent_by=user.id))
        db.commit()
        log.warning("Invoice %s email failed: %s", inv.invoice_number, exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    db.add(InvoiceEmail(invoice_id=inv.id, sent_to=sent_to[:1000], subject=payload.subject[:255], status="sent",
                        sent_by=user.id))
    inv.sent_at = datetime.now(timezone.utc)
    audit.record(db, entity_type="invoice", entity_id=inv.id, action="emailed", user_id=user.id,
                 changes={"to": sent_to, "subject": payload.subject})
    db.commit()
    return _detail(db, inv)
