"""v0.11.0 owner funds (PostgreSQL branch).

Revision ID: 0025_postgresql_owner_funds
Revises: 0023_postgresql_rules
"""

from app.schema_owner_funds import downgrade_owner_funds, upgrade_owner_funds

revision = "0025_postgresql_owner_funds"
down_revision = "0023_postgresql_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_owner_funds()


def downgrade() -> None:
    downgrade_owner_funds()
