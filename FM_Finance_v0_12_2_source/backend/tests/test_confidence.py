"""v0.12.0 statement reconciliation, audit history and accountant package."""

from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

from .test_banking import make_account


def _approved_charge(c: TestClient, account_id: str, category_id: str, amount: float = -100) -> dict:
    t = c.post("/api/transactions", json={"account_id": account_id, "txn_date": "2026-10-05",
                                          "amount": amount, "description": "October service charge",
                                          "category_id": category_id}).json()
    r = c.post(f"/api/transactions/{t['id']}/approve")
    assert r.status_code == 200, r.text
    return r.json()


def test_reconcile_to_zero_locks_transaction_and_saves_history(auth_client: TestClient, category_id: str) -> None:
    account = make_account(auth_client)
    txn = _approved_charge(auth_client, account["id"], category_id)
    started = auth_client.post("/api/reconciliations", json={
        "account_id": account["id"], "statement_date": "2026-10-31", "ending_balance": 900,
        "notes": "October statement",
    })
    assert started.status_code == 201, started.text
    rec = started.json()
    assert rec["beginning_balance"] == 1000 and rec["difference"] == -100
    saved = auth_client.put(f"/api/reconciliations/{rec['id']}/selection",
                            json={"transaction_ids": [txn["id"]]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["difference"] == 0 and saved.json()["transaction_count"] == 1
    completed = auth_client.post(f"/api/reconciliations/{rec['id']}/complete")
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert auth_client.patch(f"/api/transactions/{txn['id']}", json={"memo": "changed"}).status_code == 409
    history = auth_client.get("/api/reconciliations").json()
    assert history[0]["status"] == "completed" and history[0]["ending_balance"] == 900


def test_out_of_balance_cannot_complete_and_draft_can_be_cancelled(auth_client: TestClient,
                                                                   category_id: str) -> None:
    account = make_account(auth_client)
    _approved_charge(auth_client, account["id"], category_id)
    rec = auth_client.post("/api/reconciliations", json={
        "account_id": account["id"], "statement_date": "2026-10-31", "ending_balance": 850,
    }).json()
    assert auth_client.post(f"/api/reconciliations/{rec['id']}/complete").status_code == 409
    assert auth_client.delete(f"/api/reconciliations/{rec['id']}").status_code == 204
    assert auth_client.get("/api/reconciliations").json() == []


def test_statement_attachment_and_accountant_export(auth_client: TestClient, category_id: str) -> None:
    account = make_account(auth_client)
    txn = _approved_charge(auth_client, account["id"], category_id)
    rec = auth_client.post("/api/reconciliations", json={
        "account_id": account["id"], "statement_date": "2026-10-31", "ending_balance": 900,
    }).json()
    attached = auth_client.post(f"/api/reconciliations/{rec['id']}/statement",
                                files={"file": ("october.pdf", b"%PDF-1.4\nstatement", "application/pdf")})
    assert attached.status_code == 200, attached.text
    assert attached.json()["statement_filename"] == "october.pdf"
    auth_client.put(f"/api/reconciliations/{rec['id']}/selection", json={"transaction_ids": [txn["id"]]})
    auth_client.post(f"/api/reconciliations/{rec['id']}/complete")
    download = auth_client.get(f"/api/reconciliations/{rec['id']}/statement")
    assert download.status_code == 200 and download.content.startswith(b"%PDF")

    package = auth_client.get("/api/accountant/export", params={"date_from": "2026-01-01",
                                                                 "date_to": "2026-12-31"})
    assert package.status_code == 200, package.text
    with zipfile.ZipFile(io.BytesIO(package.content)) as zf:
        names = set(zf.namelist())
        assert {"general_ledger.csv", "trial_balance.csv", "profit_and_loss.csv", "balance_sheet.csv",
                "bank_transactions.csv", "audit_log.csv", "documents/index.json"} <= names
        assert any(name.endswith("october.pdf") for name in names)


def test_audit_history_is_searchable(auth_client: TestClient) -> None:
    make_account(auth_client)
    result = auth_client.get("/api/audit", params={"entity_type": "account"})
    assert result.status_code == 200, result.text
    page = result.json()
    assert page["total"] >= 1 and page["items"][0]["entity_type"] == "account"
    assert page["items"][0]["user_name"]
