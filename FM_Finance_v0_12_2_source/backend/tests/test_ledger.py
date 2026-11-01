"""v0.6.0 accounting engine: posting rules, balancing, bills, closing date, reports, rebuild."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from .test_banking import CARD_CSV, CHECKING_CSV, do_import, make_account
from .test_multicompany import login, new_company, switch


# ---------------------------------------------------------------- helpers
def cats(c: TestClient) -> dict[str, str]:
    return {x["code"]: x["id"] for x in c.get("/api/categories").json()}


def ledger(c: TestClient) -> dict[str, dict]:
    return {a["name"]: a for a in c.get("/api/ledger/accounts", params={"include_inactive": True}).json()}


def bal(c: TestClient, name: str) -> float:
    return ledger(c).get(name, {"balance": 0})["balance"]


def assert_balanced(c: TestClient) -> None:
    s = c.get("/api/ledger/status").json()
    assert s["balanced"] and s["unbalanced_entries"] == 0, s
    bs = c.get("/api/ledger/reports/balance-sheet", params={"as_of": "2030-12-31"}).json()
    assert bs["balanced"], bs


def expense(c: TestClient, **kw) -> dict:
    body = {"expense_date": "2026-10-01", "description": "Test", "vendor_name": "Staples"} | kw
    r = c.post("/api/expenses", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def snapshot(c: TestClient) -> list[tuple]:
    """Every automatically posted line, order-independent."""
    out = []
    for e in c.get("/api/ledger/journal", params={"source": "all", "limit": 1000}).json():
        for ln in e["lines"]:
            out.append((e["source_type"], e["source_id"], e["entry_date"], ln["account_name"], ln["debit"],
                        ln["credit"]))
    return sorted(out)


# ---------------------------------------------------------------- tests
def test_chart_of_accounts_has_system_category_and_bank_accounts(auth_client: TestClient) -> None:
    c = auth_client
    make_account(c)  # opening balance 1000
    acc = ledger(c)
    for name in ("Accounts Payable (A/P)", "Accounts Receivable (A/R)", "Opening Balance Equity", "Meals",
                 "Chase Business Checking", "Client services revenue"):
        assert name in acc, name
    assert acc["Chase Business Checking"]["type"] == "asset" and acc["Chase Business Checking"]["linked_to"] == "bank"
    assert acc["Meals"]["linked_to"] == "category" and acc["Meals"]["type"] == "expense"
    assert acc["Client services revenue"]["type"] == "income"
    assert acc["Chase Business Checking"]["balance"] == 1000
    assert acc["Opening Balance Equity"]["balance"] == 1000
    assert_balanced(c)


def test_expense_with_payment_account_and_split_lines(auth_client: TestClient) -> None:
    c = auth_client
    acct = make_account(c)
    k = cats(c)
    cust = c.post("/api/customers", json={"name": "Acme Dental Group"}).json()
    e = expense(c, payment_account_id=acct["id"], description="Best Buy run", lines=[
        {"category_id": k["hardware_equipment"], "amount": 899.99, "description": "Laptop for Acme",
         "billable": True, "customer_id": cust["id"]},
        {"category_id": k["office_supplies"], "amount": 24.50, "description": "Cables"},
    ])
    assert e["amount"] == 924.49 and len(e["lines"]) == 2 and e["payment_account_name"] == acct["name"]
    assert e["lines"][0]["customer_name"] == "Acme Dental Group" and e["lines"][0]["billable"]
    assert bal(c, "Hardware & Equipment") == 899.99 and bal(c, "Office Supplies") == 24.50
    assert bal(c, "Chase Business Checking") == 75.51
    assert_balanced(c)

    # Editing re-posts: one line now, different account
    card = c.post("/api/accounts", json={"name": "Amex Business", "kind": "credit_card"}).json()
    r = c.put(f"/api/expenses/{e['id']}", json={"expense_date": "2026-10-02", "description": "Laptop only",
                                               "payment_account_id": card["id"],
                                               "lines": [{"category_id": k["hardware_equipment"], "amount": 899.99}]})
    assert r.status_code == 200, r.text
    assert bal(c, "Office Supplies") == 0 and bal(c, "Chase Business Checking") == 1000
    assert bal(c, "Amex Business") == 899.99  # card balance owed
    assert_balanced(c)

    # Deleting removes it from the books
    assert c.delete(f"/api/expenses/{e['id']}").status_code == 204
    assert bal(c, "Hardware & Equipment") == 0 and bal(c, "Amex Business") == 0
    assert_balanced(c)


def test_billable_line_needs_customer_and_old_single_form_still_works(auth_client: TestClient) -> None:
    c = auth_client
    k = cats(c)
    r = c.post("/api/expenses", json={"expense_date": "2026-10-01", "description": "x",
                                      "lines": [{"category_id": k["meals"], "amount": 10, "billable": True}]})
    assert r.status_code == 422
    e = expense(c, category_id=k["meals"], amount=12.5)  # v0.5 style: single category + amount
    assert e["lines"][0]["amount"] == 12.5
    # Without a payment account the expense still balances, against "Payment Account Not Set"
    assert bal(c, "Payment Account Not Set") == -12.5
    assert c.get("/api/ledger/status").json()["payment_account_not_set"] == 1
    assert_balanced(c)


def test_reimbursable_expense_owed_then_repaid(auth_client: TestClient) -> None:
    c = auth_client
    acct = make_account(c)
    k = cats(c)
    e = expense(c, is_reimbursable=True, payment_account_id=acct["id"],
                lines=[{"category_id": k["travel"], "amount": 60}])
    assert e["payment_account_id"] is None  # paid personally: no business account yet
    assert bal(c, "Reimbursements Owed") == 60 and bal(c, "Travel") == 60
    r = c.post(f"/api/expenses/{e['id']}/status", json={"status": "paid", "payment_account_id": acct["id"]})
    assert r.status_code == 200, r.text
    assert bal(c, "Reimbursements Owed") == 0 and bal(c, "Chase Business Checking") == 940
    c.post(f"/api/expenses/{e['id']}/status", json={"status": "approved"})  # undo paid
    assert bal(c, "Reimbursements Owed") == 60 and bal(c, "Chase Business Checking") == 1000
    assert_balanced(c)


def test_bank_transactions_post_when_approved_and_never_twice(auth_client: TestClient) -> None:
    c = auth_client
    chk = make_account(c)
    card = make_account(c, "Amex Business", "credit_card")
    do_import(c, chk["id"], CHECKING_CSV)
    do_import(c, card["id"], CARD_CSV)
    assert bal(c, "Chase Business Checking") == 1000  # nothing approved yet: only the opening balance
    txns = c.get("/api/transactions", params={"tab": "all"}).json()["items"]
    # Approve everything that can be approved
    r = c.post("/api/transactions/approve-confident", json={"min_confidence": 50})
    assert r.status_code == 200
    for t in c.get("/api/transactions", params={"tab": "review"}).json()["items"]:
        c.patch(f"/api/transactions/{t['id']}", json={"category_id": cats(c)["other"]})
        c.post(f"/api/transactions/{t['id']}/approve")
    assert c.get("/api/transactions", params={"tab": "review"}).json()["total"] == 0
    # With every transaction approved, the ledger matches the Banking balances exactly
    accounts = {a["name"]: a["balance"] for a in c.get("/api/accounts").json()}
    assert bal(c, "Chase Business Checking") == accounts["Chase Business Checking"]
    assert bal(c, "Amex Business") == -accounts["Amex Business"]  # card owed shows positive as a liability
    # The transfer (checking -> card payment) is one entry, not two
    transfers = [e for e in c.get("/api/ledger/journal", params={"source": "all"}).json()
                 if e["source_type"] == "transaction" and e["total"] == 200]
    assert len(transfers) == 1
    assert_balanced(c)

    # Linking an expense to a charge: the expense records it, the charge doesn't post again
    coffee = next(t for t in txns if "BLUE BOTTLE" in t["description"])
    before = bal(c, "Chase Business Checking")
    r = c.post(f"/api/transactions/{coffee['id']}/create-expense")
    assert r.status_code == 201, r.text
    assert r.json()["payment_account_name"] == "Chase Business Checking"
    assert bal(c, "Chase Business Checking") == before
    assert_balanced(c)

    # Moving a transaction back to review takes it out of the books
    stripe = next(t for t in txns if t["amount"] == 1500)
    income_before = bal(c, "Client services revenue")
    c.post(f"/api/transactions/{stripe['id']}/restore")
    assert bal(c, "Client services revenue") == income_before - 1500
    assert_balanced(c)


def test_bill_lifecycle_with_matched_bank_payment(auth_client: TestClient) -> None:
    c = auth_client
    chk = make_account(c)
    k = cats(c)
    r = c.post("/api/bills", json={"vendor_name": "Northstar Consulting LLC", "bill_date": "2026-10-01",
                                   "terms": "net_30", "bill_number": "NS-1",
                                   "lines": [{"category_id": k["professional_services"], "amount": 1200},
                                             {"category_id": k["software_licenses"], "amount": 84}]})
    assert r.status_code == 201, r.text
    bill = r.json()
    assert bill["due_date"] == "2026-10-31" and bill["total"] == 1284 and bill["status"] in ("open", "overdue")
    assert bal(c, "Accounts Payable (A/P)") == 1284
    assert bal(c, "Professional Services (legal, accounting)") == 1200
    assert_balanced(c)

    do_import(c, chk["id"], b"Date,Description,Amount\n10/20/2026,ONLINE PMT NORTHSTAR,-1000.00\n")
    cand = c.get(f"/api/bills/{bill['id']}/payment-candidates", params={
        "account_id": chk["id"], "amount": 1000, "payment_date": "2026-10-19"}).json()
    assert len(cand) == 1
    r = c.post(f"/api/bills/{bill['id']}/payments", json={"payment_date": "2026-10-20", "account_id": chk["id"],
                                                         "amount": 1000, "transaction_id": cand[0]["id"]})
    assert r.status_code == 201, r.text
    assert r.json()["status"] in ("partial", "overdue") and r.json()["balance"] == 284
    txn = c.get("/api/transactions", params={"tab": "all"}).json()["items"][0]
    assert txn["review_status"] == "approved" and txn["bill_id"] == bill["id"]
    assert bal(c, "Accounts Payable (A/P)") == 284 and bal(c, "Chase Business Checking") == 0
    assert_balanced(c)
    # Overpaying is refused; paying the rest without a bank match works
    assert c.post(f"/api/bills/{bill['id']}/payments", json={"payment_date": "2026-10-21", "account_id": chk["id"],
                                                            "amount": 300}).status_code == 422
    paid = c.post(f"/api/bills/{bill['id']}/payments", json={"payment_date": "2026-10-21", "account_id": chk["id"],
                                                            "amount": 284}).json()
    assert paid["status"] == "paid" and bal(c, "Accounts Payable (A/P)") == 0
    assert c.get("/api/bills").json()["items"] == []  # unpaid list empty
    assert c.delete(f"/api/bills/{bill['id']}").status_code == 409  # has payments

    # Removing the matched payment sends the charge back to review and restores A/P
    first = next(p for p in paid["payments"] if p["transaction_id"])
    r = c.delete(f"/api/bills/{bill['id']}/payments/{first['id']}")
    assert r.status_code == 200 and r.json()["balance"] == 1000
    assert c.get("/api/transactions", params={"tab": "review"}).json()["total"] == 1
    assert bal(c, "Accounts Payable (A/P)") == 1000
    assert_balanced(c)


def test_bill_attachment_roundtrip(auth_client: TestClient) -> None:
    c = auth_client
    k = cats(c)
    bill = c.post("/api/bills", json={"vendor_name": "FPL", "bill_date": "2026-10-01", "due_date": "2026-10-19",
                                      "lines": [{"category_id": k["other"], "amount": 142.17}]}).json()
    r = c.post(f"/api/bills/{bill['id']}/attachments", files={"file": ("b.pdf", b"%PDF-1.4\n", "application/pdf")})
    assert r.status_code == 201, r.text
    att = r.json()
    assert c.get(f"/api/bills/{bill['id']}/attachments/{att['id']}/content").content == b"%PDF-1.4\n"
    assert c.get(f"/api/bills/{bill['id']}").json()["attachment_count"] == 1
    assert c.delete(f"/api/bills/{bill['id']}/attachments/{att['id']}").status_code == 204


def test_opening_balance_and_closing_date(auth_client: TestClient) -> None:
    c = auth_client
    acct = c.post("/api/accounts", json={"name": "Savings", "kind": "savings", "opening_balance": 2500,
                                         "opening_date": "2026-01-01"}).json()
    assert bal(c, "Savings") == 2500 and bal(c, "Opening Balance Equity") == 2500
    k = cats(c)
    old = expense(c, expense_date="2026-03-15", payment_account_id=acct["id"],
                  lines=[{"category_id": k["meals"], "amount": 20}])
    r = c.put("/api/ledger/closing-date", json={"closing_date": "2026-06-30"})
    assert r.status_code == 200 and r.json()["closing_date"] == "2026-06-30"

    body = {"expense_date": "2026-03-15", "description": "x", "payment_account_id": acct["id"],
            "lines": [{"category_id": k["meals"], "amount": 25}]}
    r = c.put(f"/api/expenses/{old['id']}", json=body)
    assert r.status_code == 409 and "closed" in r.json()["detail"]
    assert c.delete(f"/api/expenses/{old['id']}").status_code == 409
    assert c.post("/api/expenses", json=body).status_code == 409  # new entry in a closed period
    assert c.put(f"/api/accounts/{acct['id']}", json={"name": "Savings", "kind": "savings",
                                                     "opening_balance": 3000,
                                                     "opening_date": "2026-01-01"}).status_code == 409
    # Nothing changed
    assert bal(c, "Meals") == 20 and bal(c, "Savings") == 2480
    # After the closing date is fine
    assert c.post("/api/expenses", json={**body, "expense_date": "2026-07-01"}).status_code == 201
    # Only owners set the closing date; clearing it reopens
    assert c.put("/api/ledger/closing-date", json={"closing_date": None}).json()["closing_date"] is None
    assert c.put(f"/api/expenses/{old['id']}", json=body).status_code == 200
    assert_balanced(c)


def test_manual_journal_entries(auth_client: TestClient) -> None:
    c = auth_client
    make_account(c)
    acc = ledger(c)
    r = c.post("/api/ledger/accounts", json={"name": "Loan from Owner", "type": "liability",
                                             "detail_type": "long_term_liability"})
    assert r.status_code == 201, r.text
    loan = r.json()
    body = {"entry_date": "2026-10-05", "number": "JE-1", "memo": "Owner loan", "lines": [
        {"account_id": acc["Chase Business Checking"]["id"], "debit": 5000},
        {"account_id": loan["id"], "credit": 5000}]}
    r = c.post("/api/ledger/journal", json=body)
    assert r.status_code == 201, r.text
    je = r.json()
    assert je["editable"] and je["total"] == 5000
    assert bal(c, "Loan from Owner") == 5000 and bal(c, "Chase Business Checking") == 6000
    assert_balanced(c)
    # Unbalanced, both-sides lines and A/P are refused
    bad = {**body, "lines": [{"account_id": loan["id"], "debit": 10}, {"account_id": loan["id"], "credit": 9}]}
    assert c.post("/api/ledger/journal", json=bad).status_code == 422
    bad = {**body, "lines": [{"account_id": loan["id"], "debit": 10, "credit": 10},
                             {"account_id": loan["id"], "credit": 0}]}
    assert c.post("/api/ledger/journal", json=bad).status_code == 422
    ap = acc["Accounts Payable (A/P)"]["id"]
    bad = {**body, "lines": [{"account_id": ap, "debit": 10}, {"account_id": loan["id"], "credit": 10}]}
    assert c.post("/api/ledger/journal", json=bad).status_code == 422
    # Edit and delete
    body["lines"][0]["debit"] = body["lines"][1]["credit"] = 4000
    r = c.put(f"/api/ledger/journal/{je['id']}", json=body)
    assert r.status_code == 200 and bal(c, "Loan from Owner") == 4000
    new_id = r.json()["id"]
    assert c.delete(f"/api/ledger/journal/{new_id}").status_code == 204
    assert bal(c, "Loan from Owner") == 0
    # Automatic entries can't be edited as journal entries
    auto = next(e for e in c.get("/api/ledger/journal", params={"source": "all"}).json() if not e["editable"])
    assert c.delete(f"/api/ledger/journal/{auto['id']}").status_code == 409
    assert_balanced(c)


def test_income_and_expense_accounts_become_categories(auth_client: TestClient) -> None:
    c = auth_client
    r = c.post("/api/ledger/accounts", json={"name": "Managed Services Revenue", "type": "income",
                                             "detail_type": "income", "code": "4010"})
    assert r.status_code == 201 and r.json()["linked_to"] == "category"
    cat = next(x for x in c.get("/api/categories").json() if x["name"] == "Managed Services Revenue")
    assert cat["kind"] == "income"
    # Renaming the category renames the account; bank detail types are refused here
    c.put(f"/api/categories/{cat['id']}", json={"name": "Managed IT Revenue"})
    assert "Managed IT Revenue" in ledger(c)
    assert c.post("/api/ledger/accounts", json={"name": "X", "type": "asset", "detail_type": "bank"}).status_code == 422


def test_reports_profit_and_loss_and_balance_sheet(auth_client: TestClient) -> None:
    c = auth_client
    chk = make_account(c)
    k = cats(c)
    expense(c, expense_date="2026-09-10", payment_account_id=chk["id"], lines=[{"category_id": k["meals"], "amount": 40}])
    expense(c, expense_date="2026-10-02", payment_account_id=chk["id"],
            lines=[{"category_id": k["software_licenses"], "amount": 60}])
    t = c.post("/api/transactions", json={"account_id": chk["id"], "txn_date": "2026-10-03", "amount": 500,
                                          "description": "Client payment", "category_id": k["client_services_revenue"]}).json()
    c.post(f"/api/transactions/{t['id']}/approve")
    pl = c.get("/api/ledger/reports/profit-and-loss", params={"date_from": "2026-10-01", "date_to": "2026-10-31"}).json()
    assert pl["net_income"] == 440  # 500 income - 60 software (meals was September)
    income = next(s for s in pl["sections"] if s["key"] == "income")
    assert income["total"] == 500
    full = c.get("/api/ledger/reports/profit-and-loss", params={"date_from": "2026-01-01", "date_to": "2026-12-31"}).json()
    assert full["net_income"] == 400
    bs = c.get("/api/ledger/reports/balance-sheet", params={"as_of": "2026-12-31"}).json()
    assert bs["balanced"] and bs["total_assets"] == 1400  # 1000 opening + 500 - 40 - 60
    equity = next(s for s in bs["sections"] if s["key"] == "equity")
    assert {r["name"]: r["amount"] for r in equity["rows"]} == {"Opening Balance Equity": 1000, "Net Income": 400}
    tb = c.get("/api/ledger/reports/trial-balance", params={"as_of": "2026-12-31"}).json()
    assert tb["total_debit"] == tb["total_credit"]
    assert c.get("/api/ledger/reports/profit-and-loss",
                 params={"date_from": "2026-12-01", "date_to": "2026-01-01"}).status_code == 422


def test_rebuild_matches_incremental_posting(auth_client: TestClient) -> None:
    """The books built from scratch equal the books built change by change."""
    c = auth_client
    chk = make_account(c)
    card = make_account(c, "Amex Business", "credit_card")
    do_import(c, chk["id"], CHECKING_CSV)
    do_import(c, card["id"], CARD_CSV)
    c.post("/api/transactions/approve-confident", json={"min_confidence": 50})
    k = cats(c)
    e = expense(c, payment_account_id=card["id"], lines=[{"category_id": k["meals"], "amount": 23}])
    expense(c, is_reimbursable=True, lines=[{"category_id": k["travel"], "amount": 15}])
    bill = c.post("/api/bills", json={"vendor_name": "FPL", "bill_date": "2026-10-01", "due_date": "2026-10-19",
                                      "lines": [{"category_id": k["other"], "amount": 142.17}]}).json()
    c.post(f"/api/bills/{bill['id']}/payments", json={"payment_date": "2026-10-10", "account_id": chk["id"],
                                                     "amount": 100})
    c.put(f"/api/expenses/{e['id']}", json={"expense_date": "2026-10-04", "description": "Lunch",
                                            "payment_account_id": card["id"],
                                            "lines": [{"category_id": k["meals"], "amount": 23}]})
    before = snapshot(c)
    assert before
    from app.database import get_session_factory
    from app.ledger.books import rebuild
    from app.tenancy import set_company

    company_id = c.get("/api/auth/me").json()["company_id"]
    import uuid as _uuid
    with get_session_factory()() as db:
        set_company(db, _uuid.UUID(company_id))
        rebuild(db, _uuid.UUID(company_id))
        db.commit()
    after = snapshot(c)
    strip = lambda rows: sorted((r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows)  # noqa: E731
    assert strip(after) == strip(before)
    assert_balanced(c)


def test_ledger_is_per_company(auth_client: TestClient) -> None:
    c = auth_client
    a_id = c.get("/api/auth/me").json()["company_id"]
    chk = make_account(c)
    k = cats(c)
    bill = c.post("/api/bills", json={"vendor_name": "FPL", "bill_date": "2026-10-01", "due_date": "2026-10-19",
                                      "lines": [{"category_id": k["other"], "amount": 50}]}).json()
    je = c.post("/api/ledger/journal", json={"entry_date": "2026-10-05", "lines": [
        {"account_id": ledger(c)["Chase Business Checking"]["id"], "debit": 1},
        {"account_id": ledger(c)["Opening Balance Equity"]["id"], "credit": 1}]}).json()
    b = new_company(c, "Bright Lawn Care")
    switch(c, b["id"])
    assert "Chase Business Checking" not in ledger(c)
    assert c.get("/api/bills", params={"show": "all"}).json()["items"] == []
    assert c.get(f"/api/bills/{bill['id']}").status_code == 404
    assert c.get(f"/api/ledger/journal/{je['id']}").status_code == 404
    assert c.delete(f"/api/ledger/journal/{je['id']}").status_code == 404
    assert c.get("/api/ledger/journal", params={"source": "all"}).json() == []
    other_acct = ledger(c)["Opening Balance Equity"]["id"]
    # A's accounts can't be used in B's entries
    r = c.post("/api/ledger/journal", json={"entry_date": "2026-10-05", "lines": [
        {"account_id": je["lines"][0]["account_id"], "debit": 1}, {"account_id": other_acct, "credit": 1}]})
    assert r.status_code == 422
    r = c.post("/api/expenses", json={"expense_date": "2026-10-01", "description": "x", "payment_account_id": chk["id"],
                                      "lines": [{"category_id": cats(c)["meals"], "amount": 5}]})
    assert r.status_code == 422
    assert c.get("/api/ledger/reports/balance-sheet", params={"as_of": "2030-01-01"}).json()["total_assets"] == 0
    switch(c, a_id)
    assert bal(c, "Accounts Payable (A/P)") == 50


def test_viewer_reads_reports_but_cannot_post(auth_client: TestClient, client: TestClient) -> None:
    v = auth_client.post("/api/members", json={"email": "v@example.com", "role": "viewer"}).json()
    login(client, "v@example.com", v["temporary_password"])
    assert client.get("/api/ledger/accounts").status_code == 200
    assert client.get("/api/ledger/reports/trial-balance", params={"as_of": "2026-12-31"}).status_code == 200
    assert client.post("/api/ledger/journal", json={"entry_date": "2026-10-01", "lines": []}).status_code == 403
    assert client.put("/api/ledger/closing-date", json={"closing_date": "2026-01-01"}).status_code == 403


def test_bookkeeper_cannot_change_closing_date(auth_client: TestClient, client: TestClient) -> None:
    b = auth_client.post("/api/members", json={"email": "bk@example.com", "role": "bookkeeper"}).json()
    login(client, "bk@example.com", b["temporary_password"])
    assert client.put("/api/ledger/closing-date", json={"closing_date": "2026-01-01"}).status_code == 403
    assert client.get("/api/ledger/status").status_code == 200


def test_money_is_exact(auth_client: TestClient) -> None:
    c = auth_client
    chk = make_account(c)
    k = cats(c)
    for _ in range(3):
        expense(c, payment_account_id=chk["id"], lines=[{"category_id": k["meals"], "amount": 0.1},
                                                       {"category_id": k["meals"], "amount": 0.2}])
    assert Decimal(str(bal(c, "Meals"))) == Decimal("0.90")
    assert_balanced(c)
