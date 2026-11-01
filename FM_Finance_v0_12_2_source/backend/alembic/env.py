"""Alembic environment. The URL comes from app settings (.env), never from alembic.ini."""

from __future__ import annotations

from alembic import context
from app.config import get_settings
from app.database import Base, create_database_engine, database_url
from app import models  # noqa: F401  (registers models on Base.metadata)

target_metadata = Base.metadata
url = context.config.attributes.get("database_url", get_settings().DATABASE_URL)


def run_migrations_offline() -> None:
    context.configure(url=database_url(url), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_database_engine(url)
    with engine.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            # Table rebuilds (drop + rename) need foreign-key enforcement off; SQLite ignores this
            # pragma inside a transaction, so it is set first. Integrity is re-checked below.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=sqlite)
        with context.begin_transaction():
            context.run_migrations()
            if sqlite:
                problems = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if problems:
                    raise RuntimeError(f"Migration left broken references; restore the data folder backup: {problems[:5]}")
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
