"""v0.5.0 multi-company foundation, shared by the SQLite and PostgreSQL branches.

- New tables: resellers, company_members, reseller_admins.
- companies gain reseller_id and is_active; users gain is_platform_admin.
- expense_categories, vendors, expenses, receipts and audit_log gain company_id. Existing rows are
  moved into the existing company (or a new "My Company" when an older database has none).
- Category codes and vendor names become unique per company instead of across the whole app.
  On SQLite that needs a table rebuild; alembic/env.py turns foreign-key enforcement off for the
  migration and runs PRAGMA foreign_key_check before committing.
- Existing users get a membership in that company: admin -> owner, approver -> bookkeeper,
  submitter -> employee. Existing admins become platform admins.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from .types import CurrencyAmount, UTCDateTime

SCOPED_SIMPLE = ("expenses", "receipts", "audit_log")
NULLABLE_SCOPE = {"audit_log"}  # account-level audit events have no company


def _ts(name: str) -> sa.Column:
    return sa.Column(name, UTCDateTime(), nullable=False, server_default=sa.func.now())


def _new_id_default(postgres: bool):
    return sa.text("gen_random_uuid()") if postgres else sa.text("(lower(hex(randomblob(16))))")


def upgrade_multicompany() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"

    # ---- new tables
    op.create_table(
        "resellers",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_new_id_default(postgres)),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts("created_at"),
    )
    op.create_table(
        "company_members",
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(20), nullable=False),
        _ts("created_at"),
        sa.CheckConstraint("role IN ('owner','accountant','bookkeeper','employee','viewer')",
                           name="ck_company_members_role"),
    )
    op.create_index("ix_company_members_user", "company_members", ["user_id"])
    op.create_table(
        "reseller_admins",
        sa.Column("reseller_id", sa.Uuid(), sa.ForeignKey("resellers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        _ts("created_at"),
    )
    op.create_index("ix_reseller_admins_user", "reseller_admins", ["user_id"])

    # ---- new columns on companies and users (plain ADD COLUMN; FKs added on PostgreSQL)
    op.add_column("companies", sa.Column("reseller_id", sa.Uuid(), nullable=True))
    op.add_column("companies", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    if postgres:
        op.create_foreign_key("fk_companies_reseller", "companies", "resellers", ["reseller_id"], ["id"])
    op.create_index("ix_companies_reseller", "companies", ["reseller_id"])
    op.add_column("users", sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(sa.text("UPDATE users SET is_platform_admin = :t WHERE role = 'admin'").bindparams(t=True))

    # ---- the company that existing data belongs to: the oldest one, or a new "My Company" when an
    # older database has users but no company yet. Written as plain SQL so it also works when the
    # PostgreSQL migration is generated as a script (alembic --sql).
    new_id = "gen_random_uuid()" if postgres else "lower(hex(randomblob(16)))"
    op.execute(f"INSERT INTO companies (id, name, base_currency, fiscal_year_start_month) "
               f"SELECT {new_id}, 'My Company', 'USD', 1 WHERE NOT EXISTS (SELECT 1 FROM companies) "
               f"AND (EXISTS (SELECT 1 FROM users) OR EXISTS (SELECT 1 FROM vendors) "
               f"OR EXISTS (SELECT 1 FROM expense_categories) OR EXISTS (SELECT 1 FROM expenses))")
    first = "(SELECT id FROM companies ORDER BY created_at, id LIMIT 1)"

    # ---- memberships for existing users
    op.execute(f"INSERT INTO company_members (company_id, user_id, role) SELECT {first}, id, "
               f"CASE role WHEN 'admin' THEN 'owner' WHEN 'approver' THEN 'bookkeeper' ELSE 'employee' END "
               f"FROM users WHERE EXISTS (SELECT 1 FROM companies)")

    # ---- company_id on scoped tables
    for table in SCOPED_SIMPLE:
        op.add_column(table, sa.Column("company_id", sa.Uuid(), nullable=True))
        op.execute(f"UPDATE {table} SET company_id = {first}")
        if postgres:
            if table not in NULLABLE_SCOPE:
                op.alter_column(table, "company_id", nullable=False)
            op.create_foreign_key(f"fk_{table}_company", table, "companies", ["company_id"], ["id"])
    op.create_index("ix_expenses_company_date", "expenses", ["company_id", "is_deleted", "expense_date"])
    op.create_index("ix_receipts_company", "receipts", ["company_id"])
    op.create_index("ix_audit_company", "audit_log", ["company_id", "entity_type", "entity_id"])

    if postgres:
        _postgres_categories_vendors(first)
    else:
        _sqlite_rebuild_categories_vendors(first)


def _postgres_categories_vendors(first: str) -> None:
    for table in ("expense_categories", "vendors"):
        op.add_column(table, sa.Column("company_id", sa.Uuid(), nullable=True))
        op.execute(f"UPDATE {table} SET company_id = {first}")
        op.alter_column(table, "company_id", nullable=False)
        op.create_foreign_key(f"fk_{table}_company", table, "companies", ["company_id"], ["id"])
    op.drop_constraint("expense_categories_code_key", "expense_categories", type_="unique")
    op.create_unique_constraint("uq_categories_company_code", "expense_categories", ["company_id", "code"])
    op.drop_constraint("vendors_name_key", "vendors", type_="unique")
    op.drop_index("ix_vendors_name_lower", table_name="vendors")
    op.create_index("ix_vendors_company_name_lower", "vendors", ["company_id", sa.text("lower(name)")], unique=True)


def _sqlite_rebuild_categories_vendors(first: str) -> None:
    """Rebuild with per-company uniqueness. Every column and CHECK constraint is listed explicitly."""
    default_id = sa.text("(lower(hex(randomblob(16))))")

    op.create_table(
        "expense_categories_new",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=default_id),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("approval_threshold", CurrencyAmount(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("kind", sa.String(10), nullable=False, server_default="expense"),
        sa.Column("tax_line", sa.String(100), nullable=True),
        sa.CheckConstraint("approval_threshold IS NULL OR approval_threshold >= 0", name="ck_categories_threshold"),
        sa.CheckConstraint("kind IN ('expense','income','equity')", name="ck_categories_kind"),
        sa.UniqueConstraint("company_id", "code", name="uq_categories_company_code"),
    )
    cat_cols = "id, code, name, approval_threshold, is_active, sort_order, kind, tax_line"
    op.execute(f"INSERT INTO expense_categories_new (company_id, {cat_cols}) "
               f"SELECT {first}, {cat_cols} FROM expense_categories")
    op.drop_table("expense_categories")
    op.rename_table("expense_categories_new", "expense_categories")

    op.create_table(
        "vendors_new",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=default_id),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        _ts("created_at"),
        sa.Column("match_key", sa.String(255), nullable=True),
        sa.Column("default_category_id", sa.Uuid(), sa.ForeignKey("expense_categories.id"), nullable=True),
        sa.Column("is_1099", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    ven_cols = "id, name, created_at, match_key, default_category_id, is_1099"
    op.execute(f"INSERT INTO vendors_new (company_id, {ven_cols}) SELECT {first}, {ven_cols} FROM vendors")
    op.drop_table("vendors")
    op.rename_table("vendors_new", "vendors")
    op.create_index("ix_vendors_company_name_lower", "vendors", ["company_id", sa.text("lower(name)")], unique=True)
    op.create_index("ix_vendors_match_key", "vendors", ["match_key"])


def downgrade_multicompany() -> None:
    raise NotImplementedError("v0.5.0 can't be downgraded automatically. Restore the backup of the data folder.")
