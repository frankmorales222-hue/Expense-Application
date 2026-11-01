"""Pydantic request/response models.

Money is stored as Decimal and serialized to JSON as a number (never a string),
which avoids the string-concatenation bug in the original prototype.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

Money = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]

ExpenseStatus = Literal["pending", "approved", "paid", "rejected"]
# v0.10.0: payment methods and terms are the company's own lists (app/rules.py); checked against them on save.
PaymentMethod = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,20}$")]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


# ---------- Auth ----------
class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class UserOut(BaseModel):
    """The signed-in user and the company they're working in."""

    id: uuid.UUID
    email: str
    name: str
    # Permission name in the current company: admin (owner), approver (accountant/bookkeeper),
    # submitter (employee), viewer, or "none" when the user has no company yet.
    role: str
    company_role: str | None = None
    company_id: uuid.UUID | None = None
    company_name: str | None = None
    company_count: int = 0
    is_platform_admin: bool = False
    is_reseller_admin: bool = False
    # v0.8.0 plan of the open company
    plan: str | None = None
    plan_label: str | None = None
    modules: list[str] = []  # switched on
    module_data: list[str] = []  # switched off but holding records (shown read-only)
    user_limit: int | None = None
    seats_used: int = 0
    # v0.9.0 look: the person's own choice (None = company default), and what they get
    theme: str | None = None
    theme_effective: str = "classic"
    company_default_theme: str = "classic"
    # v0.10.0 custom roles: what this person may do in each area of the current company
    permissions: dict[str, str] = {}
    custom_role_name: str | None = None


Theme = Literal["classic", "executive", "dark"]


class ThemeIn(BaseModel):
    theme: Theme | None = None  # None: use the company's default


# ---------- Categories / vendors ----------
CategoryKind = Literal["expense", "income", "equity"]


class CategoryOut(ORM):
    id: uuid.UUID
    code: str
    name: str
    approval_threshold: Money | None
    is_active: bool
    sort_order: int
    kind: CategoryKind
    tax_line: str | None


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    approval_threshold: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)] | None = None
    sort_order: int | None = None
    kind: CategoryKind = "expense"
    tax_line: str | None = Field(default=None, max_length=100)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    approval_threshold: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)] | None = None
    clear_threshold: bool = False
    is_active: bool | None = None
    sort_order: int | None = None
    kind: CategoryKind | None = None
    tax_line: str | None = Field(default=None, max_length=100)


class VendorOut(ORM):
    id: uuid.UUID
    name: str


class VendorDetail(ORM):
    id: uuid.UUID
    name: str
    match_key: str | None
    default_category_id: uuid.UUID | None
    is_1099: bool


class VendorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    default_category_id: uuid.UUID | None = None
    clear_default_category: bool = False
    is_1099: bool | None = None
    match_key: str | None = Field(default=None, max_length=255)


# ---------- Expenses ----------
class LineIn(BaseModel):
    """One category split of an expense or bill (QuickBooks "category details")."""

    category_id: uuid.UUID
    description: str | None = Field(default=None, max_length=500)
    amount: PositiveMoney
    billable: bool = False
    customer_id: uuid.UUID | None = None

    @field_validator("description")
    @classmethod
    def blank_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


