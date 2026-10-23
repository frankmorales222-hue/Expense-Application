"""v0.5.0 multi-company foundation (PostgreSQL branch). DDL lives in app/schema_multicompany.py.

Revision ID: 0011_postgresql_multicompany
Revises: 0009_postgresql_branding
"""

from app.schema_multicompany import downgrade_multicompany, upgrade_multicompany

revision = "0011_postgresql_multicompany"
down_revision = "0009_postgresql_branding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_multicompany()


def downgrade() -> None:
    downgrade_multicompany()
