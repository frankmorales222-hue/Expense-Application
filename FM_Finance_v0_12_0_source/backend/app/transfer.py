"""One-time SQLite -> PostgreSQL transfer into an empty destination database."""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from . import audit, models
from .bootstrap import run_migrations
from .database import Base, create_database_engine, database_url


class TransferError(Exception):
    pass


def transfer_to_postgresql(source_url: str, target_url: str) -> dict[str, int]:
    source = make_url(source_url)
    target = make_url(target_url)
    if source.get_backend_name() != "sqlite":
        raise TransferError("The source must be a file-backed SQLite database.")
    if target.get_backend_name() != "postgresql":
        raise TransferError("The destination must be PostgreSQL.")
    source = database_url(source_url)
    if not Path(source.database).is_file():
        raise TransferError("The SQLite source file does not exist.")
    # Alembic creates/updates only the destination schema, never seeds users/categories.
    run_migrations(target_url)
    src_engine = create_database_engine(source.render_as_string(hide_password=False))
    dst_engine = create_database_engine(target_url)
    tables = list(Base.metadata.sorted_tables)
    counts: dict[str, int] = {}
    try:
        with src_engine.connect() as src, dst_engine.begin() as dst:
            # Quiesce SQLite writers for a consistent snapshot throughout the copy.
            src.exec_driver_sql("BEGIN IMMEDIATE")
            # Prevent concurrent application writes/check-then-insert races at target.
            names = ", ".join(dst.dialect.identifier_preparer.quote(t.name) for t in tables)
            dst.exec_driver_sql(f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE")
            for table in tables:
                if dst.scalar(select(func.count()).select_from(table)):
                    raise TransferError("Destination contains application records. Use an empty PostgreSQL database.")
            if not src.scalar(select(func.count()).select_from(models.User.__table__)):
                raise TransferError("Source has no users. Start and test the SQLite application before transferring.")
            self_refs = {"transactions": ("transfer_peer_id", "duplicate_of_id")}
            for table in tables:
                count = 0
                deferred: list[dict] = []
                refs = self_refs.get(table.name, ())
                result = src.execute(select(table)).mappings()
                while batch := result.fetchmany(200):
                    # SQLAlchemy converts SQLite integer cents back to Decimal, then
                    # binds Decimal into PostgreSQL NUMERIC without losing precision.
                    rows = [dict(row) for row in batch]
                    for row in rows:
                        # Rows that point at each other are linked after all of them exist.
                        links = {c: row.pop(c) for c in refs if row.get(c) is not None}
                        if links:
                            deferred.append({"_id": row["id"], **links})
                        for c in refs:
                            row.setdefault(c, None)
                    dst.execute(table.insert(), rows)
                    count += len(batch)
                for link in deferred:
                    row_id = link.pop("_id")
                    dst.execute(table.update().where(table.c.id == row_id).values(**link))
                counts[table.name] = count
                if dst.scalar(select(func.count()).select_from(table)) != count:
                    raise TransferError(f"Row count mismatch for {table.name}; copy rolled back.")
            for column in (models.Expense.amount, models.BankTransaction.amount, models.Transaction.amount,
                           models.FinancialAccount.opening_balance):
                if src.scalar(select(func.sum(column))) != dst.scalar(select(func.sum(column))):
                    raise TransferError("Money totals do not match; copy rolled back.")
            with Session(bind=dst) as db:
                audit.record(db, entity_type="database", entity_id=uuid.uuid4(), action="sqlite_transferred",
                             user_id=None, changes={"table_counts": counts})
                db.flush()  # commit belongs to the outer destination transaction
            src.rollback()
    finally:
        src_engine.dispose()
        dst_engine.dispose()
    return counts
