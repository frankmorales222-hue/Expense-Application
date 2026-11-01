"""v0.8.0 plans and modules (PostgreSQL branch). DDL lives in app/schema_modules.py.

Revision ID: 0019_postgresql_modules
Revises: 0017_postgresql_email_oauth
"""

from app.schema_modules import downgrade_modules, upgrade_modules

revision = "0019_postgresql_modules"
down_revision = "0017_postgresql_email_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_modules()


def downgrade() -> None:
    downgrade_modules()
