"""v0.10.0 company rules (SQLite branch). DDL lives in app/schema_rules.py.

Revision ID: 0022_sqlite_rules
Revises: 0020_sqlite_themes
"""

from app.schema_rules import downgrade_rules, upgrade_rules

revision = "0022_sqlite_rules"
down_revision = "0020_sqlite_themes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_rules()


def downgrade() -> None:
    downgrade_rules()
