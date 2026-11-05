"""v0.6.0 accounting engine, shared by the SQLite and PostgreSQL branches.

Schema only (plus two plain-SQL data steps). The chart of accounts and the initial journal are built
in Python at startup (app.ledger.books.ensure_books), using the same posting rules as day-to-day use.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from .types import CurrencyAmount, UTCDateTime


def _ts(name: str) -> sa.Column:
    return sa.Column(name, UTCDateTime(), nullable=False, server_default=sa.func.now())


def _id(postgres: bool) -> sa.Column:
    default = sa.text("gen_random_uuid()") if postgres else sa.text("(lower(hex(randomblob(16))))")
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=default)


def _company() -> sa.Column:
    return sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False)


def _lines_table(name: str, parent: str, postgres: bool) -> None:
    op.create_table(
        name,
        _id(postgres),
        _company(),
        sa.Column(f"{parent}_id", sa.Uuid(), sa.ForeignKey(f"{parent}s.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("expense_categories.id"), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("amount", CurrencyAmount(), nullable=False),
        sa.Column("billable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=True),
        sa.CheckConstraint("amount > 0", name=f"ck_{name}_amount_positive"),
    )
    op.create_index(f"ix_{name}_parent", name, [f"{parent}_id"])


def upgrade_ledger() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"

    op.create_table(
        "ledger_accounts",
        _id(postgres),
        _company(),
        sa.Column("code", sa.String(20), nullable=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("type", sa.String(12), nullable=False),
        sa.Column("detail_type", sa.String(30), nullable=False),
        sa.Column("system_key", sa.String(40), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts("created_at"),
        sa.CheckConstraint("type IN ('asset','liability','equity','income','expense')", name="ck_ledger_accounts_type"),
        sa.UniqueConstraint("company_id", "system_key", name="uq_ledger_accounts_system_key"),
    )
    op.create_index("ix_ledger_accounts_company", "ledger_accounts", ["company_id", "type"])

    op.create_table(
        "journal_entries",
        _id(postgres),
        _company(),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("number", sa.String(30), nullable=True),
        sa.Column("memo", sa.String(500), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        _ts("created_at"),
    )
    op.create_index("ix_journal_entries_source", "journal_entries", ["company_id", "source_type", "source_id"])
    op.create_index("ix_journal_entries_date", "journal_entries", ["company_id", "entry_date"])

    op.create_table(
        "journal_lines",
        _id(postgres),
        _company(),
        sa.Column("entry_id", sa.Uuid(), sa.ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("ledger_accounts.id"), nullable=False),
        sa.Column("debit", CurrencyAmount(), nullable=False, server_default="0"),
        sa.Column("credit", CurrencyAmount(), nullable=False, server_default="0"),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("vendor_id", sa.Uuid(), sa.ForeignKey("vendors.id"), nullable=True),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=True),
        sa.CheckConstraint("debit >= 0 AND credit >= 0 AND (debit = 0 OR credit = 0)", name="ck_journal_lines_side"),
    )
    op.create_index("ix_journal_lines_entry", "journal_lines", ["entry_id"])
    op.create_index("ix_journal_lines_account", "journal_lines", ["company_id", "account_id"])

    op.create_table(
        "bills",
        _id(postgres),
        _company(),
        sa.Column("vendor_id", sa.Uuid(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("bill_date", sa.Date(), nullable=False),
        sa.Column("terms", sa.String(20), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("bill_number", sa.String(100), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("total", CurrencyAmount(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("total > 0", name="ck_bills_total_positive"),
    )
    op.create_index("ix_bills_company_due", "bills", ["company_id", "is_deleted", "due_date"])
    _lines_table("bill_lines", "bill", postgres)
    _lines_table("expense_lines", "expense", postgres)

    op.create_table(
        "bill_payments",
        _id(postgres),
        _company(),
        sa.Column("bill_id", sa.Uuid(), sa.ForeignKey("bills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("financial_accounts.id"), nullable=False),
        sa.Column("amount", CurrencyAmount(), nullable=False),
        sa.Column("memo", sa.String(500), nullable=True),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=True, unique=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint("amount > 0", name="ck_bill_payments_amount_positive"),
    )
    op.create_index("ix_bill_payments_bill", "bill_payments", ["bill_id"])

    op.create_table(
        "bill_attachments",
        _id(postgres),
        _company(),
        sa.Column("bill_id", sa.Uuid(), sa.ForeignKey("bills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        _ts("uploaded_at"),
    )
    op.create_index("ix_bill_attachments_bill", "bill_attachments", ["bill_id"])

    # New columns on existing tables (plain ADD COLUMN; foreign keys added on PostgreSQL).
    op.add_column("companies", sa.Column("closing_date", sa.Date(), nullable=True))
    op.add_column("companies", sa.Column("ledger_ready", sa.Boolean(), nullable=False, server_default=sa.false()))
    for table in ("expense_categories", "financial_accounts"):
        op.add_column(table, sa.Column("ledger_account_id", sa.Uuid(), nullable=True))
        if postgres:
            op.create_foreign_key(f"fk_{table}_ledger_account", table, "ledger_accounts",
                                  ["ledger_account_id"], ["id"])
    op.add_column("expenses", sa.Column("payment_account_id", sa.Uuid(), nullable=True))
    if postgres:
        op.create_foreign_key("fk_expenses_payment_account", "expenses", "financial_accounts",
                              ["payment_account_id"], ["id"])

    # Existing expenses become one-line expenses...
    new_id = "gen_random_uuid()" if postgres else "lower(hex(randomblob(16)))"
    false = "false" if postgres else "0"
    op.execute(f"INSERT INTO expense_lines (id, company_id, expense_id, line_no, category_id, amount, billable) "
               f"SELECT {new_id}, company_id, id, 0, category_id, amount, {false} FROM expenses")
    # ...and take their payment account from the bank transaction they're linked to, when there is one.
    op.execute(f"UPDATE expenses SET payment_account_id = (SELECT t.account_id FROM transactions t "
               f"WHERE t.expense_id = expenses.id ORDER BY t.created_at LIMIT 1) "
               f"WHERE payment_account_id IS NULL AND is_reimbursable = {false}")


def downgrade_ledger() -> None:
    raise NotImplementedError("v0.6.0 can't be downgraded automatically. Restore the backup of the data folder.")
