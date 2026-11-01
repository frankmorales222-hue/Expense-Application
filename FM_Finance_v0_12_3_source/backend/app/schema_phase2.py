"""v0.4.0 (bill import) schema, shared by the SQLite and PostgreSQL branches."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


def upgrade_phase2() -> None:
    op.add_column("expenses", sa.Column("invoice_number", sa.String(100), nullable=True))
    op.add_column("expenses", sa.Column("due_date", sa.Date(), nullable=True))
    op.create_index("ix_expenses_invoice_number", "expenses", ["invoice_number"])


def downgrade_phase2() -> None:
    op.drop_index("ix_expenses_invoice_number", table_name="expenses")
    op.drop_column("expenses", "due_date")
    op.drop_column("expenses", "invoice_number")
