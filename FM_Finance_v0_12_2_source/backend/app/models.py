"""SQLAlchemy models. The schema itself is created by Alembic migrations."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import Boolean, Date, ForeignKey, Integer, JSON, LargeBinary, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .types import CurrencyAmount, UTCDateTime

EXPENSE_STATUSES = ("pending", "approved", "paid", "rejected")
CATEGORY_KINDS = ("expense", "income", "equity")
ACCOUNT_KINDS = ("checking", "savings", "credit_card", "cash", "other")
REVIEW_STATUSES = ("unreviewed", "approved", "excluded")
PAYMENT_METHODS = ("business_card", "business_bank", "personal_card", "cash", "other")
USER_ROLES = ("admin", "approver", "submitter")  # legacy (v0.1-v0.4); access now comes from memberships
COMPANY_ROLES = ("owner", "accountant", "bookkeeper", "employee", "viewer")
# How a company role maps onto the permission names the routes check.
ROLE_ACCESS = {"owner": "admin", "accountant": "approver", "bookkeeper": "approver",
               "employee": "submitter", "viewer": "viewer"}


class CompanyScoped:
    """Mixin: rows belong to one company. Reads are filtered and new rows stamped automatically
    (see app/tenancy.py), on top of the explicit checks in the routes."""

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), nullable=False, index=False)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))


def _created() -> Mapped[datetime]:
    return mapped_column(UTCDateTime(), server_default=func.now(), nullable=False)


def _updated() -> Mapped[datetime]:
    return mapped_column(UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="admin", server_default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    # Incremented on password change; sessions issued with an older value stop working.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # The software vendor's administrators: manage resellers and create companies.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    # v0.9.0: the look this person chose (classic | executive | dark); None = the company's default.
    theme: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    # Per request (not stored): set by app.security when the current company is resolved.
    company_role: ClassVar[str | None] = None
    access_role: ClassVar[str | None] = None
    custom_role: ClassVar["CompanyRole | None"] = None  # v0.10.0
    area_levels: ClassVar[dict[str, str]] = {}


class ExpenseCategory(CompanyScoped, Base):
    __tablename__ = "expense_categories"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(50), nullable=False)  # unique per company
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    approval_threshold: Mapped[Decimal | None] = mapped_column(CurrencyAmount(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Ledger-ready: categories become chart-of-accounts entries in Phase 4.
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="expense", server_default="expense")
    tax_line: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # The chart-of-accounts entry this category posts to (created automatically).
    ledger_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ledger_accounts.id"), nullable=True)
    # Declared so new ledger accounts are always inserted before the rows that point at them.
    ledger_account: Mapped["LedgerAccount | None"] = relationship(lazy="select")


class Vendor(CompanyScoped, Base):
    __tablename__ = "vendors"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # unique per company (case-insensitive)
    # Normalized bank-description key learned from approvals (e.g. "AMAZON COM AMZN").
    match_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expense_categories.id"), nullable=True)
    is_1099: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = _created()


class Expense(CompanyScoped, Base):
    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    custom: Mapped[dict[str, Any] | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"), nullable=True)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("expense_categories.id"), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default="USD")
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_reimbursable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="approved", server_default="approved")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # legacy (v0.4); bills have due dates now
    # Bank/card account the vendor was paid from; for "paid personally" expenses, the account the
    # person was reimbursed from (set when marked paid).
    payment_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_accounts.id"), nullable=True)
    submitted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    category: Mapped[ExpenseCategory] = relationship(lazy="joined")
    vendor: Mapped[Vendor | None] = relationship(lazy="joined")
    payment_account: Mapped["FinancialAccount | None"] = relationship(lazy="joined")
    receipts: Mapped[list[Receipt]] = relationship(
        back_populates="expense", order_by="Receipt.uploaded_at", cascade="all, delete-orphan"
    )
    lines: Mapped[list[ExpenseLine]] = relationship(
        order_by="ExpenseLine.line_no", cascade="all, delete-orphan", lazy="selectin"
    )


class Receipt(CompanyScoped, Base):
    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    expense_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = _created()

    expense: Mapped[Expense] = relationship(back_populates="receipts")


class AuditLog(CompanyScoped, Base):
    __tablename__ = "audit_log"

    # Account-level events (password change, reseller setup) belong to no company.
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"), nullable=True)

    id: Mapped[uuid.UUID] = _uuid_pk()
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    created_at: Mapped[datetime] = _created()

    user: Mapped[User | None] = relationship(lazy="joined")


class BankTransaction(Base):
    """Created now so bank sync can be added later without a disruptive migration. No UI yet."""

    __tablename__ = "bank_transactions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    matched_expense_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id"), nullable=True)
    imported_at: Mapped[datetime] = _created()


# ---------------------------------------------------------------------------
# Phase 1: banking foundation
# ---------------------------------------------------------------------------
class Reseller(Base):
    """A partner (e.g. an accounting firm) that offers F&M Finance to its own client companies."""

    __tablename__ = "resellers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = _created()


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    reseller_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resellers.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default="USD")
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # Company logo, stored re-encoded as PNG (shown in the sidebar, sign-in page and, later, on invoices).
    logo_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    logo_content_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    logo_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Books are locked on and before this date (QuickBooks "closing date").
    closing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Set once the ledger has been built from this company's existing records (v0.6.0 upgrade).
    ledger_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Shown on invoices (v0.7.0).
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invoice_footer: Mapped[str | None] = mapped_column(Text, nullable=True)  # e.g. how to pay you
    # v0.8.0 plan: module keys switched on (None = every module, for companies from before plans), and the
    # user limit (None = unlimited). See app/modules.py.
    plan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    modules: Mapped[list[str] | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    user_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # v0.9.0: the look people in this company get until they choose their own (None = classic).
    default_theme: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # v0.10.0: the company's own rules (only what it changed; see app/rules.py)
    rules: Mapped[dict[str, Any] | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    created_at: Mapped[datetime] = _created()


class FinancialAccount(CompanyScoped, Base):
    """A bank account, credit card, or cash account that transactions belong to."""

    __tablename__ = "financial_accounts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default="USD")
    opening_balance: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False, default=Decimal("0"),
                                                     server_default="0")
    opening_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    csv_profile: Mapped[dict[str, Any] | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    ledger_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ledger_accounts.id"), nullable=True)
    created_at: Mapped[datetime] = _created()

    ledger_account: Mapped["LedgerAccount | None"] = relationship(lazy="select")


class Customer(CompanyScoped, Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    custom: Mapped[dict[str, Any] | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    # v0.7.0 invoicing
    cc_emails: Mapped[str | None] = mapped_column(String(500), nullable=True)  # comma-separated
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_terms: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = _created()


class ImportBatch(CompanyScoped, Base):
    __tablename__ = "import_batches"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_accounts.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # csv | ofx
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_duplicate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_invalid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_flagged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active", server_default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()


class Transaction(CompanyScoped, Base):
    """A normalized money movement on a financial account. Negative amount = money out."""

    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_accounts.id"), nullable=False)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # csv | ofx | manual
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(80), nullable=False)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)

    review_status: Mapped[str] = mapped_column(String(12), nullable=False, default="unreviewed",
                                               server_default="unreviewed")
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expense_categories.id"), nullable=True)
    # v0.11.0: a bank transaction can post directly to a balance-sheet account (for example an owner-loan
    # repayment) instead of being forced through an income/expense category.
    allocation_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ledger_accounts.id"), nullable=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"), nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), nullable=True)

    suggested_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expense_categories.id"), nullable=True)
    suggested_vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"), nullable=True)
    suggested_vendor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    suggestion_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_transfer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    transfer_peer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    expense_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id"), nullable=True)
    reconciled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    # v0.12.0: selected transactions belong to a draft or completed statement reconciliation.
    reconciliation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reconciliations.id", ondelete="SET NULL"), nullable=True)

    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Reconciliation(CompanyScoped, Base):
    """A saved bank/card statement reconciliation.

    Transactions point at the reconciliation while it is in progress.  They become locked when
    the reconciliation is completed, preserving the statement history for the accountant.
    """

    __tablename__ = "reconciliations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_accounts.id"), nullable=False)
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    beginning_balance: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False)
    ending_balance: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False)
    cleared_balance: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False, default=Decimal("0"))
    difference: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft", server_default="draft")
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    statement_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    statement_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    statement_content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    statement_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    account: Mapped[FinancialAccount] = relationship(lazy="joined")


class CompanyMember(Base):
    """A user's access to one company, with a role."""

    __tablename__ = "company_members"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # v0.10.0: a role the company defined (its base role is kept in `role`)
    custom_role_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("company_roles.id", ondelete="SET NULL"),
                                                             nullable=True)
    created_at: Mapped[datetime] = _created()


