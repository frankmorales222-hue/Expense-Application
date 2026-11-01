"""v0.9.0 themes (PostgreSQL branch). DDL lives in app/schema_themes.py.

Revision ID: 0021_postgresql_themes
Revises: 0019_postgresql_modules
"""

from app.schema_themes import downgrade_themes, upgrade_themes

revision = "0021_postgresql_themes"
down_revision = "0019_postgresql_modules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_themes()


def downgrade() -> None:
    downgrade_themes()
