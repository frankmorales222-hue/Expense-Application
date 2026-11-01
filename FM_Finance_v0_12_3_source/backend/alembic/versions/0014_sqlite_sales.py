"""v0.7.0 invoices, payments received, products and services, email (SQLite branch).
DDL lives in app/schema_sales.py.

Revision ID: 0014_sqlite_sales
Revises: 0012_sqlite_ledger
"""

from app.schema_sales import downgrade_sales, upgrade_sales

revision = "0014_sqlite_sales"
down_revision = "0012_sqlite_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_sales()


def downgrade() -> None:
    downgrade_sales()
