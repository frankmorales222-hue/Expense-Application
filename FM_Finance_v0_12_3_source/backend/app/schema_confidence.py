"""v0.12.0 reconciliation and accountant-review schema."""

from alembic import op
import sqlalchemy as sa

from .types import CurrencyAmount, UTCDateTime


def upgrade_confidence() -> None:
    op.create_table(
        "reconciliations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("financial_accounts.id"), nullable=False),
        sa.Column("statement_date", sa.Date(), nullable=False),
        sa.Column("beginning_balance", CurrencyAmount(), nullable=False),
        sa.Column("ending_balance", CurrencyAmount(), nullable=False),
        sa.Column("cleared_balance", CurrencyAmount(), nullable=False, server_default="0"),
        sa.Column("difference", CurrencyAmount(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("statement_object_key", sa.String(500), nullable=True),
        sa.Column("statement_filename", sa.String(255), nullable=True),
        sa.Column("statement_content_type", sa.String(100), nullable=True),
        sa.Column("statement_size_bytes", sa.Integer(), nullable=True),
        sa.Column("started_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("completed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", UTCDateTime(), nullable=True),
        sa.UniqueConstraint("company_id", "account_id", "statement_date", name="uq_reconciliation_statement"),
    )
    op.create_index("ix_reconciliations_company_account", "reconciliations", ["company_id", "account_id"])
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("reconciliation_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_transactions_reconciliation", "reconciliations", ["reconciliation_id"],
                                 ["id"], ondelete="SET NULL")
        batch.create_index("ix_transactions_reconciliation", ["reconciliation_id"])


def downgrade_confidence() -> None:
    raise NotImplementedError("Restore a v0.11.0 backup to go back to an earlier version.")
