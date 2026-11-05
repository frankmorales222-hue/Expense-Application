# No "from __future__ import annotations": FastAPI resolves the _Filters dependency at runtime.
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from .. import audit
from ..banking import engine
from ..banking.normalize import fingerprint_base, merchant_key
from ..config import get_settings
from ..database import get_db
from ..models import (
    BillPayment, Customer, Expense, ExpenseCategory, ExpenseLine, FinancialAccount, LedgerAccount, Receipt, Transaction, User,
    Vendor,
)
from ..schemas import (
    ApproveConfidentIn, BulkIds, BulkResult, CandidatesOut, ExpenseDetail, LinkTransferIn,
    ManualTransactionIn, PeerOut, TransactionOut, TransactionPage, TransactionUpdate,
)
from ..security import require_roles
from .accounts import load_account
from .expenses import _detail, _list_item
from .util import current_company, like_pattern

router = APIRouter(prefix="/api/transactions", tags=["transactions"])
ROLES = ("admin", "approver")
Tab = Literal["review", "approved", "excluded", "all"]
Flag = Literal["transfer", "duplicate", "uncategorized", "missing_receipt", "money_in", "money_out"]
_TAB_STATUS = {"review": "unreviewed", "approved": "approved", "excluded": "excluded"}
_SORTS = {
    "date_desc": (Transaction.txn_date.desc(), Transaction.created_at.desc()),
    "date_asc": (Transaction.txn_date.asc(), Transaction.created_at.asc()),
    "amount_desc": (Transaction.amount.desc(),),
    "amount_asc": (Transaction.amount.asc(),),
}


