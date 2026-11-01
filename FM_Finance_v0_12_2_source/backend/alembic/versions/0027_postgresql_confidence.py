"""v0.12.0 reconciliation and accountant review (PostgreSQL branch).

Revision ID: 0027_postgresql_confidence
Revises: 0025_postgresql_owner_funds
"""

from app.schema_confidence import downgrade_confidence, upgrade_confidence

revision = "0027_postgresql_confidence"
down_revision = "0025_postgresql_owner_funds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_confidence()


def downgrade() -> None:
    downgrade_confidence()
