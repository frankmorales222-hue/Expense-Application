"""v0.10.0 company rules (PostgreSQL branch). DDL lives in app/schema_rules.py.

Revision ID: 0023_postgresql_rules
Revises: 0021_postgresql_themes
"""

from app.schema_rules import downgrade_rules, upgrade_rules

revision = "0023_postgresql_rules"
down_revision = "0021_postgresql_themes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_rules()


def downgrade() -> None:
    downgrade_rules()
