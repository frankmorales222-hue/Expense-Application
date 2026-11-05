"""v0.4.0 bill import fields (SQLite branch). DDL lives in app/schema_phase2.py.

Revision ID: 0006_sqlite_bills
Revises: 0004_sqlite_phase1
"""

from app.schema_phase2 import downgrade_phase2, upgrade_phase2

revision = "0006_sqlite_bills"
down_revision = "0004_sqlite_phase1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_phase2()


def downgrade() -> None:
    downgrade_phase2()