# ---------------------------------------------------------------- serialization
def _receipt_counts(db: Session, expense_ids: set[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not expense_ids:
        return {}
    return dict(db.execute(select(Receipt.expense_id, func.count(Receipt.id))
                           .where(Receipt.expense_id.in_(expense_ids)).group_by(Receipt.expense_id)).all())


def serialize(db: Session, txns: list[Transaction]) -> list[TransactionOut]:
    accounts = {a.id: a for a in db.scalars(select(FinancialAccount))}
    cats = {c.id: c.name for c in db.scalars(select(ExpenseCategory))}
    allocation_ids = {t.allocation_account_id for t in txns if t.allocation_account_id}
    allocations = ({a.id: a.name for a in db.scalars(select(LedgerAccount).where(LedgerAccount.id.in_(allocation_ids)))}
                   if allocation_ids else {})
    vendor_ids = {t.vendor_id for t in txns if t.vendor_id}
    vendors = {v.id: v.name for v in db.scalars(select(Vendor).where(Vendor.id.in_(vendor_ids)))} if vendor_ids else {}
    cust_ids = {t.customer_id for t in txns if t.customer_id}
    customers = ({c.id: c.name for c in db.scalars(select(Customer).where(Customer.id.in_(cust_ids)))}
                 if cust_ids else {})
    ref_ids = {i for t in txns for i in (t.transfer_peer_id, t.duplicate_of_id) if i}
    refs = {r.id: r for r in db.scalars(select(Transaction).where(Transaction.id.in_(ref_ids)))} if ref_ids else {}
    receipts = _receipt_counts(db, {t.expense_id for t in txns if t.expense_id})
    from ..models import BillAttachment

    txn_ids = [t.id for t in txns]
    paid_bills = dict(db.execute(select(BillPayment.transaction_id, BillPayment.bill_id)
                                 .where(BillPayment.transaction_id.in_(txn_ids))).all()) if txn_ids else {}
    from ..models import CustomerPayment, PaymentApplication

    received = dict(db.execute(select(CustomerPayment.transaction_id, CustomerPayment.id)
                               .where(CustomerPayment.transaction_id.in_(txn_ids))).all()) if txn_ids else {}
    applied: dict = {}
    if received:
        for pay_id, inv_id in db.execute(select(PaymentApplication.payment_id, PaymentApplication.invoice_id)
                                         .where(PaymentApplication.payment_id.in_(set(received.values())))):
            applied.setdefault(pay_id, []).append(inv_id)
    bill_docs = dict(db.execute(select(BillAttachment.bill_id, func.count(BillAttachment.id))
                                .where(BillAttachment.bill_id.in_(set(paid_bills.values())))
                                .group_by(BillAttachment.bill_id)).all()) if paid_bills else {}

    def peer(ref_id: uuid.UUID | None) -> PeerOut | None:
        r = refs.get(ref_id) if ref_id else None
        if r is None:
            return None
        return PeerOut(id=r.id, account_id=r.account_id, account_name=accounts[r.account_id].name,
                       txn_date=r.txn_date, amount=r.amount, description=r.description,
                       review_status=r.review_status)

    out = []
    for t in txns:
        account = accounts[t.account_id]
        if t.amount > 0 or t.is_transfer or t.allocation_account_id:
            receipt = "not_needed"
        else:
            receipt = "attached" if t.expense_id and receipts.get(t.expense_id) else "missing"
            if t.id in paid_bills:
                receipt = "attached" if bill_docs.get(paid_bills[t.id]) else "missing"
        out.append(TransactionOut(
            id=t.id, account_id=t.account_id, account_name=account.name, account_kind=account.kind,
            txn_date=t.txn_date, amount=t.amount, description=t.description, normalized=t.normalized,
            memo=t.memo, source=t.source, review_status=t.review_status,
            category_id=t.category_id, category_name=cats.get(t.category_id) if t.category_id else None,
            allocation_account_id=t.allocation_account_id,
            allocation_account_name=allocations.get(t.allocation_account_id) if t.allocation_account_id else None,
            vendor_id=t.vendor_id, vendor_name=vendors.get(t.vendor_id) if t.vendor_id else None,
            customer_id=t.customer_id, customer_name=customers.get(t.customer_id) if t.customer_id else None,
            suggested_category_id=t.suggested_category_id,
            suggested_category_name=cats.get(t.suggested_category_id) if t.suggested_category_id else None,
            suggested_vendor_name=t.suggested_vendor_name, confidence=t.confidence,
            suggestion_reason=t.suggestion_reason, is_transfer=t.is_transfer,
            transfer_peer=peer(t.transfer_peer_id), duplicate_of=peer(t.duplicate_of_id),
            expense_id=t.expense_id, receipt_status=receipt, approved_at=t.approved_at,
            bill_id=paid_bills.get(t.id), customer_payment_id=received.get(t.id),
            invoice_ids=applied.get(received.get(t.id), []),
            reconciled=t.reconciled, reconciliation_id=t.reconciliation_id,
        ))
    return out


def _one(db: Session, t: Transaction) -> TransactionOut:
    return serialize(db, [t])[0]


def _load(db: Session, txn_id: uuid.UUID) -> Transaction:
    t = db.get(Transaction, txn_id)
    if t is None or t.company_id != current_company(db).id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    return t


def _ensure_not_reconciled(t: Transaction) -> None:
    if t.reconciled:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This transaction is part of a completed reconciliation and cannot be changed")


# ---------------------------------------------------------------- list
class _Filters:
    def __init__(
        self,
        account_id: uuid.UUID | None = None,
        tab: Tab = "review",
        flag: Flag | None = None,
        search: str | None = Query(default=None, max_length=200),
        date_from: date | None = None,
        date_to: date | None = None,
        sort: Literal["date_desc", "date_asc", "amount_desc", "amount_asc"] = "date_desc",
    ) -> None:
        self.account_id, self.tab, self.flag, self.search = account_id, tab, flag, search
        self.date_from, self.date_to, self.sort = date_from, date_to, sort

    def base(self, db: Session) -> Select:
        stmt = select(Transaction).where(Transaction.company_id == current_company(db).id)
        if self.account_id:
            stmt = stmt.where(Transaction.account_id == self.account_id)
        if self.date_from:
            stmt = stmt.where(Transaction.txn_date >= self.date_from)
        if self.date_to:
            stmt = stmt.where(Transaction.txn_date <= self.date_to)
        if self.search and self.search.strip():
            pattern = like_pattern(self.search.strip())
            vendor_match = select(Vendor.id).where(Vendor.name.ilike(pattern, escape="\\"))
            stmt = stmt.where(or_(Transaction.description.ilike(pattern, escape="\\"),
                                  Transaction.memo.ilike(pattern, escape="\\"),
                                  Transaction.vendor_id.in_(vendor_match)))
        return stmt

    def query(self, db: Session) -> Select:
        stmt = self.base(db)
        if self.tab in _TAB_STATUS:
            stmt = stmt.where(Transaction.review_status == _TAB_STATUS[self.tab])
        if self.flag == "transfer":
            stmt = stmt.where(Transaction.is_transfer.is_(True))
        elif self.flag == "duplicate":
            stmt = stmt.where(Transaction.duplicate_of_id.is_not(None))
        elif self.flag == "uncategorized":
            stmt = stmt.where(Transaction.is_transfer.is_(False), Transaction.category_id.is_(None),
                              Transaction.allocation_account_id.is_(None),
                              Transaction.suggested_category_id.is_(None))
        elif self.flag == "missing_receipt":
            with_receipts = select(Receipt.expense_id)
            stmt = stmt.where(Transaction.amount < 0, Transaction.is_transfer.is_(False),
                              Transaction.allocation_account_id.is_(None),
                              or_(Transaction.expense_id.is_(None), Transaction.expense_id.not_in(with_receipts)))
        elif self.flag == "money_in":
            stmt = stmt.where(Transaction.amount > 0)
        elif self.flag == "money_out":
            stmt = stmt.where(Transaction.amount < 0)
        return stmt


@router.get("", response_model=TransactionPage)
def list_transactions(
    filters: _Filters = Depends(),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*ROLES)),
) -> TransactionPage:
    stmt = filters.query(db)
    sub = stmt.subquery()
    total, total_in, total_out = db.execute(select(
        func.count(),
        func.coalesce(func.sum(sub.c.amount).filter(sub.c.amount > 0), 0),
        func.coalesce(func.sum(sub.c.amount).filter(sub.c.amount < 0), 0),
    )).one()
    rows = list(db.scalars(stmt.order_by(*_SORTS[filters.sort]).limit(page_size).offset((page - 1) * page_size)))
    base = filters.base(db).subquery()
    counts = {s: 0 for s in ("unreviewed", "approved", "excluded")}
    counts.update(dict(db.execute(select(base.c.review_status, func.count()).group_by(base.c.review_status)).all()))
    def money(v: object) -> Decimal:
        return Decimal(str(v or 0)).quantize(Decimal("0.01"))

    return TransactionPage(
        items=serialize(db, rows), total=total, page=page, page_size=page_size,
        counts={"review": counts["unreviewed"], "approved": counts["approved"], "excluded": counts["excluded"]},
        total_in=money(total_in), total_out=-money(total_out),
    )


