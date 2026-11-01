"""v0.7.0 sales: products and services, invoices, billable expenses, receive payment, PDF, email, reports."""

from __future__ import annotations

import io
import smtplib
from email import message_from_bytes
from email.policy import default as default_policy

import pytest
from fastapi.testclient import TestClient

from .test_banking import do_import, make_account
from .test_ledger import assert_balanced, bal, cats, expense, ledger, snapshot
from .test_multicompany import new_company, switch

DEPOSIT_CSV = b"""Date,Description,Amount,Balance
10/20/2026,STRIPE TRANSFER ACME DENTAL,1500.00,2500.00
"""


# ---------------------------------------------------------------- helpers
def customer(c: TestClient, name: str = "Acme Dental Group", **kw) -> dict:
    r = c.post("/api/customers", json={"name": name, "email": "office@acme.example", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def item(c: TestClient, name: str = "Managed IT - per user", rate: float = 85, code: str = "client_services_revenue"):
    r = c.post("/api/items", json={"name": name, "rate": rate, "category_id": cats(c)[code]})
    assert r.status_code == 201, r.text
    return r.json()


def invoice(c: TestClient, cust: dict, lines: list[dict] | None = None, **kw) -> dict:
    body = {"customer_id": cust["id"], "invoice_date": "2026-10-01", "terms": "net_30",
            "lines": lines or [{"description": "Consulting", "quantity": 2, "rate": 150,
                                "category_id": cats(c)["consulting_income"]}]} | kw
    r = c.post("/api/invoices", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def pay(c: TestClient, cust: dict, account: dict, apps: list[tuple[dict, float]], expect: int = 201, **kw):
    body = {"customer_id": cust["id"], "payment_date": "2026-10-20", "account_id": account["id"],
            "amount": round(sum(a for _, a in apps), 2), "method": "ach",
            "applications": [{"invoice_id": i["id"], "amount": a} for i, a in apps]} | kw
    r = c.post("/api/payments", json=body)
    assert r.status_code == expect, r.text
    return r.json()


class FakeSMTP:
    sent: list = []
    logins: list = []
    fail_login = False

    def __init__(self, *a, **kw):
        pass

    def login(self, user, password):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")
        FakeSMTP.logins.append((user, password))

    def send_message(self, msg, from_addr=None, to_addrs=None):
        FakeSMTP.sent.append((msg, from_addr, list(to_addrs or [])))

    def quit(self):
        pass


@pytest.fixture
def smtp(monkeypatch):
    from app.invoicing import mailer

    FakeSMTP.sent, FakeSMTP.logins, FakeSMTP.fail_login = [], [], False
    monkeypatch.setattr(mailer, "_connect", lambda cfg: FakeSMTP())
    return FakeSMTP


def email_settings(c: TestClient, **kw) -> dict:
    body = {"smtp_host": "smtp.office365.com", "smtp_port": 587, "security": "starttls",
            "username": "billing@fmitai.com", "password": "s3cret-app-password", "from_email": "billing@fmitai.com",
            "from_name": "F&M IT Services", "copy_me": True} | kw
    r = c.put("/api/email-settings", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- products and services
def test_items_need_an_income_category_and_unique_names(auth_client: TestClient) -> None:
    c = auth_client
    it = item(c)
    assert it["category_name"] == "Client services revenue" and it["rate"] == 85
    assert c.post("/api/items", json={"name": "managed it - PER USER", "category_id": cats(c)["consulting_income"]}
                  ).status_code == 409
    assert c.post("/api/items", json={"name": "Laptop", "category_id": cats(c)["meals"]}).status_code == 422
    r = c.put(f"/api/items/{it['id']}", json={"name": "Managed IT", "rate": 90, "is_active": False,
                                               "category_id": cats(c)["client_services_revenue"]})
    assert r.status_code == 200 and r.json()["rate"] == 90
    assert c.get("/api/items").json() == [] and len(c.get("/api/items", params={"include_inactive": True}).json()) == 1


# ---------------------------------------------------------------- invoices
def test_invoice_posts_to_ar_and_income_with_numbers_terms_and_status(auth_client: TestClient) -> None:
    c = auth_client
    cust = customer(c)
    it = item(c)
    inv = invoice(c, cust, lines=[
        {"item_id": it["id"], "quantity": 12, "rate": 85, "service_date": "2026-10-01"},
        {"description": "vCIO session", "quantity": 2.5, "rate": 175, "category_id": cats(c)["consulting_income"]},
    ])
    assert inv["invoice_number"] == "1001" and inv["due_date"] == "2026-10-31" and inv["status"] in ("not_sent", "overdue")
    assert inv["total"] == 1457.5 and inv["balance"] == 1457.5
    assert inv["lines"][0]["item_name"] == "Managed IT - per user" and inv["lines"][0]["amount"] == 1020
    assert bal(c, "Accounts Receivable (A/R)") == 1457.5
    assert bal(c, "Client services revenue") == 1020 and bal(c, "Consulting income") == 437.5
    assert c.get("/api/invoices/next-number").json()["invoice_number"] == "1002"
    assert invoice(c, cust)["invoice_number"] == "1002"
    # Numbers are unique; a prefixed number continues with its prefix and width.
    r = c.post("/api/invoices", json={"customer_id": cust["id"], "invoice_number": "1001", "invoice_date": "2026-10-02",
                                      "lines": [{"description": "x", "rate": 1, "category_id": cats(c)["other_income"]}]})
    assert r.status_code == 409
    invoice(c, cust, invoice_number="INV-0042")
    assert c.get("/api/invoices/next-number").json()["invoice_number"] == "INV-0043"
    assert_balanced(c)


def test_invoice_validation(auth_client: TestClient) -> None:
    c = auth_client
    cust = customer(c)
    base = {"customer_id": cust["id"], "invoice_date": "2026-10-01"}
    # An expense category isn't income.
    r = c.post("/api/invoices", json=base | {"lines": [{"rate": 10, "category_id": cats(c)["meals"]}]})
    assert r.status_code == 422
    # A line needs a product/service or an income category.
    assert c.post("/api/invoices", json=base | {"lines": [{"rate": 10}]}).status_code == 422
    # Due date before the invoice date.
    r = c.post("/api/invoices", json=base | {"due_date": "2026-09-01",
                                             "lines": [{"rate": 10, "category_id": cats(c)["other_income"]}]})
    assert r.status_code == 422
    assert c.post("/api/invoices", json=base | {"bill_email": "not-an-email",
                                                "lines": [{"rate": 10, "category_id": cats(c)["other_income"]}]}
                  ).status_code == 422


def test_billable_expenses_go_on_the_invoice_once(auth_client: TestClient) -> None:
    c = auth_client
    acct = make_account(c)
    cust = customer(c)
    other = customer(c, "Bayview Realty")
    k = cats(c)
    e = expense(c, payment_account_id=acct["id"], lines=[
        {"category_id": k["hardware_equipment"], "amount": 189.99, "description": "USB-C dock", "billable": True,
         "customer_id": cust["id"]},
        {"category_id": k["office_supplies"], "amount": 20}])
    bill = c.post("/api/bills", json={"vendor_name": "Brightline Networks", "bill_date": "2026-10-02", "terms": "net_30",
                                      "lines": [{"category_id": k["contractor_fees"], "amount": 400, "billable": True,
                                                 "customer_id": cust["id"], "description": "Cabling"}]}).json()
    found = c.get("/api/invoices/billable", params={"customer_id": cust["id"]}).json()
    assert [(f["source"], f["amount"]) for f in found] == [("expense", 189.99), ("bill", 400)]
    assert c.get("/api/invoices/billable", params={"customer_id": other["id"]}).json() == []
    exp_line = found[0]["line_id"]
    bill_line = found[1]["line_id"]
    inv = invoice(c, cust, lines=[
        {"description": "USB-C dock", "rate": 189.99, "expense_line_id": exp_line},
        {"description": "Cabling (with 10% markup)", "rate": 440, "bill_line_id": bill_line},
    ])
    assert inv["lines"][0]["category_name"] == "Billable Expense Income"
    assert bal(c, "Billable Expense Income") == 629.99
    assert bal(c, "Hardware & Equipment") == 189.99  # the expense itself stays an expense
    assert c.get("/api/invoices/billable", params={"customer_id": cust["id"]}).json() == []
    # Not twice, and not for another customer.
    r = c.post("/api/invoices", json={"customer_id": cust["id"], "invoice_date": "2026-10-05",
                                      "lines": [{"rate": 189.99, "expense_line_id": exp_line}]})
    assert r.status_code == 409
    r = c.post("/api/invoices", json={"customer_id": other["id"], "invoice_date": "2026-10-05",
                                      "lines": [{"rate": 400, "bill_line_id": bill_line}]})
    assert r.status_code == 422
    # Editing the same invoice keeps its own lines available to it.
    r = c.put(f"/api/invoices/{inv['id']}", json={"customer_id": cust["id"], "invoice_date": "2026-10-01",
                                                   "lines": [{"rate": 189.99, "expense_line_id": exp_line}]})
    assert r.status_code == 200, r.text
    assert len(c.get("/api/invoices/billable", params={"customer_id": cust["id"]}).json()) == 1
    # Voiding frees them.
    assert c.post(f"/api/invoices/{inv['id']}/void").json()["status"] == "void"
    assert len(c.get("/api/invoices/billable", params={"customer_id": cust["id"]}).json()) == 2
    assert bal(c, "Billable Expense Income") == 0 and bal(c, "Accounts Receivable (A/R)") == 0
    assert e and bill
    assert_balanced(c)


def test_receive_payment_across_invoices_and_statuses(auth_client: TestClient) -> None:
    c = auth_client
    chk = make_account(c)  # opening 1000
    cust = customer(c)
    a = invoice(c, cust, invoice_date="2026-10-01")  # 300
    b = invoice(c, cust, invoice_date="2026-10-05", lines=[
        {"description": "Onsite", "rate": 450, "category_id": cats(c)["client_services_revenue"]}])
    p1 = pay(c, cust, chk, [(a, 100)])
    assert c.get(f"/api/invoices/{a['id']}").json()["status"] in ("partial", "overdue")
    assert c.get(f"/api/invoices/{a['id']}").json()["balance"] == 200
    pay(c, cust, chk, [(a, 200), (b, 450)], reference="1042")
    for inv in (a, b):
        d = c.get(f"/api/invoices/{inv['id']}").json()
        assert d["status"] == "paid" and d["balance"] == 0
    assert bal(c, "Accounts Receivable (A/R)") == 0
    assert bal(c, "Chase Business Checking") == 1000 + 750
    assert len(c.get(f"/api/invoices/{a['id']}").json()["payments"]) == 2
    # Validation
    c3 = invoice(c, cust)
    pay(c, cust, chk, [(c3, 301)], expect=422)  # more than the balance
    r = c.post("/api/payments", json={"customer_id": cust["id"], "payment_date": "2026-10-20", "account_id": chk["id"],
                                      "amount": 100, "applications": [{"invoice_id": c3["id"], "amount": 50}]})
    assert r.status_code == 422  # must apply the whole payment
    other = customer(c, "Bayview Realty")
    pay(c, other, chk, [(c3, 50)], expect=422)  # someone else's invoice
    # Paid invoices can't be voided or deleted until the payments go.
    assert c.post(f"/api/invoices/{a['id']}/void").status_code == 409
    assert c.delete(f"/api/invoices/{a['id']}").status_code == 409
    # Can't lower the total below what's been received.
    r = c.put(f"/api/invoices/{a['id']}", json={"customer_id": cust["id"], "invoice_date": "2026-10-01",
                                                 "lines": [{"rate": 50, "category_id": cats(c)["consulting_income"]}]})
    assert r.status_code == 409
    assert c.delete(f"/api/payments/{p1['id']}").status_code == 204
    assert c.get(f"/api/invoices/{a['id']}").json()["balance"] == 100
    assert bal(c, "Accounts Receivable (A/R)") == 100 + 300
    page = c.get("/api/invoices", params={"show": "unpaid"}).json()
    assert page["total_open"] == 400 and page["count_open"] == 2
    assert_balanced(c)


def test_payment_matches_bank_deposit_without_double_counting(auth_client: TestClient) -> None:
    c = auth_client
    chk = make_account(c)
    cust = customer(c)
    inv = invoice(c, cust, lines=[{"description": "Project", "rate": 1500,
                                   "category_id": cats(c)["client_services_revenue"]}])
    do_import(c, chk["id"], DEPOSIT_CSV)
    found = c.get("/api/payments/deposit-candidates", params={"account_id": chk["id"], "amount": 1500,
                                                               "payment_date": "2026-10-18"}).json()
    assert len(found) == 1
    txn_id = found[0]["id"]
    p = pay(c, cust, chk, [(inv, 1500)], transaction_id=txn_id)
    t = next(t for t in c.get("/api/transactions", params={"tab": "all"}).json()["items"] if t["id"] == txn_id)
    assert t["review_status"] == "approved" and t["customer_payment_id"] == p["id"] and t["invoice_ids"] == [inv["id"]]
    # Income counted once (from the invoice), cash once (from the payment).
    assert bal(c, "Client services revenue") == 1500
    assert bal(c, "Chase Business Checking") == 1000 + 1500
    assert c.get("/api/payments/deposit-candidates", params={"account_id": chk["id"], "amount": 1500,
                                                              "payment_date": "2026-10-18"}).json() == []
    assert_balanced(c)
    # Removing the payment sends the deposit back to review.
    c.delete(f"/api/payments/{p['id']}")
    t = next(t for t in c.get("/api/transactions", params={"tab": "all"}).json()["items"] if t["id"] == txn_id)
    assert t["review_status"] == "unreviewed" and t["customer_payment_id"] is None
    assert bal(c, "Chase Business Checking") == 1000 and bal(c, "Accounts Receivable (A/R)") == 1500
    assert_balanced(c)


def test_void_and_delete(auth_client: TestClient) -> None:
    c = auth_client
    cust = customer(c)
    a = invoice(c, cust)
    b = invoice(c, cust)
    v = c.post(f"/api/invoices/{a['id']}/void").json()
    assert v["status"] == "void" and v["balance"] == 0 and v["voided_at"]
    r = c.put(f"/api/invoices/{a['id']}", json={"customer_id": cust["id"], "invoice_date": "2026-10-01",
                                                 "lines": [{"rate": 5, "category_id": cats(c)["other_income"]}]})
    assert r.status_code == 409
    assert c.delete(f"/api/invoices/{b['id']}").status_code == 204
    assert c.get(f"/api/invoices/{b['id']}").status_code == 404
    assert bal(c, "Accounts Receivable (A/R)") == 0 and bal(c, "Consulting income") == 0
    # The void invoice keeps its number.
    assert c.get("/api/invoices/next-number").json()["invoice_number"] == "1003"
    assert_balanced(c)


def test_closing_date_blocks_old_invoices(auth_client: TestClient) -> None:
    c = auth_client
    cust = customer(c)
    inv = invoice(c, cust, invoice_date="2026-09-15")
    assert c.put("/api/ledger/closing-date", json={"closing_date": "2026-09-30"}).status_code == 200
    r = c.post("/api/invoices", json={"customer_id": cust["id"], "invoice_date": "2026-09-20",
                                      "lines": [{"rate": 5, "category_id": cats(c)["other_income"]}]})
    assert r.status_code == 409
    assert c.post(f"/api/invoices/{inv['id']}/void").status_code == 409
    c.put("/api/ledger/closing-date", json={"closing_date": None})


def test_manual_journal_cannot_touch_ar(auth_client: TestClient) -> None:
    c = auth_client
    make_account(c)
    acc = ledger(c)
    r = c.post("/api/ledger/journal", json={"entry_date": "2026-10-05", "lines": [
        {"account_id": acc["Accounts Receivable (A/R)"]["id"], "debit": 10},
        {"account_id": acc["Chase Business Checking"]["id"], "credit": 10}]})
    assert r.status_code == 422


# ---------------------------------------------------------------- PDF
def test_invoice_pdf_has_the_invoice_details(auth_client: TestClient) -> None:
    from pypdf import PdfReader

    c = auth_client
    c.put("/api/company", json={"name": "F&M IT Services", "legal_name": "F&M IT Services LLC",
                                "fiscal_year_start_month": 1, "address": "1234 Pembroke Rd\nPembroke Pines, FL 33023",
                                "phone": "(954) 555-0142", "invoice_footer": "Pay by ACH to account ending 7788."})
    company = c.get("/api/company").json()
    assert company["address"].startswith("1234") and company["invoice_footer"]
    # Saving only the name keeps the invoice details.
    c.put("/api/company", json={"name": "F&M IT Services", "legal_name": "F&M IT Services LLC",
                                "fiscal_year_start_month": 1})
    assert c.get("/api/company").json()["phone"] == "(954) 555-0142"
    cust = customer(c, "Clínica Peña", billing_address="500 Biscayne Blvd\nMiami, FL 33132")
    inv = invoice(c, cust, message="Thank you — we appreciate your business.")
    r = c.get(f"/api/invoices/{inv['id']}/pdf", params={"download": True})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and "Invoice-1001.pdf" in r.headers["content-disposition"]
    text = PdfReader(io.BytesIO(r.content)).pages[0].extract_text()
    for expected in ("INVOICE", "1001", "Clínica Peña", "F&M IT Services LLC", "Pembroke Pines", "$300.00",
                     "Pay by ACH", "Thank you - we appreciate"):
        assert expected in text, (expected, text)


def test_pdf_shows_paid_stamp_and_logo(auth_client: TestClient) -> None:
    from PIL import Image
    from pypdf import PdfReader

    c = auth_client
    buf = io.BytesIO()
    Image.new("RGB", (400, 120), (31, 78, 140)).save(buf, "PNG")
    assert c.put("/api/company/logo", files={"file": ("logo.png", buf.getvalue(), "image/png")}).status_code == 200
    chk = make_account(c)
    cust = customer(c)
    inv = invoice(c, cust)
    pay(c, cust, chk, [(inv, 300)])
    pdf = c.get(f"/api/invoices/{inv['id']}/pdf").content
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    assert "PAID" in page.extract_text() and "$0.00" in page.extract_text()
    assert len(page.images) == 1


# ---------------------------------------------------------------- email
def test_email_settings_keep_the_password_secret(auth_client: TestClient) -> None:
    c = auth_client
    assert c.get("/api/email-settings").json()["configured"] is False
    out = email_settings(c)
    assert out["configured"] and out["has_password"] and "password" not in out
    from sqlalchemy import text

    from app.database import get_engine

    with get_engine().connect() as conn:
        stored = conn.execute(text("SELECT password_encrypted FROM email_settings")).scalar()
    assert stored and "s3cret" not in stored
    # Saving without a password keeps the old one; an empty string clears it.
    out = email_settings(c, password=None, from_name="Billing")
    assert out["has_password"] and out["from_name"] == "Billing"
    assert email_settings(c, password="")["has_password"] is False
    assert c.put("/api/email-settings", json={"smtp_host": "x", "smtp_port": 587, "from_email": "nope"}).status_code == 422


def test_send_invoice_by_email_with_pdf(auth_client: TestClient, smtp) -> None:
    c = auth_client
    cust = customer(c, cc_emails="ap@acme.example; owner@acme.example")
    inv = invoice(c, cust)
    assert c.get(f"/api/invoices/{inv['id']}/email-draft").json()["configured"] is False
    r = c.post(f"/api/invoices/{inv['id']}/send", json={"to": ["office@acme.example"], "subject": "x", "body": "y"})
    assert r.status_code == 409
    email_settings(c)
    draft = c.get(f"/api/invoices/{inv['id']}/email-draft").json()
    assert draft["to"] == ["office@acme.example"] and draft["cc"] == ["ap@acme.example", "owner@acme.example"]
    assert "Invoice 1001" in draft["subject"] and "$300.00" in draft["body"]
    r = c.post(f"/api/invoices/{inv['id']}/send", json={"to": draft["to"], "cc": draft["cc"],
                                                         "subject": draft["subject"], "body": draft["body"]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["sent_at"] and d["status"] in ("sent", "overdue") and d["emails"][0]["status"] == "sent"
    assert smtp.logins == [("billing@fmitai.com", "s3cret-app-password")]
    msg, sender, rcpts = smtp.sent[0]
    assert sender == "billing@fmitai.com"
    assert sorted(rcpts) == sorted(["office@acme.example", "ap@acme.example", "owner@acme.example",
                                    "billing@fmitai.com"])  # copy to me goes by Bcc
    parsed = message_from_bytes(msg.as_bytes(), policy=default_policy)
    assert "Bcc" not in parsed and parsed["From"] == "F&M IT Services <billing@fmitai.com>"
    attachments = [p for p in parsed.iter_attachments()]
    assert attachments[0].get_filename() == "Invoice-1001.pdf"
    assert attachments[0].get_content().startswith(b"%PDF")


def test_failed_email_is_logged_and_explained(auth_client: TestClient, smtp) -> None:
    c = auth_client
    cust = customer(c)
    inv = invoice(c, cust)
    email_settings(c)
    smtp.fail_login = True
    r = c.post(f"/api/invoices/{inv['id']}/send", json={"to": ["office@acme.example"], "subject": "s", "body": "b"})
    assert r.status_code == 502 and "app password" in r.json()["detail"]
    d = c.get(f"/api/invoices/{inv['id']}").json()
    assert d["sent_at"] is None and d["emails"][0]["status"] == "failed"
    r = c.post("/api/email-settings/test", json={"to": "me@fmitai.com"})
    assert r.status_code == 502
    smtp.fail_login = False
    assert c.post("/api/email-settings/test", json={"to": "me@fmitai.com"}).json()["sent"] is True


def test_mark_sent_for_invoices_sent_by_hand(auth_client: TestClient) -> None:
    c = auth_client
    inv = invoice(c, customer(c), invoice_date="2030-01-01")
    assert inv["status"] == "not_sent"
    assert c.post(f"/api/invoices/{inv['id']}/mark-sent").json()["status"] == "sent"
    assert c.post(f"/api/invoices/{inv['id']}/mark-sent", params={"sent": False}).json()["status"] == "not_sent"


# ---------------------------------------------------------------- customers and reports
def test_customer_balances_and_payment_history(auth_client: TestClient) -> None:
    c = auth_client
    chk = make_account(c)
    cust = customer(c, default_terms="net_15", phone="305-555-0100")
    a = invoice(c, cust, invoice_date="2026-09-01", terms="net_15")
    b = invoice(c, cust, invoice_date="2026-09-10", terms="net_15")
    invoice(c, cust, invoice_date="2030-01-01")
    pay(c, cust, chk, [(a, 300)], payment_date="2026-09-11")  # 10 days, on time
    pay(c, cust, chk, [(b, 300)], payment_date="2026-10-10")  # 30 days, late
    listing = {x["name"]: x for x in c.get("/api/customers").json()}
    assert listing["Acme Dental Group"]["open_balance"] == 300
    d = c.get(f"/api/customers/{cust['id']}").json()
    assert d["avg_days_to_pay"] == 20 and d["on_time_percent"] == 50
    assert d["invoice_count"] == 3 and d["paid_invoice_count"] == 2 and len(d["payments"]) == 2
    assert d["default_terms"] == "net_15" and d["phone"] == "305-555-0100"
    # No terms or due date on the invoice: the customer's default terms apply.
    r = c.post("/api/invoices", json={"customer_id": cust["id"], "invoice_date": "2026-10-01",
                                      "lines": [{"rate": 10, "category_id": cats(c)["other_income"]}]}).json()
    assert r["terms"] == "net_15" and r["due_date"] == "2026-10-16"
    # Updating one field keeps the others.
    c.put(f"/api/customers/{cust['id']}", json={"name": "Acme Dental Group", "is_active": True})
    assert c.get(f"/api/customers/{cust['id']}").json()["phone"] == "305-555-0100"


def test_ar_aging_and_sales_by_customer(auth_client: TestClient) -> None:
    c = auth_client
    chk = make_account(c)
    acme, bay = customer(c), customer(c, "Bayview Realty")
    invoice(c, acme, invoice_date="2026-10-01", due_date="2026-10-31")  # current on Nov 15? 15 days late
    invoice(c, acme, invoice_date="2026-07-01", due_date="2026-07-31")  # 107 days late
    old = invoice(c, bay, invoice_date="2026-08-01", due_date="2026-08-31")  # 76 days late
    pay(c, bay, chk, [(old, 100)], payment_date="2026-11-01")
    aging = c.get("/api/sales/aging", params={"as_of": "2026-11-15"}).json()
    rows = {r["customer_name"]: r for r in aging["rows"]}
    assert rows["Acme Dental Group"]["d1_30"] == 300 and rows["Acme Dental Group"]["d91_plus"] == 300
    assert rows["Bayview Realty"]["d61_90"] == 200 and aging["totals"]["total"] == 800
    # As of an earlier date the payment hadn't come in yet.
    earlier = c.get("/api/sales/aging", params={"as_of": "2026-10-15"}).json()
    assert {r["customer_name"]: r["total"] for r in earlier["rows"]}["Bayview Realty"] == 300
    sales = c.get("/api/sales/by-customer", params={"date_from": "2026-01-01", "date_to": "2026-12-31"}).json()
    assert {r["customer_name"]: r["amount"] for r in sales["rows"]} == {"Acme Dental Group": 600, "Bayview Realty": 300}
    assert sales["total"] == 900
    s = c.get("/api/sales/summary").json()
    assert s["open_total"] == 800 and s["open_count"] == 3


def test_sales_rebuild_matches_incremental(auth_client: TestClient) -> None:
    import uuid as _uuid

    from app.database import get_session_factory
    from app.ledger.books import rebuild
    from app.tenancy import set_company

    c = auth_client
    chk = make_account(c)
    cust = customer(c)
    k = cats(c)
    e = expense(c, payment_account_id=chk["id"], lines=[{"category_id": k["hardware_equipment"], "amount": 50,
                                                          "billable": True, "customer_id": cust["id"]}])
    line = c.get("/api/invoices/billable", params={"customer_id": cust["id"]}).json()[0]["line_id"]
    inv = invoice(c, cust, lines=[{"rate": 55, "expense_line_id": line},
                                  {"rate": 100, "category_id": k["client_services_revenue"]}])
    do_import(c, chk["id"], DEPOSIT_CSV)
    pay(c, cust, chk, [(inv, 100)])
    invoice(c, cust)
    before = snapshot(c)
    company_id = _uuid.UUID(c.get("/api/auth/me").json()["company_id"])
    with get_session_factory()() as db:
        set_company(db, company_id)
        rebuild(db, company_id)
        db.commit()
    assert snapshot(c) == before and e
    assert_balanced(c)


def test_invoices_are_per_company(auth_client: TestClient) -> None:
    c = auth_client
    inv = invoice(c, customer(c))
    first = c.get("/api/auth/me").json()["company_id"]
    b = new_company(c, "Second Co")
    switch(c, b["id"])
    assert c.get(f"/api/invoices/{inv['id']}").status_code == 404
    assert c.get(f"/api/invoices/{inv['id']}/pdf").status_code == 404
    assert c.get("/api/invoices", params={"show": "all"}).json()["items"] == []
    assert c.get("/api/invoices/next-number").json()["invoice_number"] == "1001"
    other = customer(c, "Local Customer")
    assert invoice(c, other)["invoice_number"] == "1001"  # numbering is per company
    switch(c, first)
    assert c.get(f"/api/invoices/{inv['id']}").status_code == 200


# ---------------------------------------------------------------- v0.7.1: Microsoft 365 sign-in
CLIENT = "11111111-2222-3333-4444-555555555555"


class FakeMicrosoft:
    """Stands in for login.microsoftonline.com and graph.microsoft.com."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.pending = 1  # polls answered "authorization_pending" before success
        self.refresh_ok = True
        self.sent: list[dict] = []

    def __call__(self, method, url, form=None, body=None, token=None):
        self.calls.append((method, url, form, body, token))
        if url.endswith("/devicecode"):
            if form["client_id"] == "00000000-0000-0000-0000-000000000000":
                return 400, {"error": "unauthorized_client",
                             "error_description": "AADSTS700016: Application not found in the directory."}
            return 200, {"device_code": "DEV-123", "user_code": "ABCD-EFGH", "interval": 1, "expires_in": 900,
                         "verification_uri": "https://microsoft.com/devicelogin"}
        if url.endswith("/token") and form["grant_type"].endswith("device_code"):
            if self.pending:
                self.pending -= 1
                return 400, {"error": "authorization_pending"}
            return 200, {"access_token": "AT-1", "refresh_token": "RT-1"}
        if url.endswith("/token") and form["grant_type"] == "refresh_token":
            if not self.refresh_ok:
                return 400, {"error": "invalid_grant", "error_description": "AADSTS70043: The refresh token has expired."}
            return 200, {"access_token": "AT-2", "refresh_token": "RT-2"}
        if "/me?" in url:
            return 200, {"displayName": "Francisco Morales", "mail": "billing@fmitai.com"}
        if url.endswith("/me/sendMail"):
            self.sent.append({"token": token, **body})
            return 202, {}
        return 404, {}


@pytest.fixture
def ms(monkeypatch):
    from app.invoicing import microsoft

    fake = FakeMicrosoft()
    monkeypatch.setattr(microsoft, "_http", fake)
    return fake


def connect(c: TestClient, ms: FakeMicrosoft, client_id: str = CLIENT) -> dict:
    start = c.post("/api/email-settings/microsoft/start", json={"client_id": client_id})
    assert start.status_code == 200, start.text
    assert start.json()["user_code"] == "ABCD-EFGH"
    first = c.post("/api/email-settings/microsoft/poll", json={"flow_id": start.json()["flow_id"]}).json()
    assert first["status"] == "pending"
    done = c.post("/api/email-settings/microsoft/poll", json={"flow_id": start.json()["flow_id"]})
    assert done.status_code == 200, done.text
    return done.json()


def test_connect_microsoft_365_and_send_invoice_with_graph(auth_client: TestClient, ms) -> None:
    c = auth_client
    assert c.get("/api/email-settings").json()["microsoft_ready"] is False
    assert c.post("/api/email-settings/microsoft/start", json={}).status_code == 409  # no client ID anywhere
    assert c.post("/api/email-settings/microsoft/start", json={"client_id": "not-a-guid"}).status_code == 422
    done = connect(c, ms)
    s = done["settings"]
    assert done["status"] == "connected" and s["configured"] and s["provider"] == "microsoft"
    assert s["oauth_account"] == "billing@fmitai.com" and s["ms_client_id"] == CLIENT and s["microsoft_ready"]
    from sqlalchemy import text

    from app.database import get_engine

    with get_engine().connect() as conn:
        stored = conn.execute(text("SELECT oauth_refresh_encrypted FROM email_settings")).scalar()
    assert stored and "RT-1" not in stored  # encrypted
    c.put("/api/email-settings/options", json={"reply_to": "frank@fmitai.com", "copy_me": True})

    cust = customer(c, cc_emails="ap@acme.example")
    inv = invoice(c, cust)
    draft = c.get(f"/api/invoices/{inv['id']}/email-draft").json()
    assert draft["configured"] and "Microsoft 365" in draft["from_label"]
    r = c.post(f"/api/invoices/{inv['id']}/send", json={"to": draft["to"], "cc": draft["cc"],
                                                         "subject": draft["subject"], "body": draft["body"]})
    assert r.status_code == 200, r.text
    sent = ms.sent[0]
    msg = sent["message"]
    assert sent["token"] == "AT-2" and sent["saveToSentItems"] is True
    assert [x["emailAddress"]["address"] for x in msg["toRecipients"]] == ["office@acme.example"]
    assert [x["emailAddress"]["address"] for x in msg["ccRecipients"]] == ["ap@acme.example"]
    assert [x["emailAddress"]["address"] for x in msg["bccRecipients"]] == ["billing@fmitai.com"]
    assert msg["replyTo"][0]["emailAddress"]["address"] == "frank@fmitai.com"
    att = msg["attachments"][0]
    import base64

    assert att["name"] == "Invoice-1001.pdf" and base64.b64decode(att["contentBytes"]).startswith(b"%PDF")
    # The rotated refresh token is kept (still encrypted).
    with get_engine().connect() as conn:
        now = conn.execute(text("SELECT oauth_refresh_encrypted FROM email_settings")).scalar()
    assert now != stored
    assert c.post("/api/email-settings/test", json={"to": "me@fmitai.com"}).json()["sent"] is True
    # Disconnect keeps the app ID for a one-click reconnect.
    out = c.post("/api/email-settings/microsoft/disconnect").json()
    assert out["configured"] is False and out["ms_client_id"] == CLIENT and out["microsoft_ready"]
    assert c.get(f"/api/invoices/{inv['id']}/email-draft").json()["configured"] is False
    assert c.post(f"/api/invoices/{inv['id']}/send", json={"to": ["x@acme.example"], "subject": "s", "body": "b"}
                  ).status_code == 409


def test_microsoft_errors_are_explained(auth_client: TestClient, ms) -> None:
    c = auth_client
    r = c.post("/api/email-settings/microsoft/start", json={"client_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 502 and "multitenant" in r.json()["detail"]
    assert c.post("/api/email-settings/microsoft/poll", json={"flow_id": "unknown-flow"}).status_code == 409
    connect(c, ms)
    ms.refresh_ok = False
    inv = invoice(c, customer(c))
    r = c.post(f"/api/invoices/{inv['id']}/send", json={"to": ["x@acme.example"], "subject": "s", "body": "b"})
    assert r.status_code == 502 and "Connect Microsoft 365 again" in r.json()["detail"]
    assert c.get(f"/api/invoices/{inv['id']}").json()["emails"][0]["status"] == "failed"


def test_switching_between_smtp_and_microsoft(auth_client: TestClient, ms, smtp) -> None:
    c = auth_client
    email_settings(c)
    assert c.get("/api/email-settings").json()["provider"] == "smtp"
    connect(c, ms)
    s = c.get("/api/email-settings").json()
    assert s["provider"] == "microsoft" and not s["has_password"] and s["smtp_host"] is None
    out = email_settings(c, password="pw2")
    assert out["provider"] == "smtp" and out["oauth_account"] is None and out["has_password"]
    inv = invoice(c, customer(c))
    assert c.post(f"/api/invoices/{inv['id']}/send", json={"to": ["x@acme.example"], "subject": "s", "body": "b"}
                  ).status_code == 200
    assert smtp.sent and not ms.sent


def test_env_client_id_is_used_when_none_is_saved(auth_client: TestClient, ms, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "MS_CLIENT_ID", CLIENT)
    c = auth_client
    s = c.get("/api/email-settings").json()
    assert s["microsoft_ready"] and s["ms_client_id_in_env"] and s["ms_client_id"] is None
    start = c.post("/api/email-settings/microsoft/start", json={}).json()
    c.post("/api/email-settings/microsoft/poll", json={"flow_id": start["flow_id"]})
    done = c.post("/api/email-settings/microsoft/poll", json={"flow_id": start["flow_id"]}).json()
    assert done["settings"]["ms_client_id"] is None  # nothing saved per company; .env keeps working
    assert ms.calls[0][2]["client_id"] == CLIENT
