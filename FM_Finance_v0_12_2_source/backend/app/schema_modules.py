"""v0.8.0: plans and modules per company, and the Microsoft tenant ID for single-tenant apps."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


def upgrade_modules() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    op.add_column("companies", sa.Column("plan", sa.String(20), nullable=True))
    op.add_column("companies", sa.Column("modules", JSONB() if postgres else sa.JSON(), nullable=True))
    op.add_column("companies", sa.Column("user_limit", sa.Integer(), nullable=True))
    op.add_column("email_settings", sa.Column("oauth_tenant", sa.String(64), nullable=True))
    # Existing companies keep every module and no user limit (modules NULL = all).


def downgrade_modules() -> None:
    raise NotImplementedError("Restore the backup of the data folder to go back to an earlier version.")