class LineOut(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    category_name: str
    description: str | None
    amount: Money
    billable: bool
    customer_id: uuid.UUID | None
    customer_name: str | None


class ExpenseIn(BaseModel):
    """Send `lines` (one or more category splits). The single category_id + amount form from earlier
    versions is still accepted and becomes one line."""
    custom: dict[str, Any] | None = None  # v0.10.0 custom fields (code -> value)

    expense_date: date
    vendor_name: str | None = Field(default=None, max_length=255)
    category_id: uuid.UUID | None = None
    description: str = Field(min_length=1, max_length=500)
    amount: PositiveMoney | None = None
    lines: list[LineIn] | None = Field(default=None, max_length=50)
    payment_account_id: uuid.UUID | None = None
    payment_method: PaymentMethod | None = None
    is_reimbursable: bool = False
    notes: str | None = Field(default=None, max_length=5000)
    invoice_number: str | None = Field(default=None, max_length=100)
    due_date: date | None = None

    @field_validator("description")
    @classmethod
    def strip_description(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Description is required")
        return v

    @field_validator("vendor_name", "notes", "invoice_number")
    @classmethod
    def blank_to_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    def resolved_lines(self) -> list[LineIn]:
        if self.lines:
            return self.lines
        if self.category_id is None or self.amount is None:
            raise ValueError("Add at least one line with a category and amount")
        return [LineIn(category_id=self.category_id, amount=self.amount)]


class StatusIn(BaseModel):
    status: ExpenseStatus
    note: str | None = Field(default=None, max_length=1000)
    # For "paid" on an expense someone paid personally: the account they were reimbursed from.
    payment_account_id: uuid.UUID | None = None


class ReceiptOut(ORM):
    id: uuid.UUID
    original_filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime


class AuditOut(BaseModel):
    id: uuid.UUID
    action: str
    user_name: str | None
    changes: dict[str, Any] | None
    created_at: datetime


class ExpenseListItem(BaseModel):
    id: uuid.UUID
    payment_account_id: uuid.UUID | None = None
    payment_account_name: str | None = None
    line_count: int = 1
    expense_date: date
    vendor_name: str | None
    category_id: uuid.UUID
    category_name: str
    description: str
    amount: Money
    currency: str
    payment_method: str | None
    is_reimbursable: bool
    status: str
    receipt_count: int
    created_at: datetime


class ExpenseDetail(ExpenseListItem):
    custom: dict[str, Any] | None = None
    lines: list[LineOut] = []
    notes: str | None
    invoice_number: str | None = None
    due_date: date | None = None
    bank_transaction_id: uuid.UUID | None = None
    approved_at: datetime | None
    paid_at: datetime | None
    receipts: list[ReceiptOut]
    history: list[AuditOut]
    allowed_transitions: list[str]


class ExpensePage(BaseModel):
    items: list[ExpenseListItem]
    total: int
    total_amount: Money
    page: int
    page_size: int


# ---------- Reports ----------
class NameAmount(BaseModel):
    key: str
    label: str
    amount: Money
    count: int


class SummaryOut(BaseModel):
    date_from: date | None
    date_to: date | None
    total_spent: Money
    expense_count: int
    pending_count: int
    pending_amount: Money
    reimbursable_owed: Money
    by_status: list[NameAmount]
    by_category: list[NameAmount]
    by_month: list[NameAmount]


class AppSettingsOut(BaseModel):
    version: str
    currency: str
    approval_required: bool
    date_format: str = "MM/DD/YYYY"
    number_format: str = "1,234.56"
    currency_symbol: str | None = None
    auto_approve_confidence: int = 90
    default_approval_threshold: Money
    max_receipt_mb: int
    desktop_mode: bool
    receipt_storage: str
    database: str


# ---------- Phase 1: banking ----------
AccountKind = Literal["checking", "savings", "credit_card", "cash", "other"]
ReviewStatus = Literal["unreviewed", "approved", "excluded"]
SignedMoney = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]


def _strip_required(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("Required")
    return v


class CompanyOut(ORM):
    id: uuid.UUID
    name: str
    legal_name: str | None
    base_currency: str
    fiscal_year_start_month: int
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    invoice_footer: str | None = None
    has_logo: bool = False
    logo_version: int = 0


class BrandingOut(BaseModel):
    """Shown before sign-in: name and logo only."""

    name: str
    has_logo: bool
    logo_version: int
    company_id: uuid.UUID | None = None


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    # Invoice details (v0.7.0). Leave out to keep what's saved.
    address: str | None = Field(default=None, max_length=1000)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    website: str | None = Field(default=None, max_length=255)
    invoice_footer: str | None = Field(default=None, max_length=2000)

    @field_validator("legal_name", "address", "phone", "email", "website", "invoice_footer")
    @classmethod
    def blank_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

    _name = field_validator("name")(classmethod(lambda cls, v: _strip_required(v)))


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: AccountKind
    institution: str | None = Field(default=None, max_length=120)
    last4: str | None = Field(default=None, pattern=r"^[0-9]{4}$")
    opening_balance: SignedMoney = Decimal("0")
    opening_date: date | None = None
    is_active: bool = True

    _name = field_validator("name")(classmethod(lambda cls, v: _strip_required(v)))

    @field_validator("institution", "last4", mode="before")
    @classmethod
    def blank_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v


class AccountOut(ORM):
    id: uuid.UUID
    name: str
    kind: AccountKind
    institution: str | None
    last4: str | None
    currency: str
    opening_balance: Money
    opening_date: date | None
    is_active: bool
    balance: Money = Decimal("0")
    unreviewed_count: int = 0
    transaction_count: int = 0
    has_csv_profile: bool = False


class CustomerIn(BaseModel):
    custom: dict[str, Any] | None = None  # v0.10.0 custom fields (code -> value)
    name: str = Field(min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=5000)
    is_active: bool = True
    cc_emails: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=50)
    billing_address: str | None = Field(default=None, max_length=1000)
    default_terms: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,20}$")] | None = None

    _name = field_validator("name")(classmethod(lambda cls, v: _strip_required(v)))

    @field_validator("email", "notes", "cc_emails", "phone", "billing_address")
    @classmethod
    def blank_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

    @field_validator("email")
    @classmethod
    def valid_email(cls, v: str | None) -> str | None:
        if v and not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("cc_emails")
    @classmethod
    def valid_cc(cls, v: str | None) -> str | None:
        if not v:
            return None
        parts = [p.strip() for p in v.replace(";", ",").split(",") if p.strip()]
        bad = [p for p in parts if not EMAIL_RE.match(p)]
        if bad:
            raise ValueError(f"Not a valid email address: {bad[0]}")
        return ", ".join(parts) or None


