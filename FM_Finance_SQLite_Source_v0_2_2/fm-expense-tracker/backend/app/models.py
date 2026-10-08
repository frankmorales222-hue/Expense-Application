"""SQLAlchemy models. The schema itself is created by Alembic migrations."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Integer, JSON, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .types import CurrencyAmount, UTCDateTime

EXPENSE_STATUSES = ("pending", "approved", "paid", "rejected")
PAYMENT_METHODS = ("business_card", "business_bank", "personal_card", "cash", "other")
USER_ROLES = ("admin", "approver", "submitter")


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
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    approval_threshold: Mapped[Decimal | None] = mapped_column(CurrencyAmount(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = _created()


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = _uuid_pk()
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
    submitted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    category: Mapped[ExpenseCategory] = relationship(lazy="joined")
    vendor: Mapped[Vendor | None] = relationship(lazy="joined")
    receipts: Mapped[list[Receipt]] = relationship(
        back_populates="expense", order_by="Receipt.uploaded_at", cascade="all, delete-orphan"
    )


class Receipt(Base):
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


class AuditLog(Base):
    __tablename__ = "audit_log"

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