class CompanyRole(Base):
    """A role a company defines: a base role (owner, accountant, bookkeeper, employee, viewer) plus what it may
    see and change in each area. See app/permissions.py."""

    __tablename__ = "company_roles"

    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    base_role: Mapped[str] = mapped_column(String(20), nullable=False)
    permissions: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    created_at: Mapped[datetime] = _created()


class Plan(Base):
    """A plan: a bundle of modules and a user limit. reseller_id NULL: the platform owner's plans, offered to
    everyone; otherwise a reseller's own plan for its clients."""

    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = _uuid_pk()
    reseller_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resellers.id", ondelete="CASCADE"), nullable=True)
    key: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    modules: Mapped[list[str]] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    user_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_price: Mapped[Decimal | None] = mapped_column(CurrencyAmount(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = _created()


class ResellerAdmin(Base):
    """A user who manages a reseller: creates its client companies and can open them as owner."""

    __tablename__ = "reseller_admins"

    reseller_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resellers.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = _created()



# ---------------------------------------------------------------------------
# v0.6.0: accounting engine
# ---------------------------------------------------------------------------
ACCOUNT_TYPES = ("asset", "liability", "equity", "income", "expense")
DETAIL_TYPES = {
    "asset": ("bank", "accounts_receivable", "other_current_asset", "fixed_asset", "other_asset"),
    "liability": ("credit_card", "accounts_payable", "other_current_liability", "long_term_liability"),
    "equity": ("equity",),
    "income": ("income", "other_income"),
    "expense": ("expense", "cost_of_goods_sold", "other_expense"),
}
DEBIT_NORMAL = ("asset", "expense")


class LedgerAccount(CompanyScoped, Base):
    """A chart-of-accounts entry. Categories and bank/card accounts each have one."""

    __tablename__ = "ledger_accounts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    type: Mapped[str] = mapped_column(String(12), nullable=False)
    detail_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Accounts the app relies on (accounts_payable, opening_balance_equity, ...). Can't be deleted.
    system_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = _created()


class JournalEntry(CompanyScoped, Base):
    """A balanced set of debits and credits. Most are posted automatically from a source record
    (source_type/source_id); manual journal entries have source_type 'journal'."""

    __tablename__ = "journal_entries"

    id: Mapped[uuid.UUID] = _uuid_pk()
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()

    lines: Mapped[list[JournalLine]] = relationship(
        back_populates="entry", order_by="JournalLine.line_no", cascade="all, delete-orphan", lazy="selectin"
    )


class JournalLine(CompanyScoped, Base):
    __tablename__ = "journal_lines"

    id: Mapped[uuid.UUID] = _uuid_pk()
    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ledger_accounts.id"), nullable=False)
    debit: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False, default=Decimal("0"))
    credit: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False, default=Decimal("0"))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"), nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), nullable=True)

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")
    account: Mapped[LedgerAccount] = relationship(lazy="select")


