"""v0.10.0 company rules: each company sets its own terms, payment methods, approvals, formats, custom fields,
invoice numbering and wording, bank rules, plans and roles. Nothing here should be fixed in code."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from .test_banking import CHECKING_CSV, do_import, make_account, txns
from .test_ledger import cats
from .test_multicompany import login, new_company, switch
from .test_sales import customer, email_settings, invoice, smtp  # noqa: F401


def put_rules(c: TestClient, expect: int = 200, currency: str | None = None, **rules) -> dict:
    body: dict = {"rules": rules}
    if currency:
        body["currency"] = currency
    r = c.put("/api/rules", json=body)
    assert r.status_code == expect, r.text
    return r.json()


def default_terms(c: TestClient) -> list[dict]:
    return c.get("/api/rules").json()["rules"]["terms"]


# ---------------------------------------------------------------- rules basics
def test_defaults_match_previous_behavior(auth_client: TestClient) -> None:
    r = auth_client.get("/api/rules").json()
    codes = [t["code"] for t in r["rules"]["terms"]]
    assert {"due_on_receipt", "net_15", "net_30"} <= set(codes)
    assert r["rules"]["approvals_required"] is False and r["rules"]["date_format"] == "MM/DD/YYYY"
    assert r["currency"] == "USD" and r["labels_default"]["invoice_title"] == "INVOICE"
    assert "invoice_number" in r["email_placeholders"]


def test_only_owner_changes_rules_and_changes_are_audited(auth_client: TestClient, client: TestClient) -> None:
    c = auth_client
    emp = c.post("/api/members", json={"email": "emp@example.com", "name": "Emp", "role": "employee"}).json()
    put_rules(c, forecast_days=60)
    log = c.get("/api/audit", params={"entity_type": "company"})
    if log.status_code == 200:
        assert any(e["action"] == "rules_changed" for e in log.json().get("items", log.json()))
    login(client, "emp@example.com", emp["temporary_password"])
    assert client.get("/api/rules").status_code == 200  # forms need the lists
    assert client.put("/api/rules", json={"rules": {"forecast_days": 14}}).status_code == 403


def test_bad_values_are_explained(auth_client: TestClient) -> None:
    r = put_rules(auth_client, expect=422, terms=[{"code": "Net 45!", "name": "Net 45", "days": 45}])
    assert "detail" in r
    r = put_rules(auth_client, expect=422, terms=[{"code": "eom10", "name": "10th next month",
                                                   "kind": "day_of_next_month"}])
    assert "day of the month" in r["detail"]
    put_rules(auth_client, expect=422, pdf_accent="blue")
    put_rules(auth_client, expect=422, custom_fields=[{"code": "po", "label": "PO", "entity": "invoice",
                                                       "type": "choice"}])


def test_codes_in_use_cannot_be_deleted_only_turned_off(auth_client: TestClient) -> None:
    c = auth_client
    terms = default_terms(c)
    r = put_rules(c, expect=409, terms=[t for t in terms if t["code"] != "net_30"])
    assert "Turn it off" in r["detail"]
    for t in terms:
        if t["code"] == "net_15":
            t["active"] = False
    put_rules(c, terms=terms)
    assert next(t for t in default_terms(c) if t["code"] == "net_15")["active"] is False


def test_each_company_keeps_its_own_rules(auth_client: TestClient) -> None:
    c = auth_client
    first = c.get("/api/company").json()["id"]
    put_rules(c, date_format="DD/MM/YYYY", approvals_required=True, approval_threshold=50)
    other = new_company(c, "Panadería Sol")
    switch(c, other["id"])
    assert c.get("/api/rules").json()["rules"]["date_format"] == "MM/DD/YYYY"
    assert c.get("/api/settings").json()["approval_required"] is False
    put_rules(c, currency="EUR", number_format="1.234,56")
    assert c.get("/api/settings").json()["currency"] == "EUR"
    switch(c, first)
    assert c.get("/api/settings").json()["currency"] == "USD"


# ---------------------------------------------------------------- payment terms
def test_custom_terms_drive_due_dates(auth_client: TestClient) -> None:
    c = auth_client
    terms = [t for t in default_terms(c)] + [
        {"code": "eom_10", "name": "10th of next month", "kind": "day_of_next_month", "day": 10},
        {"code": "eom", "name": "End of month + 5", "kind": "end_of_month", "days": 5},
    ]
    put_rules(c, terms=terms, default_terms="net_45")
    cust = customer(c)
    inv = invoice(c, cust, terms="net_45", invoice_date="2026-10-01")
    assert inv["due_date"] == "2026-11-15"
    assert invoice(c, cust, terms="eom_10", invoice_date="2026-12-20")["due_date"] == "2027-01-10"
    assert invoice(c, cust, terms="eom", invoice_date="2026-10-03")["due_date"] == "2026-11-05"
    # A code the company doesn't have is refused.
    r = c.post("/api/invoices", json={"customer_id": cust["id"], "invoice_date": "2026-10-01", "terms": "net_99",
                                      "lines": [{"description": "x", "rate": 1,
                                                 "category_id": cats(c)["consulting_income"]}]})
    assert r.status_code == 422
    # Customers can default to a company term.
    assert customer(c, "Net45 Co", default_terms="net_45")["default_terms"] == "net_45"
    assert c.post("/api/customers", json={"name": "Bad", "default_terms": "net_99"}).status_code == 422


def test_turned_off_term_cannot_be_used_for_new_invoices(auth_client: TestClient) -> None:
    c = auth_client
    terms = default_terms(c)
    for t in terms:
        if t["code"] == "net_15":
            t["active"] = False
    put_rules(c, terms=terms)
    cust = customer(c)
    r = c.post("/api/invoices", json={"customer_id": cust["id"], "invoice_date": "2026-10-01", "terms": "net_15",
                                      "lines": [{"description": "x", "rate": 1,
                                                 "category_id": cats(c)["consulting_income"]}]})
    assert r.status_code == 422


def test_bill_terms_come_from_rules(auth_client: TestClient) -> None:
    c = auth_client
    put_rules(c, terms=default_terms(c) + [{"code": "net_10", "name": "Net 10", "days": 10}])
    r = c.post("/api/bills", json={"vendor_name": "Brightline", "bill_date": "2026-10-02", "terms": "net_10",
                                   "lines": [{"category_id": cats(c)["contractor_fees"], "amount": 100}]})
    assert r.status_code == 201, r.text
    assert r.json()["due_date"] == "2026-10-12"


# ---------------------------------------------------------------- payment methods
def test_company_payment_methods(auth_client: TestClient, category_id: str) -> None:
    c = auth_client
    rules = c.get("/api/rules").json()["rules"]
    put_rules(c, expense_methods=rules["expense_methods"] + [{"code": "amex_gold", "label": "Amex Gold"}],
              received_methods=rules["received_methods"] + [{"code": "zelle", "label": "Zelle"}])
    r = c.post("/api/expenses", json={"expense_date": "2026-10-01", "vendor_name": "Staples", "description": "Paper", "category_id": category_id,
                                      "amount": 10, "payment_method": "amex_gold", "is_reimbursable": False})
    assert r.status_code == 201, r.text
    r = c.post("/api/expenses", json={"expense_date": "2026-10-01", "vendor_name": "Staples", "description": "Paper", "category_id": category_id,
                                      "amount": 10, "payment_method": "venmo", "is_reimbursable": False})
    assert r.status_code == 422
    cust = customer(c)
    inv = invoice(c, cust)
    chk = make_account(c)
    r = c.post("/api/payments", json={"customer_id": cust["id"], "payment_date": "2026-10-20", "account_id": chk["id"],
                                      "amount": 300, "method": "zelle",
                                      "applications": [{"invoice_id": inv["id"], "amount": 300}]})
    assert r.status_code == 201, r.text
    r = c.post("/api/payments", json={"customer_id": cust["id"], "payment_date": "2026-10-20", "account_id": chk["id"],
                                      "amount": 1, "method": "bitcoin", "applications": []})
    assert r.status_code == 422


# ---------------------------------------------------------------- approvals per company
def test_approvals_are_per_company(auth_client: TestClient, category_id: str) -> None:
    c = auth_client
    small = {"expense_date": "2026-10-01", "vendor_name": "Staples", "description": "Paper", "category_id": category_id,
             "payment_method": "business_card", "is_reimbursable": False}
    assert c.post("/api/expenses", json=small | {"amount": 900}).json()["status"] == "approved"
    put_rules(c, approvals_required=True, approval_threshold=100)
    assert c.get("/api/settings").json()["approval_required"] is True
    assert c.post("/api/expenses", json=small | {"amount": 99}).json()["status"] == "approved"
    assert c.post("/api/expenses", json=small | {"amount": 100}).json()["status"] == "pending"


# ---------------------------------------------------------------- custom fields
def test_custom_fields_validate_and_store(auth_client: TestClient) -> None:
    c = auth_client
    put_rules(c, custom_fields=[
        {"code": "po_number", "label": "PO number", "entity": "invoice", "required": True, "print_on_invoice": True},
        {"code": "region", "label": "Region", "entity": "customer", "type": "choice",
         "options": ["North", "South"], "print_on_invoice": True},
        {"code": "sku", "label": "SKU", "entity": "item"},
        {"code": "job", "label": "Job number", "entity": "expense", "type": "number"},
        {"code": "approved_on", "label": "Approved on", "entity": "bill", "type": "date"},
    ])
    assert c.post("/api/customers", json={"name": "X", "custom": {"region": "East"}}).status_code == 422
    cust = customer(c, custom={"region": "North", "unknown": "ignored"})
    assert cust["custom"] == {"region": "North"}
    it = c.post("/api/items", json={"name": "Widget", "rate": 5, "category_id": cats(c)["client_services_revenue"],
                                    "custom": {"sku": "W-100"}})
    assert it.status_code == 201 and it.json()["custom"] == {"sku": "W-100"}
    body = {"customer_id": cust["id"], "invoice_date": "2026-10-01", "terms": "net_30",
            "lines": [{"description": "x", "rate": 10, "category_id": cats(c)["consulting_income"]}]}
    r = c.post("/api/invoices", json=body)
    assert r.status_code == 422 and "PO number" in r.text
    inv = c.post("/api/invoices", json=body | {"custom": {"po_number": "PO-7781"}})
    assert inv.status_code == 201, inv.text
    assert c.get(f"/api/invoices/{inv.json()['id']}").json()["custom"] == {"po_number": "PO-7781"}
    e = c.post("/api/expenses", json={"expense_date": "2026-10-01", "vendor_name": "Home Depot", "description": "Lumber",
                                      "category_id": cats(c)["office_supplies"], "amount": 10,
                                      "payment_method": "business_card", "is_reimbursable": False,
                                      "custom": {"job": "1,250"}})
    assert e.status_code == 201 and e.json()["custom"] == {"job": 1250.0}
    bad = c.post("/api/expenses", json={"expense_date": "2026-10-01", "vendor_name": "Home Depot", "description": "Lumber",
                                        "category_id": cats(c)["office_supplies"], "amount": 10,
                                        "payment_method": "business_card", "is_reimbursable": False,
                                        "custom": {"job": "abc"}})
    assert bad.status_code == 422
    b = c.post("/api/bills", json={"vendor_name": "Brightline", "bill_date": "2026-10-02", "terms": "net_30",
                                   "custom": {"approved_on": "2026-10-03"},
                                   "lines": [{"category_id": cats(c)["contractor_fees"], "amount": 100}]})
    assert b.status_code == 201 and b.json()["custom"] == {"approved_on": "2026-10-03"}


# ---------------------------------------------------------------- invoices: numbering, PDF and email
def test_invoice_numbering_prefix_and_start(auth_client: TestClient) -> None:
    c = auth_client
    put_rules(c, invoice_prefix="FM-", next_invoice_number=5000)
    cust = customer(c)
    assert invoice(c, cust)["invoice_number"] == "FM-5000"
    assert invoice(c, cust)["invoice_number"] == "FM-5001"


def test_pdf_uses_company_wording_formats_and_custom_fields(auth_client: TestClient) -> None:
    from pypdf import PdfReader

    c = auth_client
    put_rules(c, currency="EUR", date_format="DD.MM.YYYY", number_format="1.234,56", pdf_accent="#0F766E",
              pdf_labels={"invoice_title": "FACTURA", "bill_to": "CLIENTE", "balance_due": "Saldo"},
              custom_fields=[{"code": "po_number", "label": "PO number", "entity": "invoice",
                              "print_on_invoice": True},
                             {"code": "vat_id", "label": "VAT ID", "entity": "customer", "print_on_invoice": True}])
    cust = customer(c, "Panadería Sol", custom={"vat_id": "ESB12345678"})
    inv = invoice(c, cust, invoice_date="2026-10-01", custom={"po_number": "PO-42"},
                  lines=[{"description": "Soporte", "quantity": 1, "rate": 1234.5,
                          "category_id": cats(c)["consulting_income"]}])
    r = c.get(f"/api/invoices/{inv['id']}/pdf")
    assert r.status_code == 200
    text = PdfReader(io.BytesIO(r.content)).pages[0].extract_text()
    for expected in ("FACTURA", "CLIENTE", "Saldo", "01.10.2026", "1.234,50", "PO-42", "ESB12345678"):
        assert expected in text, (expected, text)
    assert "INVOICE" not in text


def test_email_template_is_the_companys(auth_client: TestClient, smtp) -> None:
    c = auth_client
    email_settings(c)
    put_rules(c, email_subject="Factura {invoice_number} de {company}",
              email_body="Hola {customer}, adjuntamos la factura por {total}. Vence {due_date}. {nope}")
    cust = customer(c)
    inv = invoice(c, cust, invoice_date="2026-10-01")
    d = c.get(f"/api/invoices/{inv['id']}/email-draft").json()
    assert d["subject"].startswith("Factura 1001 de ")
    assert "Hola Acme Dental Group" in d["body"] and "$300.00" in d["body"] and "10/31/2026" in d["body"]
    assert "{nope}" in d["body"]  # unknown placeholders are left as typed


# ---------------------------------------------------------------- dashboard periods
def test_dashboard_periods_follow_rules(auth_client: TestClient) -> None:
    c = auth_client
    put_rules(c, forecast_days=60, coming_up_days=7)
    d = c.get("/api/dashboard/overview").json()
    assert d["forecast_days"] == 60 and d["coming_up_days"] == 7


# ---------------------------------------------------------------- bank rules
def test_bank_rules_categorize_and_auto_approve(auth_client: TestClient) -> None:
    c = auth_client
    k = cats(c)
    acct = make_account(c)
    r = c.post("/api/bank-rules", json={"name": "Microsoft", "match_text": "microsoft", "direction": "out",
                                        "category_id": k["software_licenses"], "vendor_name": "Microsoft",
                                        "auto_approve": True})
    assert r.status_code == 201, r.text
    rule = r.json()
    assert c.post("/api/bank-rules", json={"name": "Nothing", "match_text": "x"}).status_code == 422
    assert do_import(c, acct["id"], CHECKING_CSV).status_code in (200, 201)
    items = txns(c)["items"]
    ms = [t for t in items if "MICROSOFT" in t["description"]]
    assert ms and all(t["review_status"] != "unreviewed" or t.get("duplicate_of_id") for t in ms)
    approved = [t for t in ms if t["review_status"] != "unreviewed"]
    assert approved
    coffee = next(t for t in items if "BLUE BOTTLE" in t["description"])
    assert not (coffee.get("suggestion_reason") or "").startswith("Your rule")
    listed = c.get("/api/bank-rules").json()
    assert listed[0]["times_used"] >= 1 and listed[0]["category_name"]
    # A rule added later can be run over what's waiting.
    c.post("/api/bank-rules", json={"name": "Coffee", "match_text": "BLUE BOTTLE", "category_id": k["meals"]})
    out = c.post("/api/bank-rules/apply").json()
    assert out["matched"] >= 1
    coffee = next(t for t in txns(c)["items"] if "BLUE BOTTLE" in t["description"])
    assert coffee["suggestion_reason"] == "Your rule: Coffee" and coffee["suggested_category_id"] == k["meals"]
    assert c.delete(f"/api/bank-rules/{rule['id']}").status_code == 204
    assert c.delete(f"/api/bank-rules/{rule['id']}").status_code == 404


def test_bank_rules_belong_to_one_company(auth_client: TestClient) -> None:
    c = auth_client
    c.post("/api/bank-rules", json={"name": "Coffee", "match_text": "COFFEE", "category_id": cats(c)["meals"]})
    other = new_company(c, "Other Co")
    switch(c, other["id"])
    assert c.get("/api/bank-rules").json() == []


# ---------------------------------------------------------------- plans as data
def test_plans_are_editable_data(auth_client: TestClient) -> None:
    c = auth_client
    cat = c.get("/api/plans/catalog").json()
    keys = [p["key"] for p in cat["plans"]]
    assert keys[:4] == ["starter", "essentials", "plus", "advanced"] and all(p["editable"] for p in cat["plans"])
    r = c.post("/api/plans/catalog", json={"key": "nonprofit", "label": "Nonprofit", "modules": ["invoicing", "bills"],
                                           "user_limit": 10, "monthly_price": 19})
    assert r.status_code == 201, r.text
    assert c.post("/api/plans/catalog", json={"key": "nonprofit", "label": "Again"}).status_code == 409
    assert c.post("/api/plans/catalog", json={"key": "x", "label": "X", "modules": ["teleport"]}).status_code == 422
    co = new_company(c, "Food Bank")
    r = c.put(f"/api/plans/companies/{co['id']}", json={"plan": "nonprofit"})
    assert r.status_code == 200, r.text
    assert r.json()["plan_label"] == "Nonprofit" and r.json()["user_limit"] == 10
    starter = next(p for p in cat["plans"] if p["key"] == "starter")
    c.put(f"/api/plans/companies/{co['id']}", json={"plan": "starter"})
    edit = {"label": "Starter", "modules": ["invoicing", "bills"], "user_limit": 2}
    assert c.put(f"/api/plans/catalog/{starter['id']}", json=edit).status_code == 200
    mine = next(x for x in c.get("/api/plans/companies").json() if x["id"] == co["id"])
    assert mine["user_limit"] == 1  # not applied to existing companies unless asked
    c.put(f"/api/plans/catalog/{starter['id']}", params={"apply_to_companies": True}, json=edit)
    mine = next(x for x in c.get("/api/plans/companies").json() if x["id"] == co["id"])
    assert mine["user_limit"] == 2 and "bills" in mine["modules"]


# ---------------------------------------------------------------- custom roles
def test_custom_role_narrows_access(auth_client: TestClient, client: TestClient) -> None:
    c = auth_client
    areas = c.get("/api/roles/areas").json()
    assert "banking" in areas["areas"] and areas["base"]["owner"]["banking"] == "full"
    r = c.post("/api/roles", json={"name": "Front desk", "base_role": "bookkeeper",
                                   "permissions": {"banking": "none", "accounting": "none", "reports": "view"}})
    assert r.status_code == 201, r.text
    role = r.json()
    assert role["effective"]["banking"] == "none" and role["effective"]["sales"] == "full"
    # Can't widen: an employee base stays without banking even if asked for full.
    wide = c.post("/api/roles", json={"name": "Wide", "base_role": "employee", "permissions": {"banking": "full"}})
    assert wide.json()["effective"]["banking"] == "none"
    assert c.post("/api/roles", json={"name": "Bad", "base_role": "viewer",
                                      "permissions": {"rockets": "none"}}).status_code == 422
    added = c.post("/api/members", json={"email": "desk@example.com", "name": "Desk", "role": "bookkeeper",
                                         "custom_role_id": role["id"]})
    assert added.status_code == 201, added.text
    assert added.json()["member"]["custom_role_name"] == "Front desk"
    me = login(client, "desk@example.com", added.json()["temporary_password"])
    who = client.get("/api/auth/me").json()
    assert who["permissions"]["banking"] == "none" and who["custom_role_name"] == "Front desk"
    assert client.get("/api/transactions", params={"tab": "all"}).status_code == 403
    assert client.post("/api/accounts", json={"name": "X", "kind": "checking"}).status_code == 403
    assert client.get("/api/accounts").status_code == 200  # lookups still work for forms
    assert client.get("/api/invoices").status_code == 200
    cu = client.post("/api/customers", json={"name": "Walk-in"})
    assert cu.status_code == 201, cu.text
    assert client.get("/api/ledger/journal").status_code in (403, 404, 405)


def test_deleting_a_role_returns_members_to_base(auth_client: TestClient) -> None:
    c = auth_client
    role = c.post("/api/roles", json={"name": "No banking", "base_role": "accountant",
                                      "permissions": {"banking": "none"}}).json()
    added = c.post("/api/members", json={"email": "acc@example.com", "name": "Acc", "role": "accountant",
                                         "custom_role_id": role["id"]}).json()
    uid = added["member"]["user_id"] if "user_id" in added["member"] else added["member"]["id"]
    assert c.get("/api/roles").json()[0]["member_count"] == 1
    assert c.delete(f"/api/roles/{role['id']}").status_code == 204
    m = next(x for x in c.get("/api/members").json() if x.get("user_id", x.get("id")) == uid)
    assert m["custom_role_id"] is None and m["role"] == "accountant"


def test_owner_with_custom_role_does_not_count_as_full_owner(auth_client: TestClient) -> None:
    c = auth_client
    role = c.post("/api/roles", json={"name": "Limited owner", "base_role": "owner",
                                      "permissions": {"team": "none"}}).json()
    me = c.get("/api/auth/me").json()
    admin_id = me.get("id") or me["user"]["id"]
    # The only full owner can't be put on a narrowing role (the company would lose its owner).
    r = c.put(f"/api/members/{admin_id}", json={"role": "owner", "custom_role_id": role["id"]})
    assert r.status_code == 409