class CustomerOut(ORM):
    custom: dict[str, Any] | None = None
    id: uuid.UUID
    name: str
    email: str | None
    notes: str | None
    is_active: bool
    cc_emails: str | None = None
    phone: str | None = None
    billing_address: str | None = None
    default_terms: str | None = None


class CsvMapping(BaseModel):
    date_column: int | None = None
    description_column: int | None = None
    amount_column: int | None = None
    debit_column: int | None = None
    credit_column: int | None = None
    invert_amounts: bool = False
    date_format: str | None = Field(default=None, max_length=20)


class PreviewRow(BaseModel):
    line: int
    txn_date: date | None
    amount: Money | None
    description: str
    error: str | None


class ImportPreviewOut(BaseModel):
    source: str
    filename: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    date_from: date | None
    date_to: date | None
    money_in: Money
    money_out: Money
    rows: list[PreviewRow]
    headers: list[str] = []
    sample: list[list[str]] = []
    mapping: CsvMapping | None = None
    problems: list[str] = []
    file_account_last4: str | None = None
    previously_imported: bool = False


class ImportBatchOut(ORM):
    id: uuid.UUID
    account_id: uuid.UUID
    account_name: str = ""
    source: str
    filename: str
    rows_total: int
    rows_imported: int
    rows_duplicate: int
    rows_invalid: int
    rows_flagged: int
    status: str
    created_at: datetime
    approved_count: int = 0


class PeerOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account_name: str
    txn_date: date
    amount: Money
    description: str
    review_status: str


class TransactionOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account_name: str
    bill_id: uuid.UUID | None = None  # this charge is the payment of a bill
    customer_payment_id: uuid.UUID | None = None  # this deposit is a payment received on invoices
    invoice_ids: list[uuid.UUID] = []  # ...applied to these invoices
    account_kind: str
    txn_date: date
    amount: Money
    description: str
    normalized: str
    memo: str | None
    source: str
    review_status: ReviewStatus
    category_id: uuid.UUID | None
    category_name: str | None
    allocation_account_id: uuid.UUID | None = None
    allocation_account_name: str | None = None
    vendor_id: uuid.UUID | None
    vendor_name: str | None
    customer_id: uuid.UUID | None
    customer_name: str | None
    suggested_category_id: uuid.UUID | None
    suggested_category_name: str | None
    suggested_vendor_name: str | None
    confidence: int
    suggestion_reason: str | None
    is_transfer: bool
    transfer_peer: PeerOut | None
    duplicate_of: PeerOut | None
    expense_id: uuid.UUID | None
    receipt_status: Literal["attached", "missing", "not_needed"]
    approved_at: datetime | None
    reconciled: bool = False
    reconciliation_id: uuid.UUID | None = None


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    page_size: int
    counts: dict[str, int]
    total_in: Money
    total_out: Money


# ---------- v0.12.0: statement reconciliation and accountant review ----------
class ReconciliationStartIn(BaseModel):
    account_id: uuid.UUID
    statement_date: date
    ending_balance: Money
    notes: str | None = Field(default=None, max_length=1000)


class ReconciliationSelectionIn(BaseModel):
    transaction_ids: list[uuid.UUID] = Field(max_length=5000)


