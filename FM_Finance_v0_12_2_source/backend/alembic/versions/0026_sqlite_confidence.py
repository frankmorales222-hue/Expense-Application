"""v0.12.0 reconciliation and accountant review (SQLite branch).

Revision ID: 0026_sqlite_confidence
Revises: 0024_sqlite_owner_funds
"""

from app.schema_confidence import downgrade_confidence, upgrade_confidence

revision = "0026_sqlite_confidence"
down_revision = "0024_sqlite_owner_funds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_confidence()


def downgrade() -> None:
    downgrade_confidence()
