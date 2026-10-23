"""v0.8.0 plans and modules (SQLite branch). DDL lives in app/schema_modules.py.

Revision ID: 0018_sqlite_modules
Revises: 0016_sqlite_email_oauth
"""

from app.schema_modules import downgrade_modules, upgrade_modules

revision = "0018_sqlite_modules"
down_revision = "0016_sqlite_email_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_modules()


def downgrade() -> None:
    downgrade_modules()