class ReconciliationSummary(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account_name: str
    account_kind: str
    statement_date: date
    beginning_balance: Money
    ending_balance: Money
    cleared_balance: Money
    difference: Money
    status: Literal["draft", "completed"]
    transaction_count: int
    statement_filename: str | None = None
    statement_size_bytes: int | None = None
    notes: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    completed_by_name: str | None = None


class ReconciliationOut(ReconciliationSummary):
    transactions: list[TransactionOut]


class AuditLogOut(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    action: str
    user_id: uuid.UUID | None
    user_name: str | None
    user_email: str | None
    changes: dict[str, Any] | None
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogOut]
    total: int
    page: int
    page_size: int


class TransactionUpdate(BaseModel):
    """Only fields that are sent are changed; send null to clear."""

    category_id: uuid.UUID | None = None
    vendor_name: str | None = Field(default=None, max_length=255)
    customer_id: uuid.UUID | None = None
    memo: str | None = Field(default=None, max_length=5000)
    expense_id: uuid.UUID | None = None


class ManualTransactionIn(BaseModel):
    account_id: uuid.UUID
    txn_date: date
    amount: SignedMoney
    description: str = Field(min_length=1, max_length=500)
    category_id: uuid.UUID | None = None
    vendor_name: str | None = Field(default=None, max_length=255)
    customer_id: uuid.UUID | None = None
    memo: str | None = Field(default=None, max_length=5000)

    _desc = field_validator("description")(classmethod(lambda cls, v: _strip_required(v)))

    @field_validator("amount")
    @classmethod
    def nonzero(cls, v: Decimal) -> Decimal:
        if v == 0:
            raise ValueError("Amount can't be zero")
        return v


class BulkIds(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class ApproveConfidentIn(BaseModel):
    account_id: uuid.UUID | None = None
    min_confidence: int = Field(default=90, ge=50, le=100)


class BulkResult(BaseModel):
    approved: int
    skipped: int
    messages: list[str] = []


class LinkTransferIn(BaseModel):
    peer_id: uuid.UUID


class CandidatesOut(BaseModel):
    transfers: list[PeerOut]
    expenses: list[ExpenseListItem]



# ---------- v0.4.0: bill import ----------
class BillCapabilities(BaseModel):
    ocr: bool
    ai_mode: str
    ai_requested: str
    ai_key_set: bool
    ai_model: str
    formats: list[str]


class BankMatch(BaseModel):
    id: uuid.UUID
    account_name: str
    txn_date: date
    description: str


class BillExtractOut(BaseModel):
    filename: str
    method: Literal["text", "ocr", "ai"]
    vendor_name: str | None
    expense_date: date | None
    due_date: date | None
    amount: Money | None
    invoice_number: str | None
    description: str | None
    currency: str
    category_id: uuid.UUID | None
    category_reason: str
    confidence: dict[str, float]
    sources: dict[str, str]
    confident: bool
    known_vendor: bool
    warnings: list[str]
    attachments: list[str]
    text_preview: str
    duplicates: list[ExpenseListItem]
    bank_match: BankMatch | None



# ---------- v0.5.0: multi-company ----------
CompanyRole = Literal["owner", "accountant", "bookkeeper", "employee", "viewer"]


class CompanyListItem(BaseModel):
    id: uuid.UUID
    name: str
    role: CompanyRole
    via_reseller: bool
    reseller_id: uuid.UUID | None
    reseller_name: str | None
    has_logo: bool
    logo_version: int
    is_current: bool


class CompanyCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    reseller_id: uuid.UUID | None = None
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    plan: str = Field(default="plus", min_length=1, max_length=30)  # v0.8.0; v0.10.0 any plan key

    _name = field_validator("name")(classmethod(lambda cls, v: _strip_required(v)))


class MemberOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    role: CompanyRole
    via_reseller: bool
    is_you: bool
    is_active: bool
    custom_role_id: uuid.UUID | None = None  # v0.10.0
    custom_role_name: str | None = None


class MemberIn(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str | None = Field(default=None, max_length=255)
    role: CompanyRole
    custom_role_id: uuid.UUID | None = None  # v0.10.0: one of the company's own roles (its base role wins)


class MemberRoleIn(BaseModel):
    role: CompanyRole
    custom_role_id: uuid.UUID | None = None


class MemberAdded(BaseModel):
    member: MemberOut
    temporary_password: str | None = None


class ResellerAdminOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str


class ResellerOut(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    company_count: int
    admins: list[ResellerAdminOut]


class ResellerIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_active: bool = True

    _name = field_validator("name")(classmethod(lambda cls, v: _strip_required(v)))


class ResellerAdminIn(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str | None = Field(default=None, max_length=255)


class ResellerAdminAdded(BaseModel):
    admin: ResellerAdminOut
    temporary_password: str | None = None


# ---------- v0.6.0: bills ----------
BillTerms = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,20}$")]
BillStatus = Literal["open", "partial", "paid", "overdue"]


class BillIn(BaseModel):
    custom: dict[str, Any] | None = None  # v0.10.0 custom fields (code -> value)
    vendor_name: str = Field(min_length=1, max_length=255)
    bill_date: date
    terms: BillTerms | None = None
    due_date: date | None = None  # defaults from terms (or the bill date)
    bill_number: str | None = Field(default=None, max_length=100)
    memo: str | None = Field(default=None, max_length=5000)
    lines: list[LineIn] = Field(min_length=1, max_length=50)

    _vendor = field_validator("vendor_name")(classmethod(lambda cls, v: _strip_required(v)))

    @field_validator("bill_number", "memo")
    @classmethod
    def blank_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


class BillPaymentOut(BaseModel):
    id: uuid.UUID
    payment_date: date
    account_id: uuid.UUID
    account_name: str
    amount: Money
    memo: str | None
    transaction_id: uuid.UUID | None


class BillAttachmentOut(ORM):
    id: uuid.UUID
    original_filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime


class BillListItem(BaseModel):
    id: uuid.UUID
    vendor_id: uuid.UUID
    vendor_name: str
    bill_date: date
    due_date: date
    terms: str | None
    bill_number: str | None
    total: Money
    paid: Money
    balance: Money
    status: BillStatus
    attachment_count: int


class BillDetail(BillListItem):
    custom: dict[str, Any] | None = None
    memo: str | None
    lines: list[LineOut]
    payments: list[BillPaymentOut]
    attachments: list[BillAttachmentOut]


class BillPage(BaseModel):
    items: list[BillListItem]
    total_open: Money
    total_overdue: Money


class BillPaymentIn(BaseModel):
    payment_date: date
    account_id: uuid.UUID
    amount: PositiveMoney
    memo: str | None = Field(default=None, max_length=500)
    transaction_id: uuid.UUID | None = None


# ---------- v0.6.0: ledger ----------
AccountType = Literal["asset", "liability", "equity", "income", "expense"]


class LedgerAccountOut(BaseModel):
    id: uuid.UUID
    code: str | None
    name: str
    type: AccountType
    detail_type: str
    system_key: str | None
    description: str | None
    is_active: bool
    balance: Money
    linked_to: Literal["category", "bank", "system", "none"]
    category_id: uuid.UUID | None = None
    bank_account_id: uuid.UUID | None = None


class LedgerAccountIn(BaseModel):
    """Accounts made here are for journal entries and future features (loans, equipment, owner's capital).
    Expense and income accounts are created through Settings > Categories so they can be chosen on
    expenses and in Banking; bank and card accounts through Accounts."""

    code: str | None = Field(default=None, max_length=20)
    name: str = Field(min_length=1, max_length=150)
    type: AccountType
    detail_type: str = Field(min_length=1, max_length=30)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool = True

    _name = field_validator("name")(classmethod(lambda cls, v: _strip_required(v)))


class RegisterLine(BaseModel):
    entry_id: uuid.UUID
    entry_date: date
    source_type: str
    source_id: uuid.UUID | None
    number: str | None
    memo: str | None
    description: str | None
    other_accounts: str
    debit: Money
    credit: Money
    balance: Money


class RegisterOut(BaseModel):
    account: LedgerAccountOut
    lines: list[RegisterLine]
    opening_balance: Money


class JournalLineIn(BaseModel):
    account_id: uuid.UUID
    debit: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)] = Decimal("0")
    credit: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)] = Decimal("0")
    description: str | None = Field(default=None, max_length=500)
    customer_id: uuid.UUID | None = None
    vendor_name: str | None = Field(default=None, max_length=255)