# ---------------------------------------------------------------- create / edit
@router.post("", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_manual(payload: ManualTransactionIn, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(*ROLES))) -> TransactionOut:
    account = load_account(db, payload.account_id)
    t = Transaction(
        id=uuid.uuid4(), company_id=account.company_id, account_id=account.id, source="manual",
        txn_date=payload.txn_date, amount=payload.amount, description=payload.description,
        normalized=merchant_key(payload.description), memo=payload.memo,
        fingerprint=f"manual:{uuid.uuid4().hex}",
    )
    db.add(t)
    db.flush()
    _apply_category(db, t, payload.category_id)
    _apply_customer(db, t, payload.customer_id)
    if payload.vendor_name:
        t.vendor_id = engine.get_or_create_vendor_by_name(db, payload.vendor_name).id
    engine.suggest(db, [t])
    db.flush()
    engine.approve_by_rules(db, user)
    audit.record(db, entity_type="transaction", entity_id=t.id, action="created", user_id=user.id, changes={
        "account": account.name, "date": t.txn_date, "amount": t.amount, "description": t.description,
        "fingerprint_base": fingerprint_base(t.txn_date, t.amount, t.description)})
    db.commit()
    return _one(db, t)


def _apply_category(db: Session, t: Transaction, category_id: uuid.UUID | None) -> None:
    if category_id is None:
        t.category_id = None
        return
    cat = db.get(ExpenseCategory, category_id)
    if cat is None or (not cat.is_active and cat.id != t.category_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Category not found or inactive")
    t.category_id = cat.id


def _apply_customer(db: Session, t: Transaction, customer_id: uuid.UUID | None) -> None:
    if customer_id is None:
        t.customer_id = None
        return
    customer = db.get(Customer, customer_id)
    if customer is None or customer.company_id != t.company_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Customer not found")
    t.customer_id = customer.id


@router.patch("/{txn_id}", response_model=TransactionOut)
def update_transaction(txn_id: uuid.UUID, payload: TransactionUpdate, db: Session = Depends(get_db),
                       user: User = Depends(require_roles(*ROLES))) -> TransactionOut:
    t = _load(db, txn_id)
    _ensure_not_reconciled(t)
    sent = payload.model_fields_set
    before = {"category_id": t.category_id, "allocation_account_id": t.allocation_account_id,
              "vendor_id": t.vendor_id, "customer_id": t.customer_id,
              "memo": t.memo, "expense_id": t.expense_id}
    if "category_id" in sent:
        if t.is_transfer and payload.category_id is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Unlink the transfer before categorizing it")
        _apply_category(db, t, payload.category_id)
        if payload.category_id is not None:
            t.allocation_account_id = None
    if "vendor_name" in sent:
        name = (payload.vendor_name or "").strip()
        t.vendor_id = engine.get_or_create_vendor_by_name(db, name).id if name else None
        if not name:
            t.suggested_vendor_id, t.suggested_vendor_name = None, None
    if "customer_id" in sent:
        _apply_customer(db, t, payload.customer_id)
    if "memo" in sent:
        t.memo = (payload.memo or "").strip() or None
    if "expense_id" in sent:
        if payload.expense_id is None:
            t.expense_id = None
        else:
            if payload.expense_id not in {e.id for e in engine.expense_candidates(db, t)} and \
                    payload.expense_id != t.expense_id:
                exp = db.get(Expense, payload.expense_id)
                if exp is None or exp.is_deleted:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Expense not found")
                if db.scalar(select(Transaction.id).where(Transaction.expense_id == exp.id, Transaction.id != t.id)):
                    raise HTTPException(status.HTTP_409_CONFLICT, "That expense is linked to another transaction")
            exp = db.get(Expense, payload.expense_id)
            if exp is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Expense not found")
            if exp.payment_account_id not in (None, t.account_id) and not exp.is_reimbursable:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    "That expense says it was paid from a different account")
            engine.link_expense(t, exp)
    after = {"category_id": t.category_id, "allocation_account_id": t.allocation_account_id,
             "vendor_id": t.vendor_id, "customer_id": t.customer_id,
             "memo": t.memo, "expense_id": t.expense_id}
    changes = {k: [before[k], after[k]] for k in before if before[k] != after[k]}
    if changes:
        audit.record(db, entity_type="transaction", entity_id=t.id, action="updated", user_id=user.id,
                     changes=changes)
        if t.review_status == "approved" and "category_id" in changes:
            engine.learn_from(db, t)
    db.commit()
    return _one(db, t)


