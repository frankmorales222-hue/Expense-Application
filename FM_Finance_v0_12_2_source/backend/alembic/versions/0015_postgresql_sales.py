"""v0.7.0 invoices, payments received, products and services, email (PostgreSQL branch).
DDL lives in app/schema_sales.py.

Revision ID: 0015_postgresql_sales
Revises: 0013_postgresql_ledger
"""

from app.schema_sales import downgrade_sales, upgrade_sales

revision = "0015_postgresql_sales"
down_revision = "0013_postgresql_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_sales()


def downgrade() -> None:
    downgrade_sales()
