"""v0.10.0: company rules. Shared by the SQLite and PostgreSQL branches.

- companies.rules: what each company changed (payment terms, payment methods, approvals, formats, custom
  fields, invoice wording...). NULL keeps today's behavior.
- expenses: the fixed list of payment methods (a CHECK constraint) is gone.
- custom: values of custom fields on customers, items, invoices, bills and expenses.
- plans: plans as data (the platform owner's, and each reseller's own), seeded with the four v0.8.0 plans.
- company_roles + company_members.custom_role_id: roles a company defines for itself.
- bank_rules: a company's own rules for categorizing bank transactions.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from .schema_ledger import _company, _id, _ts
from .types import CurrencyAmount

PLANS = [  # key, label, modules, user limit, sort
    ("starter", "Starter", ["invoicing"], 1, 1),
    ("essentials", "Essentials", ["invoicing", "bills", "smart_capture"], 3, 2),
    ("plus", "Plus", ["invoicing", "bills", "smart_capture", "advanced_accounting"], 5, 3),
    ("advanced", "Advanced", ["invoicing", "bills", "smart_capture", "advanced_accounting"], 25, 4),
]


def upgrade_rules() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    js = JSONB() if postgres else sa.JSON()

    op.add_column("companies", sa.Column("rules", js, nullable=True))
    for table in ("customers", "items", "invoices", "bills", "expenses"):
        op.add_column(table, sa.Column("custom", js, nullable=True))
    if postgres:  # payment-method codes can now be up to 20 characters
        op.alter_column("customer_payments", "method", type_=sa.String(20))
    # Expense payment methods were a fixed list in the database; each company now keeps its own (checked by the app).
    if postgres:
        op.drop_constraint("ck_expenses_payment_method", "expenses", type_="check")
    else:  # SQLite can't drop a CHECK in place: rebuild the table (migrations run with foreign keys off)
        with op.batch_alter_table("expenses", recreate="always") as batch:
            batch.drop_constraint("ck_expenses_payment_method", type_="check")

    op.create_table(
        "plans",
        _id(postgres),
        sa.Column("reseller_id", sa.Uuid(), sa.ForeignKey("resellers.id", ondelete="CASCADE"), nullable=True),
        sa.Column("key", sa.String(30), nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("description", sa.String(300), nullable=True),
        sa.Column("modules", js, nullable=False),
        sa.Column("user_limit", sa.Integer(), nullable=True),
        sa.Column("monthly_price", CurrencyAmount(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        _ts("created_at"),
    )
    op.create_index("ix_plans_key", "plans", ["reseller_id", "key"], unique=True)
    # Plain SQL so the offline (--sql) PostgreSQL script can render it too.
    import json
    import uuid as _uuid

    for k, label, mods, limit, sort in PLANS:
        u = _uuid.uuid4()
        uid = f"'{u}'" if postgres else f"'{u.hex}'"
        mod = f"CAST('{json.dumps(mods)}' AS JSONB)" if postgres else f"'{json.dumps(mods)}'"
        yes = "true" if postgres else "1"
        op.execute(f"INSERT INTO plans (id, reseller_id, key, label, modules, user_limit, is_active, sort_order) "
                   f"VALUES ({uid}, NULL, '{k}', '{label}', {mod}, {limit}, {yes}, {sort})")

    op.create_table(
        "company_roles",
        _id(postgres),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("description", sa.String(300), nullable=True),
        sa.Column("base_role", sa.String(20), nullable=False),
        sa.Column("permissions", js, nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("company_id", "name", name="uq_company_roles_name"),
    )
    if postgres:
        op.add_column("company_members", sa.Column("custom_role_id", sa.Uuid(),
                                                   sa.ForeignKey("company_roles.id", ondelete="SET NULL"), nullable=True))
    else:  # SQLite can't add a column with a foreign key to an existing table; the app keeps it consistent
        op.add_column("company_members", sa.Column("custom_role_id", sa.Uuid(), nullable=True))

    op.create_table(
        "bank_rules",
        _id(postgres),
        _company(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("match_type", sa.String(12), nullable=False, server_default="contains"),
        sa.Column("match_text", sa.String(200), nullable=False),
        sa.Column("direction", sa.String(4), nullable=False, server_default="any"),
        sa.Column("amount_min", CurrencyAmount(), nullable=True),
        sa.Column("amount_max", CurrencyAmount(), nullable=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("financial_accounts.id"), nullable=True),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("expense_categories.id"), nullable=True),
        sa.Column("vendor_name", sa.String(255), nullable=True),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("memo", sa.String(500), nullable=True),
        sa.Column("auto_approve", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("times_used", sa.Integer(), nullable=False, server_default="0"),
        _ts("created_at"),
    )
    op.create_index("ix_bank_rules_company", "bank_rules", ["company_id", "priority"])


def downgrade_rules() -> None:
    raise NotImplementedError("Restore the backup of the data folder to go back to an earlier version.")
