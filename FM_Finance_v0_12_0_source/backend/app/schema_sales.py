"""v0.7.0 sales (invoices, payments received, products and services, outgoing email).
Shared by the SQLite and PostgreSQL branches. Schema only; no data changes to existing rows."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from .schema_ledger import _company, _id, _ts
from .types import CurrencyAmount, UTCDateTime


def upgrade_sales() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"

    for col in (sa.Column("address", sa.Text(), nullable=True), sa.Column("phone", sa.String(50), nullable=True),
                sa.Column("email", sa.String(255), nullable=True), sa.Column("website", sa.String(255), nullable=True),
                sa.Column("invoice_footer", sa.Text(), nullable=True)):
        op.add_column("companies", col)
    for col in (sa.Column("cc_emails", sa.String(500), nullable=True), sa.Column("phone", sa.String(50), nullable=True),
                sa.Column("billing_address", sa.Text(), nullable=True),
                sa.Column("default_terms", sa.String(20), nullable=True)):
        op.add_column("customers", col)

    op.create_table(
        "items",
        _id(postgres),
        _company(),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("rate", CurrencyAmount(), nullable=True),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("expense_categories.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts("created_at"),
    )
    op.create_index("ix_items_company", "items", ["company_id", "name"])

    op.create_table(
        "invoices",
        _id(postgres),
        _company(),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("invoice_number", sa.String(30), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("terms", sa.String(20), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("bill_email", sa.String(255), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("total", CurrencyAmount(), nullable=False),
        sa.Column("sent_at", UTCDateTime(), nullable=True),
        sa.Column("is_void", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("voided_at", UTCDateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("total > 0", name="ck_invoices_total_positive"),
        sa.UniqueConstraint("company_id", "invoice_number", name="uq_invoices_number"),
    )
    op.create_index("ix_invoices_customer", "invoices", ["company_id", "customer_id"])
    op.create_index("ix_invoices_due", "invoices", ["company_id", "is_deleted", "due_date"])

    op.create_table(
        "invoice_lines",
        _id(postgres),
        _company(),
        sa.Column("invoice_id", sa.Uuid(), sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("service_date", sa.Date(), nullable=True),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("items.id"), nullable=True),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("quantity", CurrencyAmount(), nullable=False),
        sa.Column("rate", CurrencyAmount(), nullable=False),
        sa.Column("amount", CurrencyAmount(), nullable=False),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("expense_categories.id"), nullable=True),
        sa.Column("expense_line_id", sa.Uuid(), sa.ForeignKey("expense_lines.id"), nullable=True),
        sa.Column("bill_line_id", sa.Uuid(), sa.ForeignKey("bill_lines.id"), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_invoice_lines_amount_positive"),
    )
    op.create_index("ix_invoice_lines_invoice", "invoice_lines", ["invoice_id"])

    op.create_table(
        "customer_payments",
        _id(postgres),
        _company(),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("financial_accounts.id"), nullable=False),
        sa.Column("amount", CurrencyAmount(), nullable=False),
        sa.Column("method", sa.String(10), nullable=True),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("memo", sa.String(500), nullable=True),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=True, unique=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint("amount > 0", name="ck_customer_payments_amount_positive"),
    )
    op.create_index("ix_customer_payments_customer", "customer_payments", ["company_id", "customer_id"])

    op.create_table(
        "payment_applications",
        _id(postgres),
        _company(),
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("customer_payments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("amount", CurrencyAmount(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_payment_applications_amount_positive"),
    )
    op.create_index("ix_payment_applications_invoice", "payment_applications", ["invoice_id"])
    op.create_index("ix_payment_applications_payment", "payment_applications", ["payment_id"])

    op.create_table(
        "email_settings",
        _id(postgres),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False, unique=True),
        sa.Column("smtp_host", sa.String(255), nullable=False),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("security", sa.String(10), nullable=False, server_default="starttls"),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        sa.Column("from_email", sa.String(255), nullable=False),
        sa.Column("from_name", sa.String(255), nullable=True),
        sa.Column("reply_to", sa.String(255), nullable=True),
        sa.Column("copy_me", sa.Boolean(), nullable=False, server_default=sa.false()),
        _ts("updated_at"),
    )

    op.create_table(
        "invoice_emails",
        _id(postgres),
        _company(),
        sa.Column("invoice_id", sa.Uuid(), sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sent_to", sa.String(1000), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("error", sa.String(1000), nullable=True),
        sa.Column("sent_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        _ts("sent_at"),
    )
    op.create_index("ix_invoice_emails_invoice", "invoice_emails", ["invoice_id"])


def downgrade_sales() -> None:
    raise NotImplementedError("v0.7.0 can't be downgraded automatically. Restore the backup of the data folder.")
