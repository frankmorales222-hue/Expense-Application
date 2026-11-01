"""v0.8.0 plans and modules: read-only when off, Accountant exemption, user limits, who manages plans."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import ADMIN
from .test_ledger import cats, ledger
from .test_multicompany import login, new_company, switch
from .test_sales import customer, invoice, ms  # noqa: F401  (ms is a fixture)

CLIENT_ID = "11111111-2222-3333-4444-555555555555"


def company_id(c: TestClient) -> str:
    return c.get("/api/auth/me").json()["company_id"]


def set_plan(c: TestClient, cid: str, plan: str, **kw) -> dict:
    r = c.put(f"/api/plans/companies/{cid}", json={"plan": plan, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def bill(c: TestClient, expect: int = 201):
    r = c.post("/api/bills", json={"vendor_name": "FPL", "bill_date": "2026-10-01", "terms": "net_30",
                                   "lines": [{"category_id": cats(c)["other"], "amount": 50}]})
    assert r.status_code == expect, r.text
    return r.json()


def test_existing_companies_keep_every_module(auth_client: TestClient) -> None:
    me = auth_client.get("/api/auth/me").json()
    assert me["modules"] == ["invoicing", "bills", "smart_capture", "advanced_accounting"]
    assert me["plan_label"] == "All modules" and me["user_limit"] is None
    cat = auth_client.get("/api/plans/catalog").json()
    assert [p["key"] for p in cat["plans"]] == ["starter", "essentials", "plus", "advanced"]
    assert {m["key"] for m in cat["modules"]} == {"invoicing", "bills", "smart_capture", "advanced_accounting"}


def test_modules_off_are_read_only(auth_client: TestClient) -> None:
    c = auth_client
    cid = company_id(c)
    b = bill(c)
    inv = invoice(c, customer(c))
    out = set_plan(c, cid, "starter")  # invoicing only, 1 user
    assert out["modules"] == ["invoicing"] and out["user_limit"] == 1 and out["plan_label"] == "Starter"
    me = c.get("/api/auth/me").json()
    assert me["modules"] == ["invoicing"] and me["module_data"] == ["bills"]

    # Bills: can read and print, can't add, change, pay or delete.
    r = bill(c, expect=403)
    assert "isn't included in this company's plan" in r["detail"]
    assert c.get("/api/bills", params={"show": "all"}).status_code == 200
    assert c.get(f"/api/bills/{b['id']}").status_code == 200
    assert c.delete(f"/api/bills/{b['id']}").status_code == 403
    # Smart capture is off too.
    r = c.post("/api/documents/extract", files={"file": ("bill.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 403
    # Invoicing is on.
    assert c.get(f"/api/invoices/{inv['id']}/pdf").status_code == 200
    invoice(c, customer(c, "Second Customer"))

    set_plan(c, cid, "custom", modules=["bills"], user_limit=None)
    r = c.post("/api/invoices", json={"customer_id": inv["customer_id"], "invoice_date": "2026-10-01",
                                      "lines": [{"rate": 5, "category_id": cats(c)["other_income"]}]})
    assert r.status_code == 403
    assert c.get(f"/api/invoices/{inv['id']}").status_code == 200  # still viewable
    assert c.get(f"/api/invoices/{inv['id']}/pdf").status_code == 200  # and printable
    assert c.post("/api/items", json={"name": "X", "category_id": cats(c)["other_income"]}).status_code == 403
    assert "invoicing" in c.get("/api/auth/me").json()["module_data"]
    bill(c)  # bills back on
    # The books still count the old invoice.
    assert ledger(c)["Accounts Receivable (A/R)"]["balance"] == 300 + 300


def test_accountant_always_has_accounting_tools(auth_client: TestClient, client: TestClient) -> None:
    c = auth_client
    cid = company_id(c)
    set_plan(c, cid, "essentials")  # no advanced accounting
    acc = ledger(c)
    entry = {"entry_date": "2026-10-05", "lines": [
        {"account_id": acc["Owner contribution"]["id"], "credit": 10},
        {"account_id": acc["Opening Balance Equity"]["id"], "debit": 10}]}
    r = c.post("/api/ledger/journal", json=entry)
    assert r.status_code == 403  # the owner's staff can't
    assert c.get("/api/ledger/reports/trial-balance", params={"as_of": "2026-12-31"}).status_code == 403
    assert c.get("/api/ledger/reports/balance-sheet", params={"as_of": "2026-12-31"}).status_code == 200  # core
    assert c.get("/api/ledger/reports/profit-and-loss",
                 params={"date_from": "2026-01-01", "date_to": "2026-12-31"}).status_code == 200

    added = c.post("/api/members", json={"email": "cpa@garciatax.example", "name": "Maria CPA", "role": "accountant"})
    assert added.status_code == 201, added.text
    login(client, "cpa@garciatax.example", added.json()["temporary_password"])
    switch(client, cid)
    r = client.post("/api/ledger/journal", json=entry)
    assert r.status_code == 201, r.text
    assert client.get("/api/ledger/reports/trial-balance", params={"as_of": "2026-12-31"}).status_code == 200
    # The accountant's entry is readable by the owner (read-only module).
    assert len(c.get("/api/ledger/journal").json()) == 1
    assert "advanced_accounting" in c.get("/api/auth/me").json()["module_data"]


def test_user_limit_counts_everyone_but_the_accountant(auth_client: TestClient) -> None:
    c = auth_client
    cid = company_id(c)
    set_plan(c, cid, "starter")  # 1 user; the platform owner doesn't take a seat
    assert c.post("/api/members", json={"email": "owner2@client.example", "role": "owner"}).status_code == 201
    r = c.post("/api/members", json={"email": "book@client.example", "role": "bookkeeper"})
    assert r.status_code == 409 and "The Accountant doesn't count" in r.json()["detail"]
    acct = c.post("/api/members", json={"email": "cpa@client.example", "role": "accountant"})
    assert acct.status_code == 201
    me = c.get("/api/auth/me").json()
    assert me["seats_used"] == 1 and me["user_limit"] == 1
    assert c.put(f"/api/members/{acct.json()['member']['user_id']}", json={"role": "bookkeeper"}).status_code == 409
    set_plan(c, cid, "essentials")  # 3 users
    assert c.post("/api/members", json={"email": "book@client.example", "role": "bookkeeper"}).status_code == 201


def test_new_company_gets_the_chosen_plan_and_only_admins_change_plans(
        auth_client: TestClient, client: TestClient) -> None:
    c = auth_client
    co = new_company(c, "Sunrise Bakery", plan="essentials")
    plans = {p["name"]: p for p in c.get("/api/plans/companies").json()}
    assert plans["Sunrise Bakery"]["modules"] == ["invoicing", "bills", "smart_capture"]
    assert plans["Sunrise Bakery"]["user_limit"] == 3
    # Adjusting a plan by hand makes it Custom.
    out = set_plan(c, co["id"], "essentials", modules=["invoicing"], user_limit=3)
    assert out["plan"] == "custom" and out["plan_label"] == "Custom"

    # A company owner can't see or change plans.
    added = c.post("/api/members", json={"email": "owner@bakery.example", "role": "owner"}).json()
    login(client, "owner@bakery.example", added["temporary_password"])
    assert client.get("/api/plans/companies").status_code == 403
    assert client.put(f"/api/plans/companies/{co['id']}", json={"plan": "plus"}).status_code == 403


def test_reseller_admin_manages_plans_for_their_clients_only(auth_client: TestClient, client: TestClient) -> None:
    c = auth_client
    mine = new_company(c, "F&M Client")
    reseller = c.post("/api/resellers", json={"name": "Garcia Tax & Accounting"}).json()
    added = c.post(f"/api/resellers/{reseller['id']}/admins", json={"email": "maria@garciatax.example"}).json()
    login(client, "maria@garciatax.example", added["temporary_password"])
    theirs = client.post("/api/companies", json={"name": "Sunrise Bakery", "plan": "starter"}).json()
    listed = client.get("/api/plans/companies").json()
    assert [x["name"] for x in listed] == ["Sunrise Bakery"] and listed[0]["reseller_name"] == "Garcia Tax & Accounting"
    assert set_plan(client, theirs["id"], "plus")["plan"] == "plus"
    assert client.put(f"/api/plans/companies/{mine['id']}", json={"plan": "plus"}).status_code == 404
    # The platform owner sees every company (names and plans only).
    login(c, ADMIN["email"], ADMIN["password"])
    assert {"Sunrise Bakery", "F&M Client"} <= {x["name"] for x in c.get("/api/plans/companies").json()}


def test_single_tenant_microsoft_app(auth_client: TestClient, ms) -> None:
    c = auth_client
    tenant = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert c.post("/api/email-settings/microsoft/start", json={"client_id": CLIENT_ID, "tenant_id": "bad tenant"}
                  ).status_code == 422
    start = c.post("/api/email-settings/microsoft/start", json={"client_id": CLIENT_ID, "tenant_id": tenant}).json()
    assert f"/{tenant}/oauth2/v2.0/devicecode" in ms.calls[-1][1]
    c.post("/api/email-settings/microsoft/poll", json={"flow_id": start["flow_id"]})
    done = c.post("/api/email-settings/microsoft/poll", json={"flow_id": start["flow_id"]}).json()
    assert done["settings"]["ms_tenant"] == tenant
    assert all(f"/{tenant}/" in call[1] for call in ms.calls if "login.microsoftonline.com" in call[1])
    inv = invoice(c, customer(c))
    r = c.post(f"/api/invoices/{inv['id']}/send", json={"to": ["x@acme.example"], "subject": "s", "body": "b"})
    assert r.status_code == 200, r.text
    assert f"/{tenant}/oauth2/v2.0/token" in [call[1] for call in ms.calls if call[2] and
                                              call[2].get("grant_type") == "refresh_token"][0]


def test_single_tenant_error_is_explained() -> None:
    from app.invoicing.microsoft import explain

    msg = explain({"error": "invalid_request", "error_description":
                   "AADSTS50194: Application 'x' is not configured as a multi-tenant application."})
    assert "Directory (tenant) ID" in msg
