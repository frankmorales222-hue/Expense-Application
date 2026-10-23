"""v0.11.0 owner money: plain-language workflow backed by balanced ledger entries."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import make_expense


def bank(c: TestClient, *, opening: float = 0) -> dict:
    response = c.post("/api/accounts", json={
        "name": "Business Checking", "kind": "checking", "institution": "Test Bank",
        "last4": "1234", "opening_balance": opening, "opening_date": "2026-10-01",
    })
    assert response.status_code == 201, response.text
    return response.json()


def record(c: TestClient, action: str, amount: float, account_id: str | None = None,
           transaction_id: str | None = None) -> dict:
    response = c.post("/api/owner-funds", json={
        "action": action, "entry_date": "2026-10-08", "amount": amount,
        "account_id": account_id, "transaction_id": transaction_id,
        "memo": "Owner funding test",
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_owner_loan_and_partial_repayment_are_not_profit(auth_client: TestClient) -> None:
    account = bank(auth_client)
    summary = record(auth_client, "loan", 1000, account["id"])
    assert summary["loan_balance"] == 1000
    assert summary["reimbursement_balance"] == 0

    summary = record(auth_client, "repayment", 900, account["id"])
    assert summary["loan_balance"] == 100
    assert summary["total_owed"] == 100
    assert sorted(row["change"] for row in summary["activity"]) == [-900, 1000]

    dashboard = auth_client.get("/api/dashboard/overview").json()
    assert dashboard["cash_total"] == 100
    assert dashboard["owner_loan_balance"] == 100
    assert dashboard["owner_total_owed"] == 100
    assert dashboard["income_ytd"] == 0 and dashboard["expenses_ytd"] == 0
    assert auth_client.get("/api/ledger/status").json()["balanced"] is True

    transactions = auth_client.get("/api/transactions", params={"tab": "all"}).json()["items"]
    assert len(transactions) == 2
    assert all(t["allocation_account_name"] == "Due to Owner" for t in transactions)
    assert all(t["receipt_status"] == "not_needed" for t in transactions)

    too_much = auth_client.post("/api/owner-funds", json={
        "action": "repayment", "entry_date": "2026-10-09", "amount": 100.01,
        "account_id": account["id"],
    })
    assert too_much.status_code == 409


def test_existing_bank_transaction_is_used_once(auth_client: TestClient) -> None:
    account = bank(auth_client)
    transaction = auth_client.post("/api/transactions", json={
        "account_id": account["id"], "txn_date": "2026-10-08", "amount": 1000,
        "description": "OWNER TRANSFER",
    }).json()
    summary = record(auth_client, "loan", 1000, transaction_id=transaction["id"])
    assert summary["loan_balance"] == 1000
    page = auth_client.get("/api/transactions", params={"tab": "all"}).json()
    assert page["total"] == 1
    assert page["items"][0]["review_status"] == "approved"
    assert page["items"][0]["allocation_account_name"] == "Due to Owner"


def test_opening_balance_reclassification_does_not_change_cash(auth_client: TestClient) -> None:
    bank(auth_client, opening=1000)
    before = auth_client.get("/api/dashboard/overview").json()
    summary = record(auth_client, "opening_balance", 1000)
    after = auth_client.get("/api/dashboard/overview").json()
    assert before["cash_total"] == after["cash_total"] == 1000
    assert summary["loan_balance"] == 1000
    chart = auth_client.get("/api/ledger/accounts").json()
    assert next(a for a in chart if a["system_key"] == "opening_balance_equity")["balance"] == 0


def test_owner_page_combines_loan_and_personal_reimbursements(
        auth_client: TestClient, category_id: str) -> None:
    account = bank(auth_client)
    record(auth_client, "loan", 100, account["id"])
    make_expense(auth_client, category_id, amount=25.50, is_reimbursable=True)
    summary = auth_client.get("/api/owner-funds").json()
    assert summary["loan_balance"] == 100
    assert summary["reimbursement_balance"] == 25.50
    assert summary["total_owed"] == 125.50
    dashboard = auth_client.get("/api/dashboard/overview").json()
    assert dashboard["owner_reimbursements"] == 25.50
    assert dashboard["owner_total_owed"] == 125.50