class JournalEntryIn(BaseModel):
    entry_date: date
    number: str | None = Field(default=None, max_length=30)
    memo: str | None = Field(default=None, max_length=500)
    lines: list[JournalLineIn] = Field(min_length=2, max_length=100)


class JournalLineOut(BaseModel):
    account_id: uuid.UUID
    account_name: str
    debit: Money
    credit: Money
    description: str | None
    customer_id: uuid.UUID | None
    vendor_name: str | None


class JournalEntryOut(BaseModel):
    id: uuid.UUID
    entry_date: date
    source_type: str
    source_id: uuid.UUID | None
    number: str | None
    memo: str | None
    total: Money
    lines: list[JournalLineOut]
    editable: bool


class ReportRow(BaseModel):
    account_id: uuid.UUID
    name: str
    code: str | None
    amount: Money


class ReportSection(BaseModel):
    key: str
    label: str
    rows: list[ReportRow]
    total: Money


class ProfitLossOut(BaseModel):
    date_from: date
    date_to: date
    sections: list[ReportSection]
    gross_profit: Money
    net_operating_income: Money
    net_income: Money


class BalanceSheetOut(BaseModel):
    as_of: date
    sections: list[ReportSection]
    total_assets: Money
    total_liabilities_and_equity: Money
    balanced: bool


class TrialBalanceRow(BaseModel):
    account_id: uuid.UUID
    name: str
    code: str | None
    type: str
    debit: Money
    credit: Money


class TrialBalanceOut(BaseModel):
    as_of: date
    rows: list[TrialBalanceRow]
    total_debit: Money
    total_credit: Money


class ClosingDateIn(BaseModel):
    closing_date: date | None = None


class BooksStatusOut(BaseModel):
    closing_date: date | None
    total_debit: Money
    total_credit: Money
    balanced: bool
    unbalanced_entries: int
    payment_account_not_set: int


# ---------- v0.11.0 owner funds ----------
OwnerFundsAction = Literal["loan", "repayment", "opening_balance"]


class OwnerFundsIn(BaseModel):
    action: OwnerFundsAction
    entry_date: date
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    account_id: uuid.UUID | None = None
    transaction_id: uuid.UUID | None = None
    memo: str | None = Field(default=None, max_length=500)


class OwnerFundsActivity(BaseModel):
    entry_id: uuid.UUID
    entry_date: date
    account: Literal["loan", "reimbursement"]
    source_type: str
    source_id: uuid.UUID | None
    description: str
    change: Money


