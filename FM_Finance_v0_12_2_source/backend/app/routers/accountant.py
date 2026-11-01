"""Accountant review: searchable audit history and a portable year/period package."""

from __future__ import annotations

import csv
import io
import json
import tempfile
import uuid
import zipfile
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import PurePath

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from ..database import get_db
from ..ledger import reports
from ..models import (
    AuditLog, Bill, BillAttachment, Company, Expense, FinancialAccount, Invoice, JournalEntry, JournalLine,
    LedgerAccount, Receipt, Reconciliation, Transaction, User, Vendor,
)
from ..schemas import AuditLogOut, AuditLogPage
from ..security import require_roles
from ..storage import ReceiptStorage, get_storage
from .util import current_company

router = APIRouter(tags=["accountant"])
ROLES = ("admin", "approver")


def _audit_out(row: AuditLog) -> AuditLogOut:
    return AuditLogOut(id=row.id, entity_type=row.entity_type, entity_id=row.entity_id, action=row.action,
                       user_id=row.user_id, user_name=row.user.name if row.user else None,
                       user_email=row.user.email if row.user else None, changes=row.changes, created_at=row.created_at)


@router.get("/api/audit", response_model=AuditLogPage)
def audit_history(entity_type: str | None = Query(default=None, max_length=50),
                  action: str | None = Query(default=None, max_length=50), user_id: uuid.UUID | None = None,
                  date_from: date | None = None, date_to: date | None = None,
                  page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200),
                  db: Session = Depends(get_db), _: User = Depends(require_roles(*ROLES))) -> AuditLogPage:
    stmt = select(AuditLog)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, time.min, timezone.utc))
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= datetime.combine(date_to, time.max, timezone.utc))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(page_size).offset((page - 1) * page_size)))
    return AuditLogPage(items=[_audit_out(row) for row in rows], total=total, page=page, page_size=page_size)


def _text(value: object) -> object:
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, (date, datetime, uuid.UUID)):
        return str(value)
    if value is None:
        return ""
    return value


def _csv_bytes(headers: list[str], rows: list[list[object]]) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(headers)
    writer.writerows([[_text(value) for value in row] for row in rows])
    return out.getvalue().encode("utf-8-sig")


def _safe_zip_name(name: str) -> str:
    clean = PurePath(name.replace("\\", "/")).name.strip() or "document"
    return "".join(ch for ch in clean if ch not in '<>:"/\\|?*')[:180] or "document"


def _write_documents(zf: zipfile.ZipFile, db: Session, storage: ReceiptStorage,
                     date_from: date, date_to: date) -> list[dict[str, object]]:
    index: list[dict[str, object]] = []
    receipts = list(db.scalars(select(Receipt).join(Expense, Expense.id == Receipt.expense_id).where(
        Expense.expense_date.between(date_from, date_to), Expense.is_deleted.is_(False))))
    for item in receipts:
        path = f"documents/expenses/{item.expense_id}/{_safe_zip_name(item.original_filename)}"
        try:
            with zf.open(path, "w") as target:
                for block in storage.open(item.object_key):
                    target.write(block)
            index.append({"kind": "expense_receipt", "record_id": str(item.expense_id), "file": path,
                          "status": "included"})
        except Exception as exc:  # keep the financial package usable when one attachment is unavailable
            index.append({"kind": "expense_receipt", "record_id": str(item.expense_id), "file": path,
                          "status": f"unavailable: {type(exc).__name__}"})
    attachments = list(db.scalars(select(BillAttachment).join(Bill, Bill.id == BillAttachment.bill_id).where(
        Bill.bill_date.between(date_from, date_to), Bill.is_deleted.is_(False))))
    for item in attachments:
        path = f"documents/bills/{item.bill_id}/{_safe_zip_name(item.original_filename)}"
        try:
            with zf.open(path, "w") as target:
                for block in storage.open(item.object_key):
                    target.write(block)
            index.append({"kind": "bill_attachment", "record_id": str(item.bill_id), "file": path,
                          "status": "included"})
        except Exception as exc:
            index.append({"kind": "bill_attachment", "record_id": str(item.bill_id), "file": path,
                          "status": f"unavailable: {type(exc).__name__}"})
    statements = list(db.scalars(select(Reconciliation).where(
        Reconciliation.statement_date.between(date_from, date_to),
        Reconciliation.statement_object_key.is_not(None))))
    for item in statements:
        path = (f"documents/statements/{_safe_zip_name(item.account.name)}/"
                f"{item.statement_date}-{_safe_zip_name(item.statement_filename or 'statement')}")
        try:
            with zf.open(path, "w") as target:
                for block in storage.open(item.statement_object_key or ""):
                    target.write(block)
            index.append({"kind": "bank_statement", "record_id": str(item.id), "file": path,
                          "status": "included"})
        except Exception as exc:
            index.append({"kind": "bank_statement", "record_id": str(item.id), "file": path,
                          "status": f"unavailable: {type(exc).__name__}"})
    return index


