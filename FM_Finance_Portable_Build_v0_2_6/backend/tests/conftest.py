"""Test setup. Runs against a real PostgreSQL test database (it is wiped).

Set TEST_DATABASE_URL to point at a disposable database, e.g.
  postgresql+psycopg2://fm_user:password@localhost:5432/fm_finance_test
"""

from __future__ import annotations

import os
from pathlib import Path
from collections.abc import Iterator

import pytest

TEST_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_URL:
    raise RuntimeError("Set TEST_DATABASE_URL to a disposable SQLite file or PostgreSQL database. Tests erase its data.")
os.environ["DATABASE_URL"] = TEST_URL
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 48
os.environ["APP_ENV"] = "development"
os.environ["ADMIN_EMAIL"] = "admin@test.local"
os.environ["ADMIN_NAME"] = "Test Admin"
os.environ["ADMIN_INITIAL_PASSWORD"] = "Admin-Password-123"
os.environ["APPROVAL_REQUIRED"] = "false"
os.environ["LOG_DIR"] = os.path.join(os.path.dirname(__file__), ".logs")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.bootstrap import ensure_admin, run_migrations, seed_categories  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import database_url, get_engine, get_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402
from app.security import login_throttle  # noqa: E402
from app.storage import StorageUnavailable, get_storage  # noqa: E402

ADMIN = {"email": "admin@test.local", "password": "Admin-Password-123"}


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.available = True

    def _check(self) -> None:
        if not self.available:
            raise StorageUnavailable("down")

    def ensure_bucket(self) -> None:
        self._check()

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._check()
        self.objects[key] = (data, content_type)

    def open(self, key: str) -> Iterator[bytes]:
        self._check()
        return iter([self.objects[key][0]])

    def delete(self, key: str) -> None:
        self._check()
        self.objects.pop(key, None)

    def ping(self) -> bool:
        return self.available


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    if make_url(TEST_URL).get_backend_name() == "sqlite":
        path = Path(database_url(TEST_URL).database)
        if path.exists():
            path.unlink()
        for suffix in ("-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)
    else:
        with get_engine().begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    run_migrations()
    with get_session_factory()() as db:
        ensure_admin(db, get_settings())
        seed_categories(db)


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    yield
    with get_engine().begin() as conn:
        if conn.dialect.name == "sqlite":
            for table in ("receipts", "audit_log", "bank_transactions", "expenses", "vendors"):
                conn.execute(text(f"DELETE FROM {table}"))
        else:
            conn.execute(text("TRUNCATE receipts, audit_log, bank_transactions, expenses, vendors CASCADE"))
        conn.execute(text("UPDATE expense_categories SET approval_threshold = NULL, is_active = true"))
        conn.execute(text("DELETE FROM expense_categories WHERE code NOT IN (SELECT code FROM expense_categories "
                          "ORDER BY sort_order LIMIT 15)"))
    login_throttle._failures.clear()


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def client(storage: FakeStorage) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_client(client: TestClient) -> TestClient:
    r = client.post("/api/auth/login", json=ADMIN)
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def category_id(auth_client: TestClient) -> str:
    cats = auth_client.get("/api/categories").json()
    return next(c["id"] for c in cats if c["code"] == "software_licenses")


def make_expense(c: TestClient, category_id: str, **overrides: object) -> dict:
    body = {
        "expense_date": "2026-10-01",
        "vendor_name": "Microsoft",
        "category_id": category_id,
        "description": "Microsoft 365 Business Standard",
        "amount": 12.50,
        "payment_method": "business_card",
        "is_reimbursable": False,
        "notes": None,
    }
    body.update(overrides)
    r = c.post("/api/expenses", json=body)
    assert r.status_code == 201, r.text
    return r.json()
