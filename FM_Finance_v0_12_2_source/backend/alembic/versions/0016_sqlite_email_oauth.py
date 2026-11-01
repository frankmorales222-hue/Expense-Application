"""v0.7.1 Microsoft 365 sign-in for email (SQLite branch). DDL lives in app/schema_email_oauth.py.

Revision ID: 0016_sqlite_email_oauth
Revises: 0014_sqlite_sales
"""

from app.schema_email_oauth import downgrade_email_oauth, upgrade_email_oauth

revision = "0016_sqlite_email_oauth"
down_revision = "0014_sqlite_sales"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_email_oauth()


def downgrade() -> None:
    downgrade_email_oauth()