@router.get("/api/accountant/export")
def accountant_export(date_from: date, date_to: date, db: Session = Depends(get_db),
                      _: User = Depends(require_roles(*ROLES)),
                      storage: ReceiptStorage = Depends(get_storage)) -> StreamingResponse:
    if date_from > date_to:
        raise HTTPException(422, "The start date must be on or before the end date")
    company = current_company(db)
    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    with zipfile.ZipFile(spool, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        manifest = {"app": "F&M Finance", "version": __version__, "company": company.name,
                    "company_id": str(company.id), "date_from": str(date_from), "date_to": str(date_to),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "contents": "CSV financial records plus available receipts, bill documents and bank statements"}
        zf.writestr("README.json", json.dumps(manifest, indent=2).encode("utf-8"))

        account_names = {a.id: a.name for a in db.scalars(select(FinancialAccount))}
        ledger_names = {a.id: a for a in db.scalars(select(LedgerAccount))}
        vendor_names = {v.id: v.name for v in db.scalars(select(Vendor))}

        gl = db.execute(select(JournalEntry, JournalLine).join(JournalLine, JournalLine.entry_id == JournalEntry.id)
                        .where(JournalEntry.entry_date.between(date_from, date_to))
                        .order_by(JournalEntry.entry_date, JournalEntry.created_at, JournalLine.line_no)).all()
        zf.writestr("general_ledger.csv", _csv_bytes(
            ["date", "journal_id", "source", "source_id", "number", "memo", "account_code", "account",
             "description", "debit", "credit"],
            [[entry.entry_date, entry.id, entry.source_type, entry.source_id, entry.number, entry.memo,
              ledger_names[line.account_id].code, ledger_names[line.account_id].name, line.description,
              line.debit, line.credit] for entry, line in gl]))

        trial = reports.trial_balance(db, company.id, date_to)
        zf.writestr("trial_balance.csv", _csv_bytes(["code", "account", "type", "debit", "credit"],
            [[account.code, account.name, account.type, debit, credit] for account, debit, credit in trial]))
        pnl = reports.profit_and_loss(db, company.id, date_from, date_to)
        zf.writestr("profit_and_loss.csv", _csv_bytes(["section", "code", "account", "amount"],
            [[section.label, row.code, row.name, row.amount] for section in pnl["sections"] for row in section.rows] +
            [["TOTAL", "", "Net income", pnl["net_income"]]]))
        bs = reports.balance_sheet(db, company.id, date_to)
        zf.writestr("balance_sheet.csv", _csv_bytes(["section", "code", "account", "amount"],
            [[section.label, row.code, row.name, row.amount] for section in bs["sections"] for row in section.rows] +
            [["TOTAL", "", "Total assets", bs["total_assets"]],
             ["TOTAL", "", "Total liabilities and equity", bs["total_liabilities_and_equity"]]]))

        txns = list(db.scalars(select(Transaction).where(Transaction.txn_date.between(date_from, date_to))
                               .order_by(Transaction.txn_date, Transaction.created_at)))
        zf.writestr("bank_transactions.csv", _csv_bytes(
            ["date", "account", "description", "amount", "status", "source", "reconciled",
             "reconciliation_id", "memo"],
            [[t.txn_date, account_names.get(t.account_id), t.description, t.amount, t.review_status, t.source,
              t.reconciled, t.reconciliation_id, t.memo] for t in txns]))
        expenses = list(db.scalars(select(Expense).where(Expense.expense_date.between(date_from, date_to),
                                                          Expense.is_deleted.is_(False)).order_by(Expense.expense_date)))
        zf.writestr("expenses.csv", _csv_bytes(
            ["date", "id", "vendor", "description", "amount", "status", "paid_personally", "payment_account",
             "receipt_count", "notes"],
            [[e.expense_date, e.id, e.vendor.name if e.vendor else "", e.description, e.amount, e.status,
              e.is_reimbursable, account_names.get(e.payment_account_id), len(e.receipts), e.notes] for e in expenses]))
        invoices = list(db.scalars(select(Invoice).where(Invoice.invoice_date.between(date_from, date_to),
                                                         Invoice.is_deleted.is_(False)).order_by(Invoice.invoice_date)))
        zf.writestr("invoices.csv", _csv_bytes(
            ["date", "id", "number", "customer", "due_date", "total", "void", "sent_at", "memo"],
            [[i.invoice_date, i.id, i.invoice_number, i.customer.name, i.due_date, i.total, i.is_void, i.sent_at,
              i.memo] for i in invoices]))
        bills = list(db.scalars(select(Bill).where(Bill.bill_date.between(date_from, date_to),
                                                   Bill.is_deleted.is_(False)).order_by(Bill.bill_date)))
        zf.writestr("bills.csv", _csv_bytes(
            ["date", "id", "number", "vendor", "due_date", "total", "paid", "memo", "attachment_count"],
            [[b.bill_date, b.id, b.bill_number, vendor_names.get(b.vendor_id), b.due_date, b.total,
              sum((p.amount for p in b.payments), Decimal("0")), b.memo, len(b.attachments)] for b in bills]))
        reconciliations = list(db.scalars(select(Reconciliation).where(
            Reconciliation.statement_date.between(date_from, date_to)).order_by(Reconciliation.statement_date)))
        zf.writestr("reconciliations.csv", _csv_bytes(
            ["statement_date", "account", "beginning_balance", "ending_balance", "cleared_balance", "difference",
             "status", "completed_at", "statement_file"],
            [[r.statement_date, r.account.name, r.beginning_balance, r.ending_balance, r.cleared_balance,
              r.difference, r.status, r.completed_at, r.statement_filename] for r in reconciliations]))
        events = list(db.scalars(select(AuditLog).where(
            AuditLog.created_at >= datetime.combine(date_from, time.min, timezone.utc),
            AuditLog.created_at <= datetime.combine(date_to, time.max, timezone.utc))
            .order_by(AuditLog.created_at)))
        zf.writestr("audit_log.csv", _csv_bytes(
            ["timestamp", "user", "email", "entity_type", "entity_id", "action", "changes"],
            [[a.created_at, a.user.name if a.user else "System", a.user.email if a.user else "", a.entity_type,
              a.entity_id, a.action, json.dumps(a.changes or {}, sort_keys=True)] for a in events]))
        document_index = _write_documents(zf, db, storage, date_from, date_to)
        zf.writestr("documents/index.json", json.dumps(document_index, indent=2).encode("utf-8"))
    spool.seek(0)

    def body():
        try:
            while block := spool.read(1024 * 1024):
                yield block
        finally:
            spool.close()

    filename = f"FMFinance_Accountant_{date_from}_{date_to}.zip"
    return StreamingResponse(body(), media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"})
