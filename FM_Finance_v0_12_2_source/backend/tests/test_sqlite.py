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
        assert revision == ("0026_sqlite_confidence" if db.dialect.name == "sqlite" else "0027_postgresql_confidence")


def test_upgrade_from_v02_database_keeps_data_and_indexes(tmp_path):
    """A SQLite file created by v0.2.x upgrades in place without losing rows or the vendor index."""
    import uuid as _uuid

    from alembic import command
    from alembic.config import Config

    from app.database import create_database_engine
    from app.paths import alembic_dir

    url = f"sqlite:///{tmp_path / 'old.db'}"
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir()))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "0002_sqlite")
    engine = create_database_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO vendors (id, name) VALUES (:i, 'Microsoft')"), {"i": _uuid.uuid4().hex})
    command.upgrade(cfg, "sqlite@head")
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM vendors")) == 1
        assert db.scalar(text("SELECT is_1099 FROM vendors")) in (0, False)
        indexes = {r[1] for r in db.execute(text("PRAGMA index_list('vendors')"))}
        assert "ix_vendors_company_name_lower" in indexes  # vendor names unique per company (v0.5.0)
        checks = db.scalar(text("SELECT sql FROM sqlite_master WHERE name='expense_categories'"))
        assert "ck_categories_threshold" in checks
    engine.dispose()


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
    # auto without MinIO credentials -> local folder storage (v0.3.0)
    assert type(get_storage()).__name__ == "LocalReceiptStorage"
    # Explicitly choosing MinIO without credentials keeps receipts unavailable.
    monkeypatch.setattr(settings, "RECEIPT_STORAGE", "minio")
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


def test_upgrade_from_v041_moves_everything_into_the_existing_company(tmp_path):
    """A v0.4.1 database with real records upgrades into v0.5.0 with nothing lost or orphaned."""
    import uuid as _uuid

    from alembic import command
    from alembic.config import Config

    from app.database import create_database_engine
    from app.paths import alembic_dir

    url = f"sqlite:///{tmp_path / 'v041.db'}"
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir()))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "0008_sqlite_branding")
    engine = create_database_engine(url)
    ids = {k: _uuid.uuid4().hex for k in ("company", "admin", "approver", "cat", "cat2", "vendor", "expense",
                                          "receipt", "account", "txn")}
    with engine.begin() as db:
        x = db.execute
        x(text("INSERT INTO companies (id, name) VALUES (:company, 'F&M IT Services')"), ids)
        x(text("INSERT INTO users (id, email, name, password_hash, role) VALUES "
               "(:admin, 'frank@fmitai.com', 'Francisco', 'h', 'admin'), "
               "(:approver, 'ap@fmitai.com', 'Ap', 'h', 'approver')"), ids)
        x(text("INSERT INTO expense_categories (id, code, name, sort_order) VALUES (:cat, 'meals', 'Meals', 10), "
               "(:cat2, 'software', 'Software', 20)"), ids)
        x(text("INSERT INTO vendors (id, name, default_category_id) VALUES (:vendor, 'Panther Coffee', :cat)"), ids)
        x(text("INSERT INTO expenses (id, expense_date, vendor_id, category_id, description, amount, submitted_by, "
               "invoice_number) VALUES (:expense, '2026-10-06', :vendor, :cat, 'Coffee', 931, :admin, 'R-1')"), ids)
        x(text("INSERT INTO receipts (id, expense_id, object_key, original_filename, content_type, size_bytes) "
               "VALUES (:receipt, :expense, 'k', 'r.pdf', 'application/pdf', 10)"), ids)
        x(text("INSERT INTO audit_log (id, entity_type, entity_id, action) VALUES (:receipt, 'expense', :expense, "
               "'created')"), ids)
        x(text("INSERT INTO financial_accounts (id, company_id, name, kind) VALUES (:account, :company, 'Chase', "
               "'checking')"), ids)
        x(text("INSERT INTO transactions (id, company_id, account_id, source, txn_date, amount, description, "
               "fingerprint, expense_id, category_id, vendor_id) VALUES (:txn, :company, :account, 'csv', "
               "'2026-10-06', -931, 'PANTHER COFFEE', 'fp', :expense, :cat, :vendor)"), ids)
    command.upgrade(cfg, "sqlite@head")
    with engine.connect() as db:
        q = lambda sql: db.execute(text(sql)).all()  # noqa: E731
        company = ids["company"]
        for table in ("expense_categories", "vendors", "expenses", "receipts", "audit_log"):
            assert q(f"SELECT DISTINCT company_id FROM {table}") == [(company,)], table
        assert q("SELECT count(*) FROM expense_categories") == [(2,)]
        assert q("SELECT name, default_category_id FROM vendors") == [("Panther Coffee", ids["cat"])]
        assert q("SELECT amount, invoice_number FROM expenses") == [(931, "R-1")]
        roles = dict(q("SELECT u.email, m.role FROM company_members m JOIN users u ON u.id = m.user_id"))
        assert roles == {"frank@fmitai.com": "owner", "ap@fmitai.com": "bookkeeper"}
        assert dict(q("SELECT email, is_platform_admin FROM users")) == {"frank@fmitai.com": 1, "ap@fmitai.com": 0}
        assert q("SELECT count(*) FROM companies") == [(1,)]
        assert q("PRAGMA foreign_key_check") == []
        assert q("SELECT expense_id FROM transactions") == [(ids["expense"],)]
        cat_sql = q("SELECT sql FROM sqlite_master WHERE name = 'expense_categories'")[0][0]
        assert "ck_categories_threshold" in cat_sql and "uq_categories_company_code" in cat_sql
    with engine.connect() as db:
        assert db.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1  # enforcement back on for the app
    engine.dispose()


