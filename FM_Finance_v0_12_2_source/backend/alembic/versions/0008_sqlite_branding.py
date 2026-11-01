"""v0.4.1 company logo (SQLite branch). DDL lives in app/schema_branding.py.

Revision ID: 0008_sqlite_branding
Revises: 0006_sqlite_bills
"""

from app.schema_branding import downgrade_branding, upgrade_branding

revision = "0008_sqlite_branding"
down_revision = "0006_sqlite_bills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_branding()


def downgrade() -> None:
    downgrade_branding()