# ---------------------------------------------------------------- review actions
def _approve_one(db: Session, t: Transaction, user: User) -> list[Transaction]:
    try:
        changed = engine.approve(db, t, user)
    except engine.ApprovalError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    for x in changed:
        audit.record(db, entity_type="transaction", entity_id=x.id, action="approved", user_id=user.id,
                     changes={"category_id": x.category_id, "is_transfer": x.is_transfer,
                              "confidence": x.confidence})
    return changed


@router.post("/{txn_id}/approve", response_model=TransactionOut)
def approve(txn_id: uuid.UUID, db: Session = Depends(get_db),
            user: User = Depends(require_roles(*ROLES))) -> TransactionOut:
    t = _load(db, txn_id)
    if t.review_status == "excluded":
        raise HTTPException(status.HTTP_409_CONFLICT, "Restore this transaction before approving it")
    _approve_one(db, t, user)
    db.commit()
    return _one(db, t)


@router.post("/bulk-approve", response_model=BulkResult)
def bulk_approve(payload: BulkIds, db: Session = Depends(get_db),
                 user: User = Depends(require_roles(*ROLES))) -> BulkResult:
    company_id = current_company(db).id
    txns = list(db.scalars(select(Transaction).where(Transaction.id.in_(payload.ids),
                                                     Transaction.company_id == company_id)))
    return _approve_many(db, txns, user)