def test_upgrade_from_v051_builds_balanced_books(tmp_path):
    """A v0.5.1 database: expenses become one-line expenses, linked ones take the bank account,
    and the startup step builds the journal from the existing records, balanced."""
    import uuid as _uuid

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.orm import Session

    from app.database import create_database_engine
    from app.ledger.books import ensure_books, totals
    from app.models import Expense, ExpenseLine, JournalEntry
    from app.paths import alembic_dir

    url = f"sqlite:///{tmp_path / 'v051.db'}"
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir()))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "0010_sqlite_multicompany")
    engine = create_database_engine(url)
    ids = {k: _uuid.uuid4().hex for k in ("company", "user", "meals", "income", "vendor", "e1", "e2", "acct",
                                          "t1", "t2")}
    with engine.begin() as db:
        x = db.execute
        x(text("INSERT INTO companies (id, name) VALUES (:company, 'F&M IT Services')"), ids)
        x(text("INSERT INTO users (id, email, name, password_hash, role, is_platform_admin) VALUES "
               "(:user, 'f@fmitai.com', 'F', 'h', 'admin', 1)"), ids)
        x(text("INSERT INTO company_members (company_id, user_id, role) VALUES (:company, :user, 'owner')"), ids)
        x(text("INSERT INTO expense_categories (id, company_id, code, name, kind, sort_order) VALUES "
               "(:meals, :company, 'meals', 'Meals', 'expense', 10), "
               "(:income, :company, 'client_services_revenue', 'Client services revenue', 'income', 20)"), ids)
        x(text("INSERT INTO vendors (id, company_id, name) VALUES (:vendor, :company, 'Panther Coffee')"), ids)
        x(text("INSERT INTO financial_accounts (id, company_id, name, kind, opening_balance, opening_date) VALUES "
               "(:acct, :company, 'Chase', 'checking', 500000, '2026-09-01')"), ids)
        # e1 is linked to a bank charge; e2 isn't (no payment account)
        x(text("INSERT INTO expenses (id, company_id, expense_date, vendor_id, category_id, description, amount, "
               "submitted_by, status) VALUES (:e1, :company, '2026-10-06', :vendor, :meals, 'Coffee', 931, :user, "
               "'approved'), (:e2, :company, '2026-10-02', :vendor, :meals, 'Lunch', 2500, :user, 'approved')"), ids)
        x(text("INSERT INTO transactions (id, company_id, account_id, source, txn_date, amount, description, "
               "fingerprint, expense_id, category_id, review_status) VALUES "
               "(:t1, :company, :acct, 'csv', '2026-10-06', -931, 'PANTHER', 'f1', :e1, :meals, 'approved'), "
               "(:t2, :company, :acct, 'csv', '2026-10-03', 240000, 'STRIPE', 'f2', NULL, :income, 'approved')"), ids)
    command.upgrade(cfg, "sqlite@head")
    with Session(engine) as db:
        ensure_books(db)
        company = _uuid.UUID(ids["company"])
        e1 = db.get(Expense, _uuid.UUID(ids["e1"]))
        assert e1.payment_account_id == _uuid.UUID(ids["acct"])  # taken from the linked bank charge
        assert db.get(Expense, _uuid.UUID(ids["e2"])).payment_account_id is None
        assert len(db.query(ExpenseLine).all()) == 2
        debit, credit = totals(db, company)
        assert debit == credit and debit > 0
        kinds = sorted(e.source_type for e in db.query(JournalEntry).all())
        # opening balance, two expenses, the Stripe deposit; the linked Panther charge isn't posted twice
        assert kinds == ["expense", "expense", "opening_balance", "transaction"]
        ensure_books(db)  # runs again on every start: nothing changes
        assert len(db.query(JournalEntry).all()) == 4
    engine.dispose()
