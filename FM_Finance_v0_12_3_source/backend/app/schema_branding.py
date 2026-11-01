"""v0.4.1 company branding (logo), shared by the SQLite and PostgreSQL branches."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from .types import UTCDateTime


def upgrade_branding() -> None:
    op.add_column("companies", sa.Column("logo_data", sa.LargeBinary(), nullable=True))
    op.add_column("companies", sa.Column("logo_content_type", sa.String(50), nullable=True))
    op.add_column("companies", sa.Column("logo_updated_at", UTCDateTime(), nullable=True))


def downgrade_branding() -> None:
    for column in ("logo_updated_at", "logo_content_type", "logo_data"):
        op.drop_column("companies", column)
