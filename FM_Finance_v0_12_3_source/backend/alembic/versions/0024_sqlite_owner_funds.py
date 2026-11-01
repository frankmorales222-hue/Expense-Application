"""v0.11.0 owner funds (SQLite branch).

Revision ID: 0024_sqlite_owner_funds
Revises: 0022_sqlite_rules
"""

from app.schema_owner_funds import downgrade_owner_funds, upgrade_owner_funds

revision = "0024_sqlite_owner_funds"
down_revision = "0022_sqlite_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_owner_funds()


def downgrade() -> None:
    downgrade_owner_funds()
