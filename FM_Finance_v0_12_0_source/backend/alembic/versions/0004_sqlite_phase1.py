"""Phase 1 banking foundation (SQLite branch). DDL lives in app/schema_phase1.py.

Revision ID: 0004_sqlite_phase1
Revises: 0002_sqlite
"""

from app.schema_phase1 import downgrade_phase1, upgrade_phase1

revision = "0004_sqlite_phase1"
down_revision = "0002_sqlite"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_phase1()


def downgrade() -> None:
    downgrade_phase1()