@router.post("/approve-confident", response_model=BulkResult)
def approve_confident(payload: ApproveConfidentIn, db: Session = Depends(get_db),
                      user: User = Depends(require_roles(*ROLES))) -> BulkResult:
    stmt = select(Transaction).where(
        Transaction.company_id == current_company(db).id, Transaction.review_status == "unreviewed",
        Transaction.confidence >= payload.min_confidence, Transaction.duplicate_of_id.is_(None),
        or_(Transaction.is_transfer.is_(True), Transaction.allocation_account_id.is_not(None),
            Transaction.category_id.is_not(None),
            Transaction.suggested_category_id.is_not(None)),
    ).order_by(Transaction.txn_date)
    if payload.account_id:
        stmt = stmt.where(Transaction.account_id == payload.account_id)
    return _approve_many(db, list(db.scalars(stmt)), user)


def _approve_many(db: Session, txns: list[Transaction], user: User) -> BulkResult:
    approved, skipped, messages = 0, 0, []
    for t in txns:
        if t.review_status != "unreviewed":
            continue
        try:
            approved += len(engine.approve(db, t, user))
        except engine.ApprovalError:
            skipped += 1
            if len(messages) < 5:
                messages.append(f"{t.txn_date:%b %d} {t.description[:40]}: needs a category")
    if approved:
        audit.record(db, entity_type="transaction", entity_id=uuid.uuid4(), action="bulk_approved",
                     user_id=user.id, changes={"approved": approved, "skipped": skipped})
    db.commit()
    return BulkResult(approved=approved, skipped=skipped, messages=messages)


@router.post("/{txn_id}/exclude", response_model=TransactionOut)
def exclude(txn_id: uuid.UUID, db: Session = Depends(get_db),
            user: User = Depends(require_roles(*ROLES))) -> TransactionOut:
    t = _load(db, txn_id)
    _ensure_not_reconciled(t)
    if t.is_transfer:
        engine.unlink_transfer(db, t)
    t.review_status, t.approved_by, t.approved_at = "excluded", None, None
    audit.record(db, entity_type="transaction", entity_id=t.id, action="excluded", user_id=user.id)
    db.commit()
    return _one(db, t)


@router.post("/{txn_id}/restore", response_model=TransactionOut)
def restore(txn_id: uuid.UUID, db: Session = Depends(get_db),
            user: User = Depends(require_roles(*ROLES))) -> TransactionOut:
    """Move an approved or excluded transaction back to For review."""
    t = _load(db, txn_id)
    if t.reconciled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Reconciled transactions can't be reopened")
    targets = [t]
    if t.is_transfer and t.transfer_peer_id:
        peer = db.get(Transaction, t.transfer_peer_id)
        if peer is not None:
            targets.append(peer)
    for x in targets:
        old = x.review_status
        x.review_status, x.approved_by, x.approved_at = "unreviewed", None, None
        audit.record(db, entity_type="transaction", entity_id=x.id, action="reopened", user_id=user.id,
                     changes={"review_status": [old, "unreviewed"]})
    if not t.is_transfer:
        engine.suggest(db, [t])
    db.commit()
    return _one(db, t)


@router.post("/{txn_id}/not-duplicate", response_model=TransactionOut)
def not_duplicate(txn_id: uuid.UUID, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(*ROLES))) -> TransactionOut:
    t = _load(db, txn_id)
    _ensure_not_reconciled(t)
    t.duplicate_of_id = None
    audit.record(db, entity_type="transaction", entity_id=t.id, action="not_duplicate", user_id=user.id)
    db.commit()
    return _one(db, t)


@router.get("/{txn_id}/candidates", response_model=CandidatesOut)
def candidates(txn_id: uuid.UUID, db: Session = Depends(get_db),
               _: User = Depends(require_roles(*ROLES))) -> CandidatesOut:
    t = _load(db, txn_id)
    accounts = {a.id: a.name for a in db.scalars(select(FinancialAccount))}
    transfers = [] if t.is_transfer else engine.transfer_candidates(db, t, window=10)
    expenses = engine.expense_candidates(db, t)
    receipts = _receipt_counts(db, {e.id for e in expenses})
    return CandidatesOut(
        transfers=[PeerOut(id=c.id, account_id=c.account_id, account_name=accounts[c.account_id],
                           txn_date=c.txn_date, amount=c.amount, description=c.description,
                           review_status=c.review_status) for c in transfers],
        expenses=[_list_item(e, e.vendor.name if e.vendor else None, e.category.name, receipts.get(e.id, 0))
                  for e in expenses],
    )


