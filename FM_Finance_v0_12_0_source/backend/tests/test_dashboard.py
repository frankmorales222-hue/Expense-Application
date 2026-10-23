"""v0.9.0: themes and the dashboard overview (cash, forecast, coming up, profit)."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from .conftest import ADMIN
from .test_banking import make_account
from .test_ledger import cats
from .test_multicompany import login, new_company
from .test_sales import customer, invoice


def iso(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def txn(c: TestClient, account: dict, days: int, amount: float, desc: str) -> dict:
    r = c.post("/api/transactions", json={"account_id": account["id"], "txn_date": iso(days), "amount": amount,
                                          "description": desc})
    assert r.status_code == 201, r.text
    return r.json()


def test_theme_is_personal_with_a_company_default(auth_client: TestClient, client: TestClient) -> None:
    c = auth_client
    me = c.get("/api/auth/me").json()
    assert me["theme"] is None and me["theme_effective"] == "classic" and me["company_default_theme"] == "classic"
    assert c.put("/api/auth/me/theme", json={"theme": "neon"}).status_code == 422
    me = c.put("/api/auth/me/theme", json={"theme": "dark"}).json()
    assert me["theme"] == "dark" and me["theme_effective"] == "dark"

    # The company default applies to people who haven't chosen.
    cid = me["company_id"]
    out = c.put(f"/api/plans/companies/{cid}/theme", json={"default_theme": "executive"})
    assert out.status_code == 200 and out.json()["default_theme"] == "executive"
    added = c.post("/api/members", json={"email": "book@client.example", "role": "bookkeeper"}).json()
    login(client, "book@client.example", added["temporary_password"])
    other = client.get("/api/auth/me").json()
    assert other["theme"] is None and other["theme_effective"] == "executive"
    # Only plan administrators set a company's default.
    assert client.put(f"/api/plans/companies/{cid}/theme", json={"default_theme": "dark"}).status_code == 403
    login(c, ADMIN["email"], ADMIN["password"])  # the two clients share cookies
    assert c.get("/api/auth/me").json()["theme_effective"] == "dark"  # own choice wins
    # Going back to the default
    assert c.put("/api/auth/me/theme", json={"theme": None}).json()["theme_effective"] == "executive"


def test_reseller_sets_default_theme_for_their_clients_only(auth_client: TestClient, client: TestClient) -> None:
    c = auth_client
    mine = new_company(c, "F&M Client")
    reseller = c.post("/api/resellers", json={"name": "Garcia Tax & Accounting"}).json()
    added = c.post(f"/api/resellers/{reseller['id']}/admins", json={"email": "maria@garciatax.example"}).json()
    login(client, "maria@garciatax.example", added["temporary_password"])
    theirs = client.post("/api/companies", json={"name": "Sunrise Bakery"}).json()
    assert client.put(f"/api/plans/companies/{theirs['id']}/theme", json={"default_theme": "dark"}).status_code == 200
    assert client.put(f"/api/plans/companies/{mine['id']}/theme", json={"default_theme": "dark"}).status_code == 404
    login(c, ADMIN["email"], ADMIN["password"])


def test_dashboard_empty_company(auth_client: TestClient) -> None:
    d = auth_client.get("/api/dashboard/overview").json()
    assert d["cash_total"] == 0 and d["has_bank_accounts"] is False
    assert len(d["history"]) == 31 and len(d["forecast"]) == 31 and len(d["months"]) == 12
    assert d["coming_up"] == [] and d["invoices"] == [] and d["review_count"] == 0


def test_dashboard_cash_forecast_and_coming_up(auth_client: TestClient) -> None:
    c = auth_client
    chk = make_account(c)  # opening 1,000
    sav = make_account(c, "SCCU Savings", "savings")  # opening 1,000
    card = make_account(c, "Business Visa", "credit_card")  # opening 1,000, not cash
    txn(c, chk, -40, 500, "Old deposit")  # before the 30-day window
    txn(c, chk, -10, 2000, "Zelle from Coastal Dental")
    txn(c, chk, -2, -250, "FPL")
    txn(c, card, -3, -99.99, "Amazon")
    excluded = txn(c, chk, -1, -5000, "Duplicate")
    assert c.post(f"/api/transactions/{excluded['id']}/exclude").status_code == 200

    cust = customer(c)
    due_soon = invoice(c, cust, invoice_date=iso(-20), terms="net_30")  # due in 10 days: 300
    late = invoice(c, customer(c, "Miramar Auto Glass"), invoice_date=iso(-35), terms="net_30")  # 5 days late
    r = c.post("/api/bills", json={"vendor_name": "Hiscox", "bill_date": iso(-10), "terms": "net_15",
                                   "lines": [{"category_id": cats(c)["other"], "amount": 640}]})
    assert r.status_code == 201, r.text
    r = c.post("/api/bills", json={"vendor_name": "Old vendor", "bill_date": iso(-60), "terms": "net_30",
                                   "lines": [{"category_id": cats(c)["other"], "amount": 100}]})
    assert r.status_code == 201, r.text

    d = c.get("/api/dashboard/overview").json()
    cash = 1000 + 500 + 2000 - 250 + 1000  # checking + savings, card and excluded left out
    assert d["cash_total"] == cash
    assert {a["name"]: a["balance"] for a in d["accounts"]}["Business Visa"] == 900.01
    assert d["history"][-1]["balance"] == cash
    assert d["history"][0]["balance"] == cash - 2000 + 250  # 30 days ago
    # Forecast: overdue bill (-100) tomorrow, Hiscox (-640) in 5 days, invoice (+300) in 10 days; late invoice not counted.
    f = {p["date"]: p["balance"] for p in d["forecast"]}
    assert f[iso(0)] == cash and f[iso(1)] == cash - 100 and f[iso(5)] == cash - 740 and f[iso(10)] == cash - 440
    assert d["forecast_low"] == {"date": iso(5), "balance": cash - 740}
    # Coming up: late things first (latest first), then by date.
    kinds = [(e["kind"], e["name"], e["days_late"]) for e in d["coming_up"]]
    assert kinds == [("bill", "Old vendor", 30), ("invoice", "Miramar Auto Glass", 5), ("bill", "Hiscox", 0),
                     ("invoice", "Acme Dental Group", 0)]
    assert [e["amount"] for e in d["coming_up"]] == [-100, 300, -640, 300]
    assert d["receivable_total"] == 600 and d["overdue_total"] == 300 and d["overdue_count"] == 1
    assert d["payable_total"] == 740 and d["payable_due_14"] == 740 and d["payable_overdue"] == 100
    assert d["invoices"][0]["invoice_number"] == late["invoice_number"] and d["invoices"][0]["days_late"] == 5
    assert d["invoices"][1]["invoice_number"] == due_soon["invoice_number"]
    assert d["review_count"] == 4  # manual transactions start in For review; the excluded one doesn't count


def test_dashboard_profit_and_month_compare(auth_client: TestClient) -> None:
    c = auth_client
    cust = customer(c)
    invoice(c, cust, invoice_date=date.today().isoformat())  # 300 of income this month
    r = c.post("/api/bills", json={"vendor_name": "Tech Data", "bill_date": date.today().isoformat(), "terms": "net_30",
                                   "lines": [{"category_id": cats(c)["other"], "amount": 120}]})
    assert r.status_code == 201, r.text
    d = c.get("/api/dashboard/overview").json()
    assert d["income_ytd"] == 300 and d["expenses_ytd"] == 120 and d["profit_ytd"] == 180
    assert d["pnl"]["income_this"] == 300 and d["pnl"]["expenses_this"] == 120 and d["pnl"]["net_this"] == 180
    assert d["pnl"]["income_last"] == 0
    assert d["pnl"]["expense_rows"][0]["this_month"] == 120
    this = d["months"][-1]
    assert this["key"] == date.today().strftime("%Y-%m") and this["income"] == 300 and this["expenses"] == 120


def test_dashboard_is_for_owners_and_accountants(auth_client: TestClient, client: TestClient) -> None:
    added = auth_client.post("/api/members", json={"email": "emp@client.example", "role": "employee"}).json()
    login(client, "emp@client.example", added["temporary_password"])
    assert client.get("/api/dashboard/overview").status_code == 403
