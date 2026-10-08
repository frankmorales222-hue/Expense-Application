"""Database compatibility and exact-money regression checks."""

from decimal import Decimal
from pathlib import Path
import io

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.bootstrap import run_migrations
from app.config import get_settings
from app.database import database_url, get_engine, get_session_factory
from app.models import AuditLog, Expense
from app.paths import alembic_dir
from app.storage import StorageUnavailable, get_storage
from app.transfer import TransferError, transfer_to_postgresql

from .conftest import make_expense


def require_sqlite():
    if get_engine().dialect.name != "sqlite":
        pytest.skip("SQLite-specific check")


def test_sqlite_money_stored_as_cents_and_exact_totals(auth_client, category_id):
    require_sqlite()
    values = [Decimal("0.10"), Decimal("0.20"), Decimal("9999999999.99"), Decimal("9999999999.99")]
    for value in values:
        make_expense(auth_client, category_id, amount=str(value))
    with get_engine().connect() as db:
        raw = db.execute(text("SELECT amount, typeof(amount) FROM expenses ORDER BY amount")).all()
        assert raw == [(10, "integer"), (20, "integer"), (999999999999, "integer"), (999999999999, "integer")]
    with get_session_factory()() as db:
        assert db.scalar(select(func.sum(Expense.amount))) == sum(values)
    page = auth_client.get("/api/expenses").json()
    summary = auth_client.get("/api/reports/summary").json()
    assert Decimal(str(page["total_amount"])) == sum(values)
    assert Decimal(str(summary["total_spent"])) == sum(values)


def test_sqlite_foreign_keys_enforced():
    require_sqlite()
    with get_engine().connect() as db:
        assert db.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    with pytest.raises(IntegrityError), get_engine().begin() as db:
        db.execute(text("INSERT INTO receipts (id, expense_id, object_key, original_filename, content_type, size_bytes) "
                        "VALUES ('11111111111111111111111111111111', '22222222222222222222222222222222', "
                        "'missing', 'missing.pdf', 'application/pdf', 1)"))


def test_restart_migrations_preserves_expense(auth_client, category_id):
    e = make_expense(auth_client, category_id)
    run_migrations()
    assert auth_client.get(f"/api/expenses/{e['id']}").json()["amount"] == 12.5
    with get_engine().connect() as db:
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == ("0002_sqlite" if db.dialect.name == "sqlite" else "0003_postgresql")


def test_audit_timestamps_remain_utc(auth_client, category_id):
    make_expense(auth_client, category_id)
    with get_session_factory()() as db:
        entry = db.scalar(select(AuditLog))
        assert entry.created_at.tzinfo is not None
        assert entry.created_at.utcoffset().total_seconds() == 0


def test_sqlite_file_path_does_not_follow_working_directory(tmp_path, monkeypatch):
    expected = database_url("sqlite:///data/path-check.db").database
    monkeypatch.chdir(tmp_path)
    assert database_url("sqlite:///data/path-check.db").database == expected
    assert Path(expected).is_absolute()


def test_local_testing_without_minio_credentials(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "MINIO_ACCESS_KEY", "")
    monkeypatch.setattr(settings, "MINIO_SECRET_KEY", "")
    store = get_storage()
    assert store.ping() is False
    with pytest.raises(StorageUnavailable):
        store.put("private", b"%PDF", "application/pdf")
    client.app.dependency_overrides[get_storage] = lambda: store
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert health.json()["database"] == "ok"


def test_transfer_rejects_non_postgresql_target(tmp_path):
    with pytest.raises(TransferError, match="destination must be PostgreSQL"):
        transfer_to_postgresql(f"sqlite:///{tmp_path / 'source.db'}", "sqlite:///wrong-destination.db")


def test_transfer_missing_source_does_not_create_database(tmp_path):
    source = tmp_path / "missing.db"
    with pytest.raises(TransferError, match="source file does not exist"):
        transfer_to_postgresql(f"sqlite:///{source}", "postgresql+psycopg2://unused:unused@localhost/unused")
    assert not source.exists()


def test_monthly_report_keeps_date_boundaries_and_zero_months(auth_client, category_id):
    make_expense(auth_client, category_id, expense_date="2026-01-31", amount="0.10")
    make_expense(auth_client, category_id, expense_date="2026-02-01", amount="0.20")
    months = auth_client.get("/api/reports/summary", params={"date_to": "2026-02-28"}).json()["by_month"]
    assert len(months) == 12
    by_key = {r["key"]: r["amount"] for r in months}
    assert by_key["2026-01"] == 0.1
    assert by_key["2026-02"] == 0.2
    assert by_key["2025-03"] == 0


def test_postgresql_migration_sql_keeps_native_money_and_jsonb():
    output = io.StringIO()
    config = Config(output_buffer=output)
    config.set_main_option("script_location", str(alembic_dir()))
    config.attributes["database_url"] = "postgresql+psycopg2://unused:unused@localhost/unused"
    command.upgrade(config, "postgresql@head", sql=True)
    ddl = output.getvalue()
    assert "NUMERIC(12, 2)" in ddl
    assert "changes JSONB" in ddl
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in ddl
    assert "0003_postgresql" in ddl
    assert "0002_sqlite" not in ddl