@router.post("/{txn_id}/link-transfer", response_model=TransactionOut)
def link_transfer(txn_id: uuid.UUID, payload: LinkTransferIn, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(*ROLES))) -> TransactionOut:
    t = _load(db, txn_id)
    peer = _load(db, payload.peer_id)
    _ensure_not_reconciled(t)
    _ensure_not_reconciled(peer)
    if peer.id == t.id or peer.account_id == t.account_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A transfer needs two different accounts")
    if peer.amount != -t.amount:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Transfer amounts must be equal and opposite")
    if t.is_transfer or peer.is_transfer:
        raise HTTPException(status.HTTP_409_CONFLICT, "One of these is already part of a transfer")
    if "approved" in (t.review_status, peer.review_status):
        raise HTTPException(status.HTTP_409_CONFLICT, "Move approved transactions back to review first")
    engine.link_transfer(t, peer, 100, "Linked by you")
    audit.record(db, entity_type="transaction", entity_id=t.id, action="transfer_linked", user_id=user.id,
                 changes={"peer": peer.id})
    db.commit()
    return _one(db, t)


@router.post("/{txn_id}/unlink-transfer", response_model=TransactionOut)
def unlink_transfer(txn_id: uuid.UUID, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(*ROLES))) -> TransactionOut:
    t = _load(db, txn_id)
    _ensure_not_reconciled(t)
    if not t.is_transfer:
        raise HTTPException(status.HTTP_409_CONFLICT, "This is not a transfer")
    if t.review_status == "approved":
        raise HTTPException(status.HTTP_409_CONFLICT, "Move it back to review before unlinking")
    peer = engine.unlink_transfer(db, t)
    engine.suggest(db, [x for x in (t, peer) if x is not None])
    audit.record(db, entity_type="transaction", entity_id=t.id, action="transfer_unlinked", user_id=user.id)
    db.commit()
    return _one(db, t)


@router.post("/{txn_id}/create-expense", response_model=ExpenseDetail, status_code=status.HTTP_201_CREATED)
def create_expense_from_transaction(txn_id: uuid.UUID, db: Session = Depends(get_db),
                                    user: User = Depends(require_roles(*ROLES))) -> ExpenseDetail:
    """Make an expense record for a bank charge so a receipt can be attached to it."""
    t = _load(db, txn_id)
    _ensure_not_reconciled(t)
    if t.amount >= 0 or t.is_transfer:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Only money-out transactions need receipts")
    if t.expense_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "This transaction already has an expense")
    category_id = t.category_id or t.suggested_category_id
    cat = db.get(ExpenseCategory, category_id) if category_id else None
    if cat is None or cat.kind != "expense":
        cat = db.scalar(select(ExpenseCategory).where(ExpenseCategory.code == "other"))
    if cat is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a category first")
    account = db.get(FinancialAccount, t.account_id)
    vendor_id = t.vendor_id or t.suggested_vendor_id
    if vendor_id is None and t.suggested_vendor_name:
        vendor_id = engine.get_or_create_vendor_by_name(db, t.suggested_vendor_name).id
    now = datetime.now(timezone.utc)
    expense = Expense(
        expense_date=t.txn_date, vendor_id=vendor_id, category_id=cat.id, description=t.description[:500],
        amount=-t.amount, currency=current_company(db).base_currency,
        payment_method="business_card" if account and account.kind == "credit_card" else "business_bank",
        is_reimbursable=False, status="approved", submitted_by=user.id, approved_by=user.id, approved_at=now,
        notes=f"Created from bank transaction in {account.name if account else 'an account'}",
        payment_account_id=t.account_id,
        lines=[ExpenseLine(id=uuid.uuid4(), line_no=0, category_id=cat.id, amount=-t.amount,
                           customer_id=t.customer_id)],
    )
    db.add(expense)
    db.flush()
    engine.link_expense(t, expense)
    audit.record(db, entity_type="expense", entity_id=expense.id, action="created", user_id=user.id,
                 changes={"from_transaction": t.id, "amount": expense.amount})
    db.commit()
    db.refresh(expense)
    return _detail(db, expense, user)