class OwnerFundsOut(BaseModel):
    due_to_owner_account_id: uuid.UUID
    reimbursements_account_id: uuid.UUID
    loan_balance: Money
    reimbursement_balance: Money
    total_owed: Money
    activity: list[OwnerFundsActivity]


# ---------- v0.7.0: sales ----------
Terms = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,20}$")]
InvoiceStatus = Literal["not_sent", "sent", "partial", "paid", "overdue", "void"]
PaymentMethodIn = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,20}$")]


def _blank(v: str | None) -> str | None:
    return (v or "").strip() or None


class ItemIn(BaseModel):
    custom: dict[str, Any] | None = None  # v0.10.0 custom fields (code -> value)
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    rate: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)] | None = None
    category_id: uuid.UUID
    is_active: bool = True

    _name = field_validator("name")(classmethod(lambda cls, v: _strip_required(v)))
    _desc = field_validator("description")(classmethod(lambda cls, v: _blank(v)))


class ItemOut(ORM):
    custom: dict[str, Any] | None = None
    id: uuid.UUID
    name: str
    description: str | None
    rate: Money | None
    category_id: uuid.UUID
    category_name: str = ""
    is_active: bool


class InvoiceLineIn(BaseModel):
    service_date: date | None = None
    item_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=1000)
    quantity: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)] = Decimal("1")
    rate: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    category_id: uuid.UUID | None = None
    expense_line_id: uuid.UUID | None = None
    bill_line_id: uuid.UUID | None = None

    _desc = field_validator("description")(classmethod(lambda cls, v: _blank(v)))


class InvoiceLineOut(BaseModel):
    id: uuid.UUID
    service_date: date | None
    item_id: uuid.UUID | None
    item_name: str | None
    description: str | None
    quantity: Money
    rate: Money
    amount: Money
    category_id: uuid.UUID | None
    category_name: str | None
    expense_line_id: uuid.UUID | None
    bill_line_id: uuid.UUID | None


class InvoiceIn(BaseModel):
    custom: dict[str, Any] | None = None  # v0.10.0 custom fields (code -> value)
    customer_id: uuid.UUID
    invoice_number: str | None = Field(default=None, max_length=30)  # next number when left out
    invoice_date: date
    terms: Terms | None = None
    due_date: date | None = None  # defaults from terms
    bill_email: str | None = Field(default=None, max_length=255)
    message: str | None = Field(default=None, max_length=4000)
    memo: str | None = Field(default=None, max_length=4000)
    lines: list[InvoiceLineIn] = Field(min_length=1, max_length=100)

    _blanks = field_validator("invoice_number", "bill_email", "message", "memo")(
        classmethod(lambda cls, v: _blank(v)))

    @field_validator("bill_email")
    @classmethod
    def valid_email(cls, v: str | None) -> str | None:
        if v and not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v


class InvoiceListItem(BaseModel):
    id: uuid.UUID
    invoice_number: str
    customer_id: uuid.UUID
    customer_name: str
    invoice_date: date
    due_date: date
    total: Money
    paid: Money
    balance: Money
    status: InvoiceStatus
    sent_at: datetime | None


class InvoicePaymentRef(BaseModel):
    payment_id: uuid.UUID
    payment_date: date
    amount: Money  # applied to this invoice
    payment_total: Money
    account_name: str
    method: str | None
    reference: str | None
    transaction_id: uuid.UUID | None


class InvoiceEmailOut(ORM):
    id: uuid.UUID
    sent_to: str
    subject: str
    status: str
    error: str | None
    sent_at: datetime


class InvoiceDetail(InvoiceListItem):
    custom: dict[str, Any] | None = None
    terms: str | None
    bill_email: str | None
    customer_email: str | None
    customer_cc: str | None
    message: str | None
    memo: str | None
    lines: list[InvoiceLineOut]
    payments: list[InvoicePaymentRef]
    emails: list[InvoiceEmailOut]
    voided_at: datetime | None


class InvoicePage(BaseModel):
    items: list[InvoiceListItem]
    total_open: Money
    total_overdue: Money
    paid_last_30: Money
    count_open: int
    count_overdue: int


class BillableOut(BaseModel):
    source: Literal["expense", "bill"]
    line_id: uuid.UUID
    record_id: uuid.UUID
    date: date
    vendor_name: str | None
    description: str | None
    category_name: str
    amount: Money


class ApplicationIn(BaseModel):
    invoice_id: uuid.UUID
    amount: PositiveMoney


class PaymentIn(BaseModel):
    customer_id: uuid.UUID
    payment_date: date
    account_id: uuid.UUID
    amount: PositiveMoney
    method: PaymentMethodIn | None = None
    reference: str | None = Field(default=None, max_length=100)
    memo: str | None = Field(default=None, max_length=500)
    transaction_id: uuid.UUID | None = None
    applications: list[ApplicationIn] = Field(min_length=1, max_length=200)

    _blanks = field_validator("reference", "memo")(classmethod(lambda cls, v: _blank(v)))


