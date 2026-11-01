"""Initial schema: users, categories, vendors, expenses, receipts, audit log, bank transactions.

Revision ID: 0001
Revises:
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None



def _id() -> sa.Column:
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "users",
        _id(),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(30), nullable=False, server_default="admin"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("role IN ('admin','approver','submitter')", name="ck_users_role"),
    )

    op.create_table(
        "expense_categories",
        _id(),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("approval_threshold", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("approval_threshold IS NULL OR approval_threshold >= 0", name="ck_categories_threshold"),
    )

    op.create_table(
        "vendors",
        _id(),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        _ts("created_at"),
    )
    op.create_index("ix_vendors_name_lower", "vendors", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "expenses",
        _id(),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("vendor_id", sa.Uuid(), sa.ForeignKey("vendors.id"), nullable=True),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("expense_categories.id"), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("payment_method", sa.String(30), nullable=True),
        sa.Column("is_reimbursable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(20), nullable=False, server_default="approved"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("submitted_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        sa.CheckConstraint("status IN ('pending','approved','paid','rejected')", name="ck_expenses_status"),
        sa.CheckConstraint(
            "payment_method IS NULL OR payment_method IN "
            "('business_card','business_bank','personal_card','cash','other')",
            name="ck_expenses_payment_method",
        ),
    )
    op.create_index("ix_expenses_expense_date", "expenses", ["expense_date"])
    op.create_index("ix_expenses_category_id", "expenses", ["category_id"])
    op.create_index("ix_expenses_status", "expenses", ["status"])
    op.create_index("ix_expenses_vendor_id", "expenses", ["vendor_id"])
    op.create_index("ix_expenses_deleted_date", "expenses", ["is_deleted", "expense_date"])

    op.create_table(
        "receipts",
        _id(),
        sa.Column("expense_id", sa.Uuid(), sa.ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        _ts("uploaded_at"),
    )
    op.create_index("ix_receipts_expense_id", "receipts", ["expense_id"])

    op.create_table(
        "audit_log",
        _id(),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("changes", postgresql.JSONB(), nullable=True),
        _ts("created_at"),
    )
    op.create_index("ix_audit_entity", "audit_log", ["entity_type", "entity_id", "created_at"])

    op.create_table(
        "bank_transactions",
        _id(),
        sa.Column("txn_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True, unique=True),
        sa.Column("matched_expense_id", sa.Uuid(), sa.ForeignKey("expenses.id"), nullable=True),
        _ts("imported_at"),
        sa.CheckConstraint("direction IN ('debit','credit')", name="ck_bank_transactions_direction"),
    )
    op.create_index("ix_bank_transactions_txn_date", "bank_transactions", ["txn_date"])


def downgrade() -> None:
    for table in ("bank_transactions", "audit_log", "receipts", "expenses", "vendors", "expense_categories", "users"):
        op.drop_table(table)
