"""v0.5.0 multi-company: isolation between companies, roles, members, resellers."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import ADMIN
from .test_banking import CHECKING_CSV, do_import, make_account
from .test_documents import INVOICE, make_pdf


def login(c: TestClient, email: str, password: str) -> dict:
    c.cookies.clear()
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def new_company(c: TestClient, name: str, **extra) -> dict:
    r = c.post("/api/companies", json={"name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def switch(c: TestClient, company_id: str) -> dict:
    r = c.post(f"/api/companies/{company_id}/switch")
    assert r.status_code == 200, r.text
    return r.json()


def cat_id(c: TestClient, code: str) -> str:
    return next(x["id"] for x in c.get("/api/categories").json() if x["code"] == code)


def seed_company_a(c: TestClient) -> dict:
    """Expense with receipt, custom category, vendor, customer, bank account and import in the current company."""
    acct = make_account(c)
    batch = do_import(c, acct["id"], CHECKING_CSV).json()
    custom = c.post("/api/categories", json={"name": "Client gifts"}).json()
    exp = c.post("/api/expenses", json={"expense_date": "2026-10-01", "vendor_name": "Northstar Consulting LLC",
                                        "category_id": custom["id"], "description": "Gift baskets",
                                        "amount": 120, "invoice_number": "NS-00981"}).json()
    rec = c.post(f"/api/expenses/{exp['id']}/receipts", files={"file": ("r.pdf", b"%PDF-1.4\n", "application/pdf")}).json()
    cust = c.post("/api/customers", json={"name": "Acme Dental Group"}).json()
    vendor = next(v for v in c.get("/api/vendors/all").json() if v["name"] == "Northstar Consulting LLC")
    txn = c.get("/api/transactions", params={"tab": "all"}).json()["items"][0]
    return {"account": acct, "batch": batch, "category": custom, "expense": exp, "receipt": rec,
            "customer": cust, "vendor": vendor, "txn": txn}


def test_fresh_install_has_one_company_owned_by_admin(auth_client: TestClient) -> None:
    me = auth_client.get("/api/auth/me").json()
    assert me["role"] == "admin" and me["company_role"] == "owner" and me["is_platform_admin"]
    assert me["company_count"] == 1 and me["company_name"]
    companies = auth_client.get("/api/companies").json()
    assert len(companies) == 1 and companies[0]["is_current"] and companies[0]["role"] == "owner"


def test_company_b_cannot_see_or_touch_company_a(auth_client: TestClient) -> None:
    c = auth_client
    a_id = c.get("/api/auth/me").json()["company_id"]
    a = seed_company_a(c)
    b = new_company(c, "Bright Lawn Care")
    assert c.get("/api/auth/me").json()["company_id"] == a_id  # creating doesn't switch
    me = switch(c, b["id"])
    assert me["company_id"] == b["id"] and me["company_role"] == "owner"

    # Lists are empty in B
    assert c.get("/api/expenses").json()["total"] == 0
    assert c.get("/api/transactions", params={"tab": "all"}).json()["total"] == 0
    assert c.get("/api/accounts").json() == []
    assert c.get("/api/vendors/all").json() == []
    assert c.get("/api/vendors", params={"q": "North"}).json() == []
    assert c.get("/api/customers").json() == []
    assert c.get("/api/imports").json() == []
    assert c.get("/api/reports/summary").json()["expense_count"] == 0
    cats = c.get("/api/categories").json()
    assert len(cats) == 21 and all(x["name"] != "Client gifts" for x in cats)  # its own default set
    export = c.get("/api/expenses/export.csv").text
    assert "Gift baskets" not in export

    # Direct access to A's records by id is "not found" from B
    assert c.get(f"/api/expenses/{a['expense']['id']}").status_code == 404
    assert c.put(f"/api/expenses/{a['expense']['id']}", json={
        "expense_date": "2026-10-01", "category_id": cats[0]["id"], "description": "x", "amount": 1}).status_code == 404
    assert c.delete(f"/api/expenses/{a['expense']['id']}").status_code == 404
    assert c.get(f"/api/receipts/{a['receipt']['id']}/content").status_code == 404
    assert c.delete(f"/api/receipts/{a['receipt']['id']}").status_code == 404
    assert c.put(f"/api/categories/{a['category']['id']}", json={"name": "Hacked"}).status_code == 404
    assert c.put(f"/api/vendors/{a['vendor']['id']}", json={"name": "Hacked"}).status_code == 404
    assert c.put(f"/api/customers/{a['customer']['id']}", json={"name": "Hacked"}).status_code == 404
    acct_body = {"name": "Hacked", "kind": "checking"}
    assert c.put(f"/api/accounts/{a['account']['id']}", json=acct_body).status_code == 404
    assert c.patch(f"/api/transactions/{a['txn']['id']}", json={"memo": "x"}).status_code == 404
    assert c.post(f"/api/transactions/{a['txn']['id']}/approve").status_code == 404
    assert c.post(f"/api/imports/{a['batch']['id']}/undo").status_code == 404
    imp = c.post("/api/imports", data={"account_id": a["account"]["id"]},
                 files={"file": ("s.csv", CHECKING_CSV, "text/csv")})
    assert imp.status_code == 404

    # A's ids can't be used as references from B
    r = c.post("/api/expenses", json={"expense_date": "2026-10-02", "category_id": a["category"]["id"],
                                      "description": "x", "amount": 5})
    assert r.status_code == 422

    # Bill import in B doesn't see A's duplicate or A's bank charge
    bill = c.post("/api/documents/extract", files={"file": ("inv.pdf", make_pdf(INVOICE.splitlines()),
                                                            "application/pdf")}).json()
    assert bill["duplicates"] == [] and bill["bank_match"] is None and not bill["known_vendor"]

    # Same names are fine in both companies
    assert c.post("/api/categories", json={"name": "Client gifts"}).status_code == 201
    e = c.post("/api/expenses", json={"expense_date": "2026-10-02", "vendor_name": "Northstar Consulting LLC",
                                      "category_id": cat_id(c, "meals"), "description": "Lunch", "amount": 30})
    assert e.status_code == 201

    # Nothing in A changed
    switch(c, a_id)
    assert c.get(f"/api/expenses/{a['expense']['id']}").json()["description"] == "Gift baskets"
    assert c.get("/api/expenses").json()["total"] == 1
    assert len([v for v in c.get("/api/vendors/all").json() if v["name"] == "Northstar Consulting LLC"]) == 1


def test_switch_requires_access(auth_client: TestClient, client: TestClient) -> None:
    other = new_company(auth_client, "Other Co")
    added = auth_client.post("/api/members", json={"email": "emp@example.com", "name": "Emp", "role": "employee"})
    assert added.status_code == 201
    pw = added.json()["temporary_password"]
    login(client, "emp@example.com", pw)
    assert client.post(f"/api/companies/{other['id']}/switch").status_code == 404
    assert [x["name"] for x in client.get("/api/companies").json()] != ["Other Co"]
    assert client.post("/api/companies/not-a-uuid/switch").status_code == 422


def test_roles_viewer_employee_and_owner_rules(auth_client: TestClient, client: TestClient) -> None:
    c = auth_client
    seed_company_a(c)
    viewer = c.post("/api/members", json={"email": "viewer@example.com", "name": "Vic Viewer", "role": "viewer"}).json()
    emp = c.post("/api/members", json={"email": "emp@example.com", "name": "Ella Employee", "role": "employee"}).json()
    assert viewer["temporary_password"] and viewer["member"]["role"] == "viewer"
    assert c.post("/api/members", json={"email": "viewer@example.com", "role": "owner"}).status_code == 409
    admin_id = c.get("/api/auth/me").json()["id"]
    # The last owner can't be demoted or removed
    assert c.put(f"/api/members/{admin_id}", json={"role": "viewer"}).status_code == 409
    assert c.delete(f"/api/members/{admin_id}").status_code == 409

    # Viewer: reads everything, writes nothing
    me = login(client, "viewer@example.com", viewer["temporary_password"])
    assert me["role"] == "viewer" and me["company_role"] == "viewer"
    assert client.get("/api/expenses").json()["total"] == 1
    assert client.get("/api/transactions", params={"tab": "all"}).json()["total"] == 5
    assert client.get("/api/accounts").status_code == 200
    exp_id = client.get("/api/expenses").json()["items"][0]["id"]
    assert client.get(f"/api/expenses/{exp_id}").json()["allowed_transitions"] == []
    cats = client.get("/api/categories").json()
    assert client.post("/api/expenses", json={"expense_date": "2026-10-01", "category_id": cats[0]["id"],
                                              "description": "x", "amount": 1}).status_code == 403
    assert client.post("/api/categories", json={"name": "Nope"}).status_code == 403
    assert client.get("/api/members").status_code == 403
    # ...but can change their own password
    assert client.post("/api/auth/change-password", json={"current_password": viewer["temporary_password"],
                                                          "new_password": "Viewer-Pass-123"}).status_code == 204

    # Employee: only their own expenses, no banking
    me = login(client, "emp@example.com", emp["temporary_password"])
    assert me["role"] == "submitter" and me["company_role"] == "employee"
    assert client.get("/api/expenses").json()["total"] == 0
    assert client.get("/api/transactions").status_code == 403
    r = client.post("/api/expenses", json={"expense_date": "2026-10-03", "category_id": cats[0]["id"],
                                           "description": "Parking", "amount": 12})
    assert r.status_code == 201
    assert client.get("/api/expenses").json()["total"] == 1

    # Owner promotes the viewer, then removes the employee
    login(c, ADMIN["email"], ADMIN["password"])
    assert c.put(f"/api/members/{viewer['member']['user_id']}", json={"role": "owner"}).json()["role"] == "owner"
    assert c.delete(f"/api/members/{emp['member']['user_id']}").status_code == 204
    login(client, "emp@example.com", emp["temporary_password"])
    assert client.get("/api/auth/me").json()["role"] == "none"
    assert client.get("/api/expenses").status_code == 403  # no company: nothing, not everything
    assert client.get("/api/companies").json() == []


def test_reseller_admin_manages_client_companies_without_platform_admin_access(
        auth_client: TestClient, client: TestClient) -> None:
    c = auth_client
    r = c.post("/api/resellers", json={"name": "Garcia Tax & Accounting"})
    assert r.status_code == 201, r.text
    reseller = r.json()
    other = c.post("/api/resellers", json={"name": "Other Partner"}).json()
    assert c.post("/api/resellers", json={"name": "garcia tax & accounting"}).status_code == 409
    added = c.post(f"/api/resellers/{reseller['id']}/admins", json={"email": "maria@garciatax.example",
                                                                     "name": "Maria Garcia"}).json()
    assert added["temporary_password"]

    me = login(client, "maria@garciatax.example", added["temporary_password"])
    assert me["is_reseller_admin"] and me["company_count"] == 0 and me["role"] == "none"
    assert client.post("/api/resellers", json={"name": "Mine"}).status_code == 403
    assert [x["name"] for x in client.get("/api/resellers").json()] == ["Garcia Tax & Accounting"]
    assert client.post("/api/companies", json={"name": "X", "reseller_id": other["id"]}).status_code == 403
    client_co = client.post("/api/companies", json={"name": "Sunrise Bakery"})
    assert client_co.status_code == 201
    client_co = client_co.json()
    assert client_co["reseller_name"] == "Garcia Tax & Accounting" and client_co["via_reseller"]
    me = switch(client, client_co["id"])
    assert me["company_role"] == "owner"
    client.post("/api/expenses", json={"expense_date": "2026-10-01", "category_id": cat_id(client, "meals"),
                                       "description": "Team lunch", "amount": 40})
    members = client.get("/api/members").json()
    assert [(m["email"], m["via_reseller"]) for m in members] == [("maria@garciatax.example", True)]

    # The platform admin can see the reseller's company count, but can't open the client's books
    login(c, ADMIN["email"], ADMIN["password"])
    assert next(x for x in c.get("/api/resellers").json() if x["id"] == reseller["id"])["company_count"] == 1
    assert c.post(f"/api/companies/{client_co['id']}/switch").status_code == 404
    assert c.get("/api/expenses").json()["total"] == 0

    # Removing the reseller admin removes their access
    assert c.delete(f"/api/resellers/{reseller['id']}/admins/{me['id']}").status_code == 204
    login(client, "maria@garciatax.example", added["temporary_password"])
    assert client.get("/api/companies").json() == []


def test_only_admins_create_companies(auth_client: TestClient, client: TestClient) -> None:
    emp = auth_client.post("/api/members", json={"email": "bk@example.com", "role": "bookkeeper"}).json()
    login(client, "bk@example.com", emp["temporary_password"])
    assert client.post("/api/companies", json={"name": "Side Biz"}).status_code == 403


def test_logo_is_per_company(auth_client: TestClient) -> None:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (400, 100), (10, 32, 54)).save(buf, "PNG")
    c = auth_client
    a_id = c.get("/api/auth/me").json()["company_id"]
    assert c.put("/api/company/logo", files={"file": ("l.png", buf.getvalue(), "image/png")}).status_code == 200
    b = new_company(c, "No Logo Co")
    switch(c, b["id"])
    assert c.get("/api/company").json()["has_logo"] is False
    assert c.get("/api/company/branding").json()["company_id"] == b["id"]
    listed = {x["id"]: x["has_logo"] for x in c.get("/api/companies").json()}
    assert listed == {a_id: True, b["id"]: False}


def test_new_browser_opens_the_home_company_not_the_first_alphabetically(auth_client: TestClient) -> None:
    home = auth_client.get("/api/auth/me").json()["company_name"]
    new_company(auth_client, "AAA First Alphabetically")
    me = login(auth_client, ADMIN["email"], ADMIN["password"])  # cookies cleared = new browser
    assert me["company_name"] == home


def test_session_from_before_v050_gets_company_remembered(auth_client: TestClient) -> None:
    company_id = auth_client.get("/api/auth/me").json()["company_id"]
    auth_client.cookies.delete("fm_company")  # like a sign-in that started under v0.4.1
    r = auth_client.get("/api/auth/me")
    assert r.json()["company_id"] == company_id
    assert auth_client.cookies.get("fm_company") == company_id
    assert auth_client.get("/api/company/branding").json()["company_id"] == company_id
