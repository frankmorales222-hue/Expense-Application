"""v0.6.0 accounting engine (PostgreSQL branch). DDL lives in app/schema_ledger.py.

Revision ID: 0013_postgresql_ledger
Revises: 0011_postgresql_multicompany
"""

from app.schema_ledger import downgrade_ledger, upgrade_ledger

revision = "0013_postgresql_ledger"
down_revision = "0011_postgresql_multicompany"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_ledger()


def downgrade() -> None:
    downgrade_ledger()