class ApplicationOut(BaseModel):
    invoice_id: uuid.UUID
    invoice_number: str
    amount: Money


class PaymentOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str
    payment_date: date
    account_id: uuid.UUID
    account_name: str
    amount: Money
    method: str | None
    reference: str | None
    memo: str | None
    transaction_id: uuid.UUID | None
    applications: list[ApplicationOut]


class CustomerListItem(CustomerOut):
    open_balance: Money = Decimal("0")
    overdue_balance: Money = Decimal("0")


class CustomerDetail(CustomerListItem):
    invoice_count: int
    paid_invoice_count: int
    avg_days_to_pay: float | None
    on_time_percent: float | None
    unbilled_amount: Money
    unbilled_count: int
    invoices: list[InvoiceListItem]
    payments: list[PaymentOut]


class EmailSettingsIn(BaseModel):
    smtp_host: str = Field(min_length=1, max_length=255)
    smtp_port: int = Field(ge=1, le=65535)
    security: Literal["starttls", "ssl", "none"] = "starttls"
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=500)  # null keeps the saved one
    from_email: str = Field(min_length=3, max_length=255)
    from_name: str | None = Field(default=None, max_length=255)
    reply_to: str | None = Field(default=None, max_length=255)
    copy_me: bool = False

    _host = field_validator("smtp_host")(classmethod(lambda cls, v: _strip_required(v)))
    _blanks = field_validator("username", "from_name", "reply_to")(classmethod(lambda cls, v: _blank(v)))

    @field_validator("from_email", "reply_to")
    @classmethod
    def valid_email(cls, v: str | None) -> str | None:
        if v and not EMAIL_RE.match(v.strip()):
            raise ValueError("Enter a valid email address")
        return v.strip() if v else v


class EmailSettingsOut(BaseModel):
    configured: bool
    provider: Literal["smtp", "microsoft"] = "smtp"
    oauth_account: str | None = None
    ms_client_id: str | None = None  # saved for this company (empty: the .env MS_CLIENT_ID is used)
    ms_client_id_in_env: bool = False
    ms_tenant: str | None = None  # saved for this company (single-tenant app)
    microsoft_ready: bool = False  # an app (client) ID is available, so "Connect Microsoft 365" can work
    smtp_host: str | None = None
    smtp_port: int | None = None
    security: str | None = None
    username: str | None = None
    has_password: bool = False
    from_email: str | None = None
    from_name: str | None = None
    reply_to: str | None = None
    copy_me: bool = False


class TestEmailIn(BaseModel):
    to: str = Field(min_length=3, max_length=255)

    @field_validator("to")
    @classmethod
    def valid_email(cls, v: str) -> str:
        if not EMAIL_RE.match(v.strip()):
            raise ValueError("Enter a valid email address")
        return v.strip()


class SendInvoiceIn(BaseModel):
    to: list[str] = Field(min_length=1, max_length=10)
    cc: list[str] = Field(default_factory=list, max_length=10)
    subject: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("to", "cc")
    @classmethod
    def valid_emails(cls, v: list[str]) -> list[str]:
        out = [a.strip() for a in v if a.strip()]
        bad = [a for a in out if not EMAIL_RE.match(a)]
        if bad:
            raise ValueError(f"Not a valid email address: {bad[0]}")
        return out


class EmailDraftOut(BaseModel):
    to: list[str]
    cc: list[str]
    subject: str
    body: str
    configured: bool
    from_label: str | None


class AgingRow(BaseModel):
    customer_id: uuid.UUID
    customer_name: str
    current: Money
    d1_30: Money
    d31_60: Money
    d61_90: Money
    d91_plus: Money
    total: Money


class AgingOut(BaseModel):
    as_of: date
    rows: list[AgingRow]
    totals: AgingRow


class SalesByCustomerRow(BaseModel):
    customer_id: uuid.UUID | None
    customer_name: str
    amount: Money


class SalesByCustomerOut(BaseModel):
    date_from: date
    date_to: date
    rows: list[SalesByCustomerRow]
    total: Money


class SalesSummaryOut(BaseModel):
    open_total: Money
    open_count: int
    overdue_total: Money
    overdue_count: int
    not_sent_count: int
    paid_last_30: Money
    deposits_to_match: int


