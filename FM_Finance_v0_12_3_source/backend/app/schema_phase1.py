"""Phase 1 (banking foundation) schema, shared by the SQLite and PostgreSQL branches.

Both Alembic branches call these functions so a schema change is written once.
CurrencyAmount renders as BIGINT cents on SQLite and NUMERIC(12,2) on PostgreSQL.
Future migrations should follow the same pattern: put the DDL here (or in a new
schema_phaseN.py) and add a thin revision file to each branch.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from .types import CurrencyAmount, UTCDateTime


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(JSONB(), "postgresql")


def _id() -> sa.Column:
    return sa.Column("id", sa.Uuid(), primary_key=True)


def _ts(name: str) -> sa.Column:
    return sa.Column(name, UTCDateTime(), nullable=False, server_default=sa.func.now())


def upgrade_phase1() -> None:
    # Plain ADD COLUMN only: on SQLite anything else forces a table rebuild, which
    # would drop reflected CHECK constraints and the lower(name) vendor index.
    postgres = op.get_bind().dialect.name == "postgresql"
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("expense_categories", sa.Column("kind", sa.String(10), nullable=False, server_default="expense"))
    op.add_column("expense_categories", sa.Column("tax_line", sa.String(100), nullable=True))
    op.add_column("vendors", sa.Column("match_key", sa.String(255), nullable=True))
    op.add_column("vendors", sa.Column("default_category_id", sa.Uuid(), nullable=True))
    op.add_column("vendors", sa.Column("is_1099", sa.Boolean(), nullable=False, server_default=sa.false()))
    if postgres:
        op.create_check_constraint("ck_categories_kind", "expense_categories", "kind IN ('expense','income','equity')")
        op.create_foreign_key("fk_vendors_default_category", "vendors", "expense_categories",
                              ["default_category_id"], ["id"])
    op.create_index("ix_vendors_match_key", "vendors", ["match_key"])

    op.create_table(
        "companies",
        _id(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("legal_name", sa.String(255), nullable=True),
        sa.Column("base_currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("fiscal_year_start_month", sa.Integer(), nullable=False, server_default="1"),
        _ts("created_at"),
        sa.CheckConstraint("fiscal_year_start_month BETWEEN 1 AND 12", name="ck_companies_fy_month"),
    )

    op.create_table(
        "financial_accounts",
        _id(),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("institution", sa.String(120), nullable=True),
        sa.Column("last4", sa.String(4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("opening_balance", CurrencyAmount(), nullable=False, server_default="0"),
        sa.Column("opening_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("csv_profile", _json(), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint("kind IN ('checking','savings','credit_card','cash','other')",
                           name="ck_financial_accounts_kind"),
        sa.UniqueConstraint("company_id", "name", name="uq_financial_accounts_name"),
    )

    op.create_table(
        "customers",
        _id(),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts("created_at"),
        sa.UniqueConstraint("company_id", "name", name="uq_customers_name"),
    )

    op.create_table(
        "import_batches",
        _id(),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("financial_accounts.id"), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("rows_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_duplicate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_invalid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_flagged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint("source IN ('csv','ofx')", name="ck_import_batches_source"),
        sa.CheckConstraint("status IN ('active','undone')", name="ck_import_batches_status"),
    )
    op.create_index("ix_import_batches_account", "import_batches", ["account_id", "created_at"])

    op.create_table(
        "transactions",
        _id(),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("financial_accounts.id"), nullable=False),
        sa.Column("import_batch_id", sa.Uuid(), sa.ForeignKey("import_batches.id"), nullable=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("txn_date", sa.Date(), nullable=False),
        sa.Column("amount", CurrencyAmount(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("normalized", sa.String(255), nullable=False, server_default=""),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("fingerprint", sa.String(80), nullable=False),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(12), nullable=False, server_default="unreviewed"),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("expense_categories.id"), nullable=True),
        sa.Column("vendor_id", sa.Uuid(), sa.ForeignKey("vendors.id"), nullable=True),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("suggested_category_id", sa.Uuid(), sa.ForeignKey("expense_categories.id"), nullable=True),
        sa.Column("suggested_vendor_id", sa.Uuid(), sa.ForeignKey("vendors.id"), nullable=True),
        sa.Column("suggested_vendor_name", sa.String(255), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("suggestion_reason", sa.String(255), nullable=True),
        sa.Column("is_transfer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("transfer_peer_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=True),
        sa.Column("duplicate_of_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=True),
        sa.Column("expense_id", sa.Uuid(), sa.ForeignKey("expenses.id"), nullable=True),
        sa.Column("reconciled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", UTCDateTime(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("source IN ('csv','ofx','manual')", name="ck_transactions_source"),
        sa.CheckConstraint("review_status IN ('unreviewed','approved','excluded')", name="ck_transactions_review"),
        sa.CheckConstraint("amount <> 0", name="ck_transactions_amount_nonzero"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_transactions_confidence"),
        sa.UniqueConstraint("account_id", "external_id", name="uq_transactions_external_id"),
        sa.UniqueConstraint("account_id", "fingerprint", name="uq_transactions_fingerprint"),
    )
    op.create_index("ix_transactions_account_date", "transactions", ["account_id", "txn_date"])
    op.create_index("ix_transactions_review", "transactions", ["company_id", "review_status", "txn_date"])
    op.create_index("ix_transactions_normalized", "transactions", ["normalized"])
    op.create_index("ix_transactions_batch", "transactions", ["import_batch_id"])
    op.create_index("ix_transactions_expense", "transactions", ["expense_id"])


def downgrade_phase1() -> None:
    for name in ("transactions", "import_batches", "customers", "financial_accounts", "companies"):
        op.drop_table(name)
    op.drop_index("ix_vendors_match_key", table_name="vendors")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("fk_vendors_default_category", "vendors", type_="foreignkey")
        op.drop_constraint("ck_categories_kind", "expense_categories", type_="check")
    for table, column in (("vendors", "is_1099"), ("vendors", "default_category_id"), ("vendors", "match_key"),
                          ("expense_categories", "tax_line"), ("expense_categories", "kind"),
                          ("users", "token_version")):
        op.drop_column(table, column)
