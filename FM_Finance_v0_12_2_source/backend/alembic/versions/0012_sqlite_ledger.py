"""v0.6.0 accounting engine (SQLite branch). DDL lives in app/schema_ledger.py.

Revision ID: 0012_sqlite_ledger
Revises: 0010_sqlite_multicompany
"""

from app.schema_ledger import downgrade_ledger, upgrade_ledger

revision = "0012_sqlite_ledger"
down_revision = "0010_sqlite_multicompany"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_ledger()


def downgrade() -> None:
    downgrade_ledger()
