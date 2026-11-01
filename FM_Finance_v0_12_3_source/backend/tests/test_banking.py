"""Phase 1 banking: import, duplicates, transfers, suggestions, approval, undo."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

CHECKING_CSV = b"""Date,Description,Amount,Running Bal.
10/01/2026,SQ *BLUE BOTTLE COFFEE Miami FL,-6.50,993.50
10/02/2026,MICROSOFT*365 BUSINESS 800-642-7676 WA,-12.50,981.00
10/02/2026,MICROSOFT*365 BUSINESS 800-642-7676 WA,-12.50,968.50
10/03/2026,ONLINE TRANSFER TO CREDIT CARD 4417,-200.00,768.50
10/04/2026,STRIPE TRANSFER ST-ABC123,1500.00,2268.50
"""

# Credit card export where purchases are positive (needs inverting) and the payment is negative.
CARD_CSV = b"""Transaction Date,Post Date,Description,Amount
10/03/2026,10/04/2026,PAYMENT THANK YOU,-200.00
10/05/2026,10/06/2026,AMAZON WEB SERVICES AWS.AMAZON.CO WA,45.10
10/06/2026,10/07/2026,UBER *EATS PENDING,23.00
"""

OFX = b"""OFXHEADER:100
DATA:OFXSGML
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>USD<BANKACCTFROM><ACCTID>000123457788</BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261010120000[-5:EST]<TRNAMT>-49.99<FITID>A1<NAME>COMCAST CABLE<MEMO>800-COMCAST</STMTTRN>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261011<TRNAMT>0.42<FITID>A2<NAME>INTEREST PAYMENT</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""


def make_account(c: TestClient, name: str = "Chase Business Checking", kind: str = "checking") -> dict:
    r = c.post("/api/accounts", json={"name": name, "kind": kind, "institution": "Chase", "last4": "7788",
                                      "opening_balance": 1000})
    assert r.status_code == 201, r.text
    return r.json()


def do_import(c: TestClient, account_id: str, data: bytes, name: str = "stmt.csv", mapping: dict | None = None):
    form = {"account_id": account_id}
    if mapping is not None:
        form["mapping"] = json.dumps(mapping)
    return c.post("/api/imports", data=form, files={"file": (name, data, "text/csv")})


