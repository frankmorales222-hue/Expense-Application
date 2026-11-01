"""v0.11.0 owner-funds workflow.

Bank transactions used for loans and repayments post directly to a balance-sheet account. The Due to Owner
account itself is created or adopted by ``ledger.chart.ensure_chart`` so existing companies keep their history.
"""

from alembic import op
import sqlalchemy as sa


def upgrade_owner_funds() -> None:
    # SQLite must rebuild the table to add a foreign key; PostgreSQL uses the same migration safely.
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column(
            "allocation_account_id", sa.Uuid(),
            sa.ForeignKey("ledger_accounts.id", name="fk_transactions_allocation_account"), nullable=True))
        batch.create_index("ix_transactions_allocation_account", ["allocation_account_id"])


def downgrade_owner_funds() -> None:
    raise NotImplementedError("Restore a v0.10.1 backup to go back to an earlier version.")
