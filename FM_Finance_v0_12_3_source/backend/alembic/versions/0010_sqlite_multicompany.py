"""v0.5.0 multi-company foundation (SQLite branch). DDL lives in app/schema_multicompany.py.

Revision ID: 0010_sqlite_multicompany
Revises: 0008_sqlite_branding
"""

from app.schema_multicompany import downgrade_multicompany, upgrade_multicompany

revision = "0010_sqlite_multicompany"
down_revision = "0008_sqlite_branding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_multicompany()


def downgrade() -> None:
    downgrade_multicompany()
