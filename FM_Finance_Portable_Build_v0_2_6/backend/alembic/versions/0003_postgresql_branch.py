"""Label the existing PostgreSQL schema branch; no tables or data change.

Revision ID: 0003_postgresql
Revises: 0001
"""

from alembic import op

revision = "0003_postgresql"
down_revision = "0001"
branch_labels = ("postgresql",)
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Use sqlite@head for a SQLite database")


def downgrade() -> None:
    pass