class MicrosoftStartIn(BaseModel):
    client_id: str | None = Field(default=None, max_length=64)  # leave out to use the saved or .env one
    # Directory (tenant) ID or domain. Required for a single-tenant app; empty: the saved one or MS_TENANT.
    tenant_id: str | None = Field(default=None, max_length=64)

    @field_validator("tenant_id")
    @classmethod
    def tenant(cls, v: str | None) -> str | None:
        v = (v or "").strip().lower()
        if not v:
            return None
        if v in ("organizations", "common"):
            return v
        guid = re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", v)
        domain = re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$", v)
        if not (guid or domain):
            raise ValueError("The Directory (tenant) ID looks like 00000000-0000-0000-0000-000000000000 "
                             "(or use your domain, like yourcompany.onmicrosoft.com)")
        return v

    @field_validator("client_id")
    @classmethod
    def guid(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if not v:
            return None
        if not re.match(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", v):
            raise ValueError("The Application (client) ID looks like 00000000-0000-0000-0000-000000000000")
        return v.lower()


class MicrosoftStartOut(BaseModel):
    flow_id: str
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int


class MicrosoftPollIn(BaseModel):
    flow_id: str = Field(min_length=8, max_length=64)


class MicrosoftPollOut(BaseModel):
    status: Literal["pending", "connected"]
    settings: EmailSettingsOut | None = None


# ---------- v0.8.0: plans and modules ----------
class ModuleInfo(BaseModel):
    key: str
    label: str
    description: str


class PlanInfo(BaseModel):
    id: uuid.UUID | None = None
    key: str
    label: str
    modules: list[str]
    user_limit: int | None
    description: str | None = None
    monthly_price: Money | None = None
    is_active: bool = True
    sort_order: int = 0
    reseller_id: uuid.UUID | None = None
    reseller_name: str | None = None
    editable: bool = False


class PlanEditIn(BaseModel):
    key: str = Field(default="", pattern=r"^[a-z0-9_]{0,30}$")  # set when adding; can't change later
    label: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    modules: list[str] = []
    user_limit: int | None = Field(default=None, ge=1, le=10000)
    monthly_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=1000)
    reseller_id: uuid.UUID | None = None


class PlansCatalog(BaseModel):
    modules: list[ModuleInfo]
    plans: list[PlanInfo]


class CompanyPlanOut(BaseModel):
    id: uuid.UUID
    name: str
    reseller_name: str | None
    is_active: bool
    plan: str | None
    plan_label: str
    modules: list[str]
    user_limit: int | None
    seats_used: int
    created_at: datetime
    default_theme: str = "classic"  # v0.9.0


class CompanyThemeIn(BaseModel):
    default_theme: Theme


class CompanyPlanIn(BaseModel):
    plan: str = Field(min_length=1, max_length=30)  # a plan key or "custom"
    modules: list[str] | None = None  # needed for "custom"; ignored otherwise unless given
    user_limit: int | None = Field(default=None, ge=1, le=10000)  # None: unlimited


# ---------- v0.9.0: dashboard overview ----------
class DashAccount(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    institution: str | None
    last4: str | None
    balance: Money
    unreviewed: int


class DashPoint(BaseModel):
    date: date
    balance: Money


class DashMonth(BaseModel):
    key: str  # YYYY-MM
    label: str  # "Oct"
    income: Money
    expenses: Money


class DashEvent(BaseModel):
    kind: Literal["invoice", "bill"]
    id: uuid.UUID
    date: date  # due date
    name: str  # customer or vendor
    reference: str | None
    amount: Money  # + money expected in, - money going out
    days_late: int = 0


class DashInvoice(BaseModel):
    id: uuid.UUID
    invoice_number: str
    customer_name: str
    due_date: date
    total: Money
    balance: Money
    status: str
    days_late: int = 0


class DashPnlRow(BaseModel):
    name: str
    this_month: Money
    last_month: Money


class DashPnl(BaseModel):
    this_from: date
    this_to: date
    last_from: date
    last_to: date
    income_this: Money
    income_last: Money
    expense_rows: list[DashPnlRow]
    expenses_this: Money
    expenses_last: Money
    net_this: Money
    net_last: Money


class DashboardOut(BaseModel):
    as_of: date
    cash_total: Money
    cash_month_start: Money  # cash at the end of last month
    has_bank_accounts: bool
    accounts: list[DashAccount]
    income_ytd: Money
    expenses_ytd: Money
    profit_ytd: Money
    profit_prior_ytd: Money  # same dates last year
    fiscal_year_start: date
    receivable_total: Money
    receivable_open_count: int
    overdue_total: Money
    overdue_count: int
    paid_last_30: Money
    payable_total: Money
    payable_count: int
    payable_due_14: Money
    payable_overdue: Money
    owner_loan_balance: Money = Decimal("0")
    owner_reimbursements: Money = Decimal("0")
    owner_total_owed: Money = Decimal("0")
    review_count: int
    months: list[DashMonth]
    history: list[DashPoint]  # actual cash, last 30 days
    forecast: list[DashPoint]  # expected cash, today and the next 30 days
    forecast_low: DashPoint
    coming_up: list[DashEvent]
    invoices: list[DashInvoice]
    pnl: DashPnl
    forecast_days: int = 30
    coming_up_days: int = 14