class ExpenseLine(CompanyScoped, Base):
    """One category split of an expense (QuickBooks "category details")."""

    __tablename__ = "expense_lines"

    id: Mapped[uuid.UUID] = _uuid_pk()
    expense_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("expense_categories.id"), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    amount: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False)
    billable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), nullable=True)


class Bill(CompanyScoped, Base):
    """Money owed to a vendor, paid later (Accounts Payable)."""

    __tablename__ = "bills"

    id: Mapped[uuid.UUID] = _uuid_pk()
    custom: Mapped[dict[str, Any] | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vendors.id"), nullable=False)
    bill_date: Mapped[date] = mapped_column(Date, nullable=False)
    terms: Mapped[str | None] = mapped_column(String(20), nullable=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    bill_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    total: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    vendor: Mapped[Vendor] = relationship(lazy="joined")
    lines: Mapped[list[BillLine]] = relationship(
        order_by="BillLine.line_no", cascade="all, delete-orphan", lazy="selectin")
    payments: Mapped[list[BillPayment]] = relationship(
        order_by="BillPayment.payment_date", cascade="all, delete-orphan", lazy="selectin")
    attachments: Mapped[list[BillAttachment]] = relationship(
        order_by="BillAttachment.uploaded_at", cascade="all, delete-orphan", lazy="selectin")


class BillLine(CompanyScoped, Base):
    __tablename__ = "bill_lines"

    id: Mapped[uuid.UUID] = _uuid_pk()
    bill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bills.id", ondelete="CASCADE"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("expense_categories.id"), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    amount: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False)
    billable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), nullable=True)


class BillPayment(CompanyScoped, Base):
    __tablename__ = "bill_payments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    bill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bills.id", ondelete="CASCADE"), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_accounts.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False)
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # The bank/card transaction this payment appears as (it then isn't posted a second time).
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()


class BillAttachment(CompanyScoped, Base):
    __tablename__ = "bill_attachments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    bill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bills.id", ondelete="CASCADE"), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = _created()


