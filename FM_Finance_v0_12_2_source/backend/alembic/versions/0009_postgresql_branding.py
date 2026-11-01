"""v0.4.1 company logo (PostgreSQL branch). DDL lives in app/schema_branding.py.

Revision ID: 0009_postgresql_branding
Revises: 0007_postgresql_bills
"""

from app.schema_branding import downgrade_branding, upgrade_branding

revision = "0009_postgresql_branding"
down_revision = "0007_postgresql_bills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_branding()


def downgrade() -> None:
    downgrade_branding()
