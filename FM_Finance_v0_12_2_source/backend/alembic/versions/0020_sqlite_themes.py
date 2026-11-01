"""v0.9.0 themes (SQLite branch). DDL lives in app/schema_themes.py.

Revision ID: 0020_sqlite_themes
Revises: 0018_sqlite_modules
"""

from app.schema_themes import downgrade_themes, upgrade_themes

revision = "0020_sqlite_themes"
down_revision = "0018_sqlite_modules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_themes()


def downgrade() -> None:
    downgrade_themes()
