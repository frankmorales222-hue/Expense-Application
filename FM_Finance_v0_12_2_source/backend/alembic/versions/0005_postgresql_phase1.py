"""Phase 1 banking foundation (PostgreSQL branch). DDL lives in app/schema_phase1.py.

Revision ID: 0005_postgresql_phase1
Revises: 0003_postgresql
"""

from app.schema_phase1 import downgrade_phase1, upgrade_phase1

revision = "0005_postgresql_phase1"
down_revision = "0003_postgresql"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_phase1()


def downgrade() -> None:
    downgrade_phase1()