def txns(c: TestClient, **params) -> dict:
    r = c.get("/api/transactions", params={"tab": "all", **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_company_and_account_balance(auth_client: TestClient) -> None:
    assert auth_client.get("/api/company").json()["name"]
    acct = make_account(auth_client)
    assert acct["balance"] == 1000
    assert auth_client.post("/api/accounts", json={"name": "chase business checking", "kind": "checking"}).status_code == 409


def test_csv_preview_guesses_mapping(auth_client: TestClient) -> None:
    acct = make_account(auth_client)
    r = auth_client.post("/api/imports/preview", data={"account_id": acct["id"]},
                         files={"file": ("stmt.csv", CHECKING_CSV, "text/csv")})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["source"] == "csv" and p["valid_rows"] == 5 and not p["problems"]
    assert p["mapping"]["date_column"] == 0 and p["mapping"]["amount_column"] == 2
    assert p["money_in"] == 1500 and p["money_out"] == 231.5


def test_import_dedup_on_reimport_keeps_legit_repeats(auth_client: TestClient) -> None:
    acct = make_account(auth_client)
    r = do_import(auth_client, acct["id"], CHECKING_CSV)
    assert r.status_code == 201, r.text
    assert r.json()["rows_imported"] == 5  # both identical Microsoft charges are kept
    again = do_import(auth_client, acct["id"], CHECKING_CSV).json()
    assert again["rows_imported"] == 0 and again["rows_duplicate"] == 5
    assert txns(auth_client)["total"] == 5
    # balance = opening + net of the file
    acct2 = next(a for a in auth_client.get("/api/accounts").json() if a["id"] == acct["id"])
    assert acct2["balance"] == 1000 - 231.5 + 1500


def test_transfer_matching_and_card_inversion(auth_client: TestClient) -> None:
    chk = make_account(auth_client)
    card = make_account(auth_client, "Amex Business", "credit_card")
    do_import(auth_client, chk["id"], CHECKING_CSV)
    r = do_import(auth_client, card["id"], CARD_CSV)
    assert r.status_code == 201, r.text
    card_txns = txns(auth_client, account_id=card["id"])["items"]
    amounts = sorted(t["amount"] for t in card_txns)
    assert amounts == [-45.10, -23.00, 200.00]  # purchases are money out, payment is money in
    payment = next(t for t in card_txns if t["amount"] == 200)
    assert payment["is_transfer"] and payment["transfer_peer"]["account_id"] == chk["id"]
    assert payment["confidence"] >= 90
    # Approving one side approves both; no category needed.
    r = auth_client.post(f"/api/transactions/{payment['id']}/approve")
    assert r.status_code == 200, r.text
    peer = auth_client.get("/api/transactions", params={"tab": "approved", "account_id": chk["id"]}).json()
    assert peer["total"] == 1 and peer["items"][0]["is_transfer"]


def test_suggestions_learning_and_bulk(auth_client: TestClient) -> None:
    acct = make_account(auth_client)
    do_import(auth_client, acct["id"], CHECKING_CSV)
    items = txns(auth_client)["items"]
    coffee = next(t for t in items if "BLUE BOTTLE" in t["description"])
    assert coffee["suggested_category_name"] == "Meals" and coffee["confidence"] == 50
    stripe = next(t for t in items if t["amount"] == 1500)
    assert stripe["suggested_category_name"] == "Client services revenue"

    ms = [t for t in items if "MICROSOFT" in t["description"]]
    cats = auth_client.get("/api/categories").json()
    cloud = next(c["id"] for c in cats if c["code"] == "cloud_hosting")
    r = auth_client.patch(f"/api/transactions/{ms[0]['id']}", json={"category_id": cloud, "vendor_name": "Microsoft"})
    assert r.status_code == 200
    assert auth_client.post(f"/api/transactions/{ms[0]['id']}/approve").status_code == 200
    # The identical charge now follows what was learned.
    other = auth_client.get("/api/transactions", params={"tab": "review", "search": "MICROSOFT"}).json()["items"][0]
    assert other["suggested_category_id"] == cloud and other["confidence"] >= 75
    assert other["suggested_vendor_name"] == "Microsoft"

    r = auth_client.post("/api/transactions/approve-confident", json={"min_confidence": 75})
    assert r.status_code == 200 and r.json()["approved"] >= 1


def test_approve_requires_category(auth_client: TestClient) -> None:
    acct = make_account(auth_client)
    r = auth_client.post("/api/transactions", json={"account_id": acct["id"], "txn_date": "2026-10-01",
                                                    "amount": -10, "description": "ZZQX UNKNOWN THING"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["confidence"] == 0
    r = auth_client.post(f"/api/transactions/{t['id']}/approve")
    assert r.status_code == 422


def test_possible_duplicate_across_imports(auth_client: TestClient) -> None:
    acct = make_account(auth_client)
    do_import(auth_client, acct["id"], b"Date,Description,Amount\n10/01/2026,COMCAST CABLE,-49.99\n")
    r = do_import(auth_client, acct["id"], b"Date,Description,Amount\n10/02/2026,COMCAST CABLE COMM,-49.99\n",
                  name="second.csv")
    assert r.json()["rows_flagged"] == 1
    flagged = auth_client.get("/api/transactions", params={"tab": "review", "flag": "duplicate"}).json()["items"]
    assert len(flagged) == 1
    r = auth_client.post(f"/api/transactions/{flagged[0]['id']}/not-duplicate")
    assert r.json()["duplicate_of"] is None


def test_ofx_import_uses_fitid(auth_client: TestClient) -> None:
    acct = make_account(auth_client)
    r = do_import(auth_client, acct["id"], OFX, name="stmt.qfx")
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "ofx" and r.json()["rows_imported"] == 2
    assert do_import(auth_client, acct["id"], OFX, name="stmt.qfx").json()["rows_duplicate"] == 2
    items = txns(auth_client)["items"]
    interest = next(t for t in items if t["amount"] == 0.42)
    assert interest["suggested_category_name"] == "Interest income"
    comcast = next(t for t in items if t["amount"] == -49.99)
    assert comcast["suggested_category_name"] == "Internet & Phone"


def test_undo_import(auth_client: TestClient) -> None:
    chk = make_account(auth_client)
    card = make_account(auth_client, "Amex Business", "credit_card")
    do_import(auth_client, chk["id"], CHECKING_CSV)
    batch = do_import(auth_client, card["id"], CARD_CSV).json()
    r = auth_client.post(f"/api/imports/{batch['id']}/undo")
    assert r.status_code == 200 and r.json()["status"] == "undone"
    assert txns(auth_client, account_id=card["id"])["total"] == 0
    # The checking-side transfer is released back to normal review.
    transfer = next(t for t in txns(auth_client, account_id=chk["id"])["items"] if t["amount"] == -200)
    assert not transfer["is_transfer"]


def test_undo_blocked_when_approved(auth_client: TestClient) -> None:
    acct = make_account(auth_client)
    batch = do_import(auth_client, acct["id"], CHECKING_CSV).json()
    coffee = next(t for t in txns(auth_client)["items"] if "BLUE BOTTLE" in t["description"])
    auth_client.post(f"/api/transactions/{coffee['id']}/approve")
    assert auth_client.post(f"/api/imports/{batch['id']}/undo").status_code == 409


def test_create_expense_from_transaction_and_receipt_status(auth_client: TestClient) -> None:
    acct = make_account(auth_client)
    do_import(auth_client, acct["id"], CHECKING_CSV)
    coffee = next(t for t in txns(auth_client)["items"] if "BLUE BOTTLE" in t["description"])
    assert coffee["receipt_status"] == "missing"
    r = auth_client.post(f"/api/transactions/{coffee['id']}/create-expense")
    assert r.status_code == 201, r.text
    exp = r.json()
    assert exp["amount"] == 6.5 and exp["category_name"] == "Meals"
    up = auth_client.post(f"/api/expenses/{exp['id']}/receipts",
                          files={"file": ("r.pdf", b"%PDF-1.4\n", "application/pdf")})
    assert up.status_code == 201
    coffee = next(t for t in txns(auth_client)["items"] if "BLUE BOTTLE" in t["description"])
    assert coffee["receipt_status"] == "attached"


def test_manual_link_and_unlink_transfer(auth_client: TestClient) -> None:
    a = make_account(auth_client, "Savings", "savings")
    b = make_account(auth_client)
    t1 = auth_client.post("/api/transactions", json={"account_id": a["id"], "txn_date": "2026-10-01",
                                                     "amount": -300, "description": "Move money"}).json()
    t2 = auth_client.post("/api/transactions", json={"account_id": b["id"], "txn_date": "2026-10-09",
                                                     "amount": 300, "description": "Deposit"}).json()
    cands = auth_client.get(f"/api/transactions/{t1['id']}/candidates").json()
    assert [c["id"] for c in cands["transfers"]] == [t2["id"]]
    r = auth_client.post(f"/api/transactions/{t1['id']}/link-transfer", json={"peer_id": t2["id"]})
    assert r.status_code == 200 and r.json()["is_transfer"]
    r = auth_client.post(f"/api/transactions/{t1['id']}/unlink-transfer")
    assert r.status_code == 200 and not r.json()["is_transfer"]


def test_exclude_and_restore(auth_client: TestClient) -> None:
    acct = make_account(auth_client)
    do_import(auth_client, acct["id"], CHECKING_CSV)
    t = txns(auth_client)["items"][0]
    assert auth_client.post(f"/api/transactions/{t['id']}/exclude").json()["review_status"] == "excluded"
    page = auth_client.get("/api/transactions", params={"tab": "review"}).json()
    assert page["counts"] == {"review": 4, "approved": 0, "excluded": 1}
    assert auth_client.post(f"/api/transactions/{t['id']}/restore").json()["review_status"] == "unreviewed"


def test_bad_mapping_reports_problem(auth_client: TestClient) -> None:
    acct = make_account(auth_client)
    weird = b"When,What,How much\n2026-10-01,Thing,-5\n"
    r = auth_client.post("/api/imports/preview", data={"account_id": acct["id"]},
                         files={"file": ("x.csv", weird, "text/csv")})
    assert r.status_code == 200 and r.json()["problems"]
    mapping = {"date_column": 0, "description_column": 1, "amount_column": 2}
    r = do_import(auth_client, acct["id"], weird, mapping=mapping)
    assert r.status_code == 201, r.text
    assert r.json()["rows_imported"] == 1


def test_password_change_signs_out_other_sessions(client: TestClient) -> None:
    from .conftest import ADMIN

    assert client.post("/api/auth/login", json=ADMIN).status_code == 200
    old_cookie = client.cookies.get("fm_session")
    r = client.post("/api/auth/change-password",
                    json={"current_password": ADMIN["password"], "new_password": "Another-Pass-789"})
    assert r.status_code == 204
    assert client.get("/api/auth/me").status_code == 200  # this session got a fresh cookie
    client.cookies.set("fm_session", old_cookie)
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.clear()
    client.post("/api/auth/login", json={"email": ADMIN["email"], "password": "Another-Pass-789"})
    assert client.post("/api/auth/change-password",
                       json={"current_password": "Another-Pass-789", "new_password": ADMIN["password"]}).status_code == 204


def test_banking_requires_approver(client: TestClient) -> None:
    assert client.get("/api/transactions").status_code == 401


def test_saved_profile_ignored_for_different_layout(auth_client: TestClient) -> None:
    acct = make_account(auth_client)
    do_import(auth_client, acct["id"], CHECKING_CSV)  # saves a single-amount profile
    split = b"Posting Date,Description,Debit,Credit\n10/04/2026,ADOBE *CREATIVE CLOUD,59.99,\n10/05/2026,DEPOSIT,,950.00\n"
    r = auth_client.post("/api/imports/preview", data={"account_id": acct["id"]},
                         files={"file": ("other.csv", split, "text/csv")})
    p = r.json()
    assert p["mapping"]["debit_column"] == 2 and p["mapping"]["credit_column"] == 3
    assert p["money_out"] == 59.99 and p["money_in"] == 950 and p["invalid_rows"] == 0
    # The same layout as the saved profile still reuses it.
    r = auth_client.post("/api/imports/preview", data={"account_id": acct["id"]},
                         files={"file": ("again.csv", CHECKING_CSV, "text/csv")})
    assert r.json()["mapping"]["amount_column"] == 2
