"""Pydantic request/response models.

Money is stored as Decimal and serialized to JSON as a number (never a string),
which avoids the string-concatenation bug in the original prototype.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

Money = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]

ExpenseStatus = Literal["pending", "approved", "paid", "rejected"]
PaymentMethod = Literal["business_card", "business_bank", "personal_card", "cash", "other"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth ----------
class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class UserOut(ORM):
    id: uuid.UUID
    email: str
    name: str
    role: str


# ---------- Categories / vendors ----------
class CategoryOut(ORM):
    id: uuid.UUID
    code: str
    name: str
    approval_threshold: Money | None
    is_active: bool
    sort_order: int


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    approval_threshold: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)] | None = None
    sort_order: int | None = None

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


class VendorOut(ORM):
    id: uuid.UUID
    name: str


# ---------- Expenses ----------
class ExpenseIn(BaseModel):
    expense_date: date
    vendor_name: str | None = Field(default=None, max_length=255)
    category_id: uuid.UUID
    description: str = Field(min_length=1, max_length=500)
    amount: PositiveMoney
    payment_method: PaymentMethod | None = None
    is_reimbursable: bool = False
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("description")
    @classmethod
    def strip_description(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Description is required")
        return v

    @field_validator("vendor_name", "notes")
    @classmethod
    def blank_to_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class StatusIn(BaseModel):
    status: ExpenseStatus
    note: str | None = Field(default=None, max_length=1000)


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
    notes: str | None
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
    default_approval_threshold: Money
    max_receipt_mb: int
