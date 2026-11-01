"""v0.9.0: the look (theme) each person chose, and each company's default."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


def upgrade_themes() -> None:
    op.add_column("users", sa.Column("theme", sa.String(20), nullable=True))
    op.add_column("companies", sa.Column("default_theme", sa.String(20), nullable=True))
    # Existing people and companies get the Classic look (NULL = classic).


def downgrade_themes() -> None:
    raise NotImplementedError("Restore the backup of the data folder to go back to an earlier version.")
