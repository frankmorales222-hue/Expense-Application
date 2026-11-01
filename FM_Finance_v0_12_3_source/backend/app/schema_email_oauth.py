"""v0.7.1: sign in to Microsoft 365 to send invoices (no SMTP password). Shared by both branches."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


def upgrade_email_oauth() -> None:
    op.add_column("email_settings", sa.Column("provider", sa.String(10), nullable=False, server_default="smtp"))
    op.add_column("email_settings", sa.Column("oauth_client_id", sa.String(64), nullable=True))
    op.add_column("email_settings", sa.Column("oauth_refresh_encrypted", sa.Text(), nullable=True))
    op.add_column("email_settings", sa.Column("oauth_account", sa.String(255), nullable=True))


def downgrade_email_oauth() -> None:
    raise NotImplementedError("Restore the backup of the data folder to go back to an earlier version.")