# ---------------------------------------------------------------- v0.7.0 sales
INVOICE_TERMS = ("due_on_receipt", "net_15", "net_30", "net_45", "net_60")
PAYMENT_METHODS_IN = ("ach", "check", "card", "cash", "wire", "other")


class Item(CompanyScoped, Base):
    """A product or service you sell (QuickBooks "Products and services")."""

    __tablename__ = "items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    custom: Mapped[dict[str, Any] | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(CurrencyAmount(), nullable=True)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("expense_categories.id"), nullable=False)  # income
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = _created()


class Invoice(CompanyScoped, Base):
    """Money a customer owes you (Accounts Receivable)."""

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = _uuid_pk()
    custom: Mapped[dict[str, Any] | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(30), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    terms: Mapped[str | None] = mapped_column(String(20), nullable=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    bill_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)  # printed on the invoice
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)  # internal
    total: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    is_void: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    voided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    customer: Mapped[Customer] = relationship(lazy="joined")
    lines: Mapped[list[InvoiceLine]] = relationship(
        order_by="InvoiceLine.line_no", cascade="all, delete-orphan", lazy="selectin")
    applications: Mapped[list[PaymentApplication]] = relationship(lazy="selectin", viewonly=True)


class InvoiceLine(CompanyScoped, Base):
    __tablename__ = "invoice_lines"

    id: Mapped[uuid.UUID] = _uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False, default=Decimal("1"))
    rate: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False)
    amount: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False)
    # Income category. Empty only for billable expenses, which post to "Billable Expense Income".
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expense_categories.id"), nullable=True)
    expense_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expense_lines.id"), nullable=True)
    bill_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bill_lines.id"), nullable=True)


class CustomerPayment(CompanyScoped, Base):
    """Money received from a customer, applied to one or more invoices (QuickBooks "Receive payment")."""

    __tablename__ = "customer_payments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_accounts.id"), nullable=False)  # deposit to
    amount: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False)
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # The bank deposit this payment appears as (it then isn't posted a second time).
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()

    customer: Mapped[Customer] = relationship(lazy="joined")
    applications: Mapped[list[PaymentApplication]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", back_populates="payment")


class PaymentApplication(CompanyScoped, Base):
    __tablename__ = "payment_applications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customer_payments.id", ondelete="CASCADE"),
                                                  nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(CurrencyAmount(), nullable=False)

    payment: Mapped[CustomerPayment] = relationship(back_populates="applications", lazy="joined")


class EmailSettings(CompanyScoped, Base):
    """Outgoing mail (SMTP) for sending invoices. One row per company. The password is encrypted."""

    __tablename__ = "email_settings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    smtp_host: Mapped[str] = mapped_column(String(255), nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    security: Mapped[str] = mapped_column(String(10), nullable=False, default="starttls")  # starttls | ssl | none
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_email: Mapped[str] = mapped_column(String(255), nullable=False)
    from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reply_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    copy_me: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    # v0.7.1: "smtp" (server + password) or "microsoft" (signed in to Microsoft 365, sends with Graph).
    provider: Mapped[str] = mapped_column(String(10), nullable=False, default="smtp", server_default="smtp")
    oauth_client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    oauth_refresh_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_account: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oauth_tenant: Mapped[str | None] = mapped_column(String(64), nullable=True)  # single-tenant apps (v0.8.0)
    updated_at: Mapped[datetime] = _updated()


class InvoiceEmail(CompanyScoped, Base):
    """Every attempt to email an invoice, sent or failed."""

    __tablename__ = "invoice_emails"

    id: Mapped[uuid.UUID] = _uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    sent_to: Mapped[str] = mapped_column(String(1000), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # sent | failed
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sent_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sent_at: Mapped[datetime] = _created()


class BankRule(CompanyScoped, Base):
    """A company's own rule for bank transactions (v0.10.0): when the description matches, suggest (or set and
    approve) the category, payee and customer. Rules are checked before the built-in suggestions."""

    __tablename__ = "bank_rules"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    match_type: Mapped[str] = mapped_column(String(12), nullable=False, default="contains", server_default="contains")
    match_text: Mapped[str] = mapped_column(String(200), nullable=False)
    direction: Mapped[str] = mapped_column(String(4), nullable=False, default="any", server_default="any")
    amount_min: Mapped[Decimal | None] = mapped_column(CurrencyAmount(), nullable=True)
    amount_max: Mapped[Decimal | None] = mapped_column(CurrencyAmount(), nullable=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_accounts.id"), nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expense_categories.id"), nullable=True)
    vendor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    auto_approve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    times_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = _created()
