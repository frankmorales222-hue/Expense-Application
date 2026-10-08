"""Optional real PostgreSQL destination integration test (disposable DB only)."""

import os

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import create_database_engine, get_engine, get_session_factory
from app.models import AuditLog, Expense, Receipt, User
from app.transfer import TransferError, transfer_to_postgresql

from .conftest import make_expense


def test_transfer_to_real_postgresql_preserves_records(auth_client, category_id):
    target = os.environ.get("POSTGRES_TRANSFER_TEST_URL")
    if not target or get_engine().dialect.name != "sqlite":
        pytest.skip("Needs SQLite test source and disposable POSTGRES_TRANSFER_TEST_URL")
    destination = create_database_engine(target)
    try:
        with destination.begin() as db:
            db.execute(text("DROP SCHEMA public CASCADE"))
            db.execute(text("CREATE SCHEMA public"))
        e = make_expense(auth_client, category_id, amount="19.99", is_reimbursable=True)
        r = auth_client.post(f"/api/expenses/{e['id']}/receipts",
                             files={"file": ("invoice.pdf", b"%PDF-1.4\n", "application/pdf")})
        assert r.status_code == 201
        with get_session_factory()() as db:
            old_hash = db.scalar(select(User.password_hash))
            receipt_key = db.scalar(select(Receipt.object_key))
        counts = transfer_to_postgresql(str(get_engine().url), target)
        assert counts["expenses"] == 1
        assert counts["receipts"] == 1
        with Session(destination) as db:
            assert str(db.scalar(select(Expense.id))) == e["id"]
            assert str(db.scalar(select(Expense.amount))) == "19.99"
            assert db.scalar(select(User.password_hash)) == old_hash
            assert db.scalar(select(Receipt.object_key)) == receipt_key
            actions = list(db.scalars(select(AuditLog.action)))
            assert {"created", "receipt_added", "sqlite_transferred"}.issubset(actions)
        with pytest.raises(TransferError, match="Destination contains"):
            transfer_to_postgresql(str(get_engine().url), target)
        assert auth_client.get(f"/api/expenses/{e['id']}").status_code == 200
    finally:
        destination.dispose()
