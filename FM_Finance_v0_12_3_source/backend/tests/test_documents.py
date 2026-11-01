"""v0.4.0 bill import: readers, offline field parsing, AI fallback, duplicates, bank matching."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.documents import ai, fields, readers
from app.documents.selftest import _docx, _eml, _png, make_pdf

UTILITY = """FPL
Florida Power & Light Company
Statement Date: Sep 28, 2026
Account Number 1234567890
Previous Balance 130.00
Payment Received - Thank You -130.00
Amount Due $142.17
Due Date: Oct 19, 2026"""

RECEIPT = """The Home Depot
1500 N Hiatus Rd, Pembroke Pines FL 33026
10/02/26 11:42 AM
PVC PIPE 2IN          12.98
WIRE NUTS              4.97
SUBTOTAL              45.00
SALES TAX 7.000%       3.15
TOTAL               $48.15
VISA XXXX1234         48.15"""

INVOICE = """Northstar Consulting LLC
Invoice # NS-00981
Invoice Date 2026-10-01
Bill To: F&M IT Services
Subtotal $1,200.00
Tax $84.00
Total $1,284.00
Balance Due $1,284.00
Due Date 2026-10-31"""


def test_utility_bill_fields() -> None:
    out = fields.extract(UTILITY)
    assert out.amount.value == Decimal("142.17") and out.amount.score >= 0.9
    assert out.expense_date.value == date(2026, 9, 28)
    assert out.due_date.value == date(2026, 10, 19)
    assert out.vendor.value == "FPL"


def test_receipt_total_not_subtotal() -> None:
    out = fields.extract(RECEIPT)
    assert out.amount.value == Decimal("48.15")
    assert out.expense_date.value == date(2026, 10, 2)
    assert out.vendor.value == "The Home Depot"


def test_invoice_number_and_balance_due() -> None:
    out = fields.extract(INVOICE)
    assert out.amount.value == Decimal("1284.00")
    assert out.invoice_number.value == "NS-00981"
    assert out.expense_date.value == date(2026, 10, 1) and out.due_date.value == date(2026, 10, 31)
    assert out.vendor.value == "Northstar Consulting LLC"
    assert out.confident()


def test_email_sender_becomes_vendor() -> None:
    out = fields.extract("Thanks! Total charged: $20.00", email_from_name="OpenAI",
                         email_from_address="noreply@tm.openai.com", email_date=date(2026, 10, 3))
    assert out.vendor.value == "OpenAI" and out.amount.value == Decimal("20.00")
    assert out.expense_date.value == date(2026, 10, 3)
    generic = fields.extract("Total $5.00", email_from_name="Billing", email_from_address="billing@contoso.com")
    assert generic.vendor.value == "Contoso"


@pytest.mark.parametrize("name,maker,amount", [
    ("a.pdf", lambda: make_pdf(INVOICE.splitlines()), "1284.00"),
    ("a.docx", _docx, "85.00"),
    ("a.eml", _eml, "129.50"),
    ("a.png", _png, "12.34"),
])
def test_readers(name, maker, amount) -> None:
    doc = readers.read(name, maker())
    assert f"{fields.extract(doc.text).amount.value:.2f}" == amount


def test_reader_rejects_unknown_and_fake_pdf() -> None:
    with pytest.raises(readers.UnsupportedDocument):
        readers.read("a.exe", b"MZ....")
    with pytest.raises(readers.UnsupportedDocument):
        readers.read("a.pdf", b"not a pdf")


def _upload(c: TestClient, name: str, data: bytes):
    return c.post("/api/documents/extract", files={"file": (name, data, "application/octet-stream")})


def test_extract_endpoint_prefills(auth_client: TestClient) -> None:
    r = _upload(auth_client, "invoice.pdf", make_pdf(INVOICE.splitlines()))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["method"] == "text" and b["amount"] == 1284.0 and b["invoice_number"] == "NS-00981"
    assert b["expense_date"] == "2026-10-01" and b["due_date"] == "2026-10-31" and b["confident"]
    assert b["duplicates"] == [] and b["bank_match"] is None


def test_category_from_keywords_and_vendor_history(auth_client: TestClient) -> None:
    b = _upload(auth_client, "r.pdf", make_pdf(["Staples", "Date 10/02/2026", "Total $18.40"])).json()
    cats = {c["id"]: c["code"] for c in auth_client.get("/api/categories").json()}
    assert cats[b["category_id"]] == "office_supplies"


def test_duplicate_invoice_warning_and_bank_link(auth_client: TestClient) -> None:
    from .test_banking import do_import, make_account

    acct = make_account(auth_client)
    do_import(auth_client, acct["id"], b"Date,Description,Amount\n10/03/2026,NORTHSTAR CONSULTING,-1284.00\n")
    b = _upload(auth_client, "inv.pdf", make_pdf(INVOICE.splitlines())).json()
    assert b["bank_match"]["account_name"] == acct["name"]
    cats = auth_client.get("/api/categories").json()
    body = {"expense_date": b["expense_date"], "vendor_name": b["vendor_name"], "category_id": cats[0]["id"],
            "description": b["description"], "amount": b["amount"], "invoice_number": b["invoice_number"],
            "due_date": b["due_date"]}
    r = auth_client.post("/api/expenses", json=body)
    assert r.status_code == 201, r.text
    exp = r.json()
    assert exp["invoice_number"] == "NS-00981" and exp["bank_transaction_id"]
    txn = auth_client.get("/api/transactions", params={"tab": "all"}).json()["items"][0]
    assert txn["expense_id"] == exp["id"]
    again = _upload(auth_client, "inv.pdf", make_pdf(INVOICE.splitlines())).json()
    assert [d["id"] for d in again["duplicates"]] == [exp["id"]]


def test_word_email_receipts_can_be_attached(auth_client: TestClient) -> None:
    cats = auth_client.get("/api/categories").json()
    exp = auth_client.post("/api/expenses", json={"expense_date": "2026-10-02", "category_id": cats[0]["id"],
                                                   "description": "Lawn", "amount": 85}).json()
    for name, data in (("bill.docx", _docx()), ("bill.eml", _eml())):
        r = auth_client.post(f"/api/expenses/{exp['id']}/receipts", files={"file": (name, data, "application/octet-stream")})
        assert r.status_code == 201, r.text
    bad = auth_client.post(f"/api/expenses/{exp['id']}/receipts", files={"file": ("x.docx", b"MZ\x90\x00", "x")})
    assert bad.status_code in (415, 422)


def test_ai_fallback_merges_when_offline_unsure(auth_client: TestClient, monkeypatch) -> None:
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "AI_EXTRACTION", "fallback")
    monkeypatch.setattr(s, "ANTHROPIC_API_KEY", "test-key")
    seen = {}

    def fake(*, text, payload, categories):
        seen["payload"] = payload[0] if payload else None
        return {"vendor_name": "Corner Cafe", "invoice_date": "2026-10-03", "total_amount": 12.34,
                "category": "Meals", "description": "Coffee and pastry", "confidence": 0.93}

    monkeypatch.setattr(ai, "read_bill", fake)
    import io

    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (700, 200), "white")
    ImageDraw.Draw(img).text((40, 60), "Thank you  12.34", fill="black", font=ImageFont.load_default(size=40))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    b = _upload(auth_client, "photo.png", buf.getvalue()).json()
    assert b["method"] == "ai" and b["vendor_name"] == "Corner Cafe" and b["amount"] == 12.34
    assert seen["payload"] == "image/png"
    names = {c["id"]: c["name"] for c in auth_client.get("/api/categories").json()}
    assert names[b["category_id"]] == "Meals"
    # Confident offline reads don't spend an AI call in fallback mode.
    seen.clear()
    b = _upload(auth_client, "invoice.pdf", make_pdf(INVOICE.splitlines())).json()
    assert b["method"] == "text" and not seen


def test_ai_failure_falls_back_with_warning(auth_client: TestClient, monkeypatch) -> None:
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "AI_EXTRACTION", "always")
    monkeypatch.setattr(s, "ANTHROPIC_API_KEY", "test-key")

    def broken(**_):
        raise ai.AIUnavailable("AI reading is unreachable (check the internet connection).")

    monkeypatch.setattr(ai, "read_bill", broken)
    b = _upload(auth_client, "invoice.pdf", make_pdf(INVOICE.splitlines())).json()
    assert b["method"] == "text" and b["amount"] == 1284.0
    assert any("unreachable" in w for w in b["warnings"])


def test_capabilities(auth_client: TestClient) -> None:
    c = auth_client.get("/api/documents/capabilities").json()
    assert c["ocr"] is True and c["ai_mode"] == "off" and "msg" in c["formats"]


def test_ocr_glued_time_and_account_number_not_invoice() -> None:
    assert fields.find_dates("10/06/20268:14AM") == [date(2026, 10, 6)]
    out = fields.extract("Comcast Business\nAccount Number 8535 1012 3456\nAmount Due $89.99")
    assert out.invoice_number.value is None and out.description.value == "Comcast Business statement"


def _png_bytes(w: int = 400, h: int = 100) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 32, 54)).save(buf, "PNG")
    return buf.getvalue()


def test_company_logo_upload_public_and_remove(auth_client: TestClient, client: TestClient) -> None:
    assert auth_client.get("/api/company/branding").json()["has_logo"] is False
    r = auth_client.put("/api/company/logo", files={"file": ("logo.png", _png_bytes(3000, 600), "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["has_logo"] and r.json()["logo_version"] > 0
    remembered = client.cookies.get("fm_company")
    assert remembered  # set at sign-in
    client.cookies.clear()
    # A browser that never signed in sees the default mark, not some company's branding.
    assert client.get("/api/company/branding").json() == {"name": "F&M Finance", "has_logo": False,
                                                          "logo_version": 0, "company_id": None}
    client.cookies.set("fm_company", remembered)  # signed out, but this browser remembers its company
    pub = client.get("/api/company/branding").json()
    assert pub["has_logo"] is True and pub["company_id"] == remembered
    assert client.get(f"/api/company/{remembered}/logo").status_code == 200
    img = client.get("/api/company/logo")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(img.content)).size == (1200, 240)  # re-encoded, scaled down
    etag = img.headers["etag"]
    assert client.get("/api/company/logo", headers={"If-None-Match": etag}).status_code == 304
    from .conftest import ADMIN

    client.post("/api/auth/login", json=ADMIN)
    assert client.delete("/api/company/logo").json()["has_logo"] is False
    assert client.get("/api/company/logo").status_code == 404


def test_logo_rejects_non_images_and_needs_admin(auth_client: TestClient, client: TestClient) -> None:
    assert auth_client.put("/api/company/logo", files={"file": ("x.png", b"<svg onload=alert(1)>", "image/png")}).status_code == 415
    assert auth_client.put("/api/company/logo", files={"file": ("x.png", b"\x89PNG\r\n\x1a\nbroken", "image/png")}).status_code == 422
    client.cookies.clear()  # auth_client and client are the same object
    assert client.put("/api/company/logo", files={"file": ("x.png", _png_bytes(), "image/png")}).status_code == 401
