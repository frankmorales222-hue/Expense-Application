from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.routers import meta

from .conftest import ADMIN, FakeStorage, make_expense

PDF = b"%PDF-1.4\n%test receipt\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


# ---------- auth ----------


def test_desktop_ui_close_stops_only_after_the_final_window(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Server:
        should_exit = False

    class Timer:
        instances: list["Timer"] = []

        def __init__(self, _delay: float, callback, args: tuple[object, ...]) -> None:
            self.callback = callback
            self.args = args
            self.cancelled = False
            self.started = False
            self.daemon = False
            self.instances.append(self)

        def start(self) -> None:
            self.started = True

        def cancel(self) -> None:
            self.cancelled = True

        def fire(self) -> None:
            if not self.cancelled:
                self.callback(*self.args)

    settings = get_settings()
    monkeypatch.setattr(settings, "DESKTOP_MODE", True)
    monkeypatch.setattr(meta, "Timer", Timer)
    server = Server()
    client.app.state.server = server
    headers = {"Origin": f"http://127.0.0.1:{settings.APP_PORT}"}

    assert client.post("/api/system/ui/open", params={"client_id": "window-one"}, headers=headers).status_code == 204
    assert client.post("/api/system/ui/open", params={"client_id": "window-two"}, headers=headers).status_code == 204
    assert client.post("/api/system/ui/close", params={"client_id": "window-one"}, headers=headers).status_code == 204
    assert Timer.instances == []

    assert client.post("/api/system/ui/close", params={"client_id": "window-two"}, headers=headers).status_code == 204
    first = Timer.instances[-1]
    assert first.started and not server.should_exit

    # A refresh or quick reopen cancels the pending stop.
    assert client.post("/api/system/ui/open", params={"client_id": "window-three"}, headers=headers).status_code == 204
    assert first.cancelled
    first.fire()
    assert not server.should_exit

    assert client.post("/api/system/ui/close", params={"client_id": "window-three"}, headers=headers).status_code == 204
    Timer.instances[-1].fire()
    assert server.should_exit


def test_desktop_ui_lifecycle_rejects_cross_site_requests(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "DESKTOP_MODE", True)
    client.app.state.server = type("Server", (), {"should_exit": False})()
    response = client.post(
        "/api/system/ui/open",
        params={"client_id": "window-one"},
        headers={"Origin": "https://example.com"},
    )
    assert response.status_code == 403


def test_login_success_sets_httponly_cookie(client: TestClient) -> None:
    r = client.post("/api/auth/login", json=ADMIN)
    assert r.status_code == 200
    assert r.json()["email"] == ADMIN["email"]
    assert "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").status_code == 200


def test_login_failure(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"email": ADMIN["email"], "password": "wrong"})
    assert r.status_code == 401


def test_login_throttled_after_repeated_failures(client: TestClient) -> None:
    for _ in range(5):
        client.post("/api/auth/login", json={"email": ADMIN["email"], "password": "wrong"})
    r = client.post("/api/auth/login", json=ADMIN)
    assert r.status_code == 429


@pytest.mark.parametrize("method,path", [
    ("get", "/api/expenses"), ("get", "/api/categories"), ("get", "/api/reports/summary"),
    ("get", "/api/auth/me"), ("get", "/api/settings"),
])
def test_unauthenticated_requests_return_401(client: TestClient, method: str, path: str) -> None:
    assert getattr(client, method)(path).status_code == 401


def test_logout_clears_session(auth_client: TestClient) -> None:
    assert auth_client.post("/api/auth/logout").status_code == 204
    assert auth_client.get("/api/auth/me").status_code == 401


def test_change_password(auth_client: TestClient) -> None:
    r = auth_client.post("/api/auth/change-password",
                         json={"current_password": "wrong", "new_password": "New-Password-456"})
    assert r.status_code == 400
    r = auth_client.post("/api/auth/change-password",
                         json={"current_password": ADMIN["password"], "new_password": "New-Password-456"})
    assert r.status_code == 204
    r = auth_client.post("/api/auth/change-password",
                         json={"current_password": "New-Password-456", "new_password": ADMIN["password"]})
    assert r.status_code == 204


# ---------- expenses ----------
def test_create_expense_amount_is_number(auth_client: TestClient, category_id: str) -> None:
    e = make_expense(auth_client, category_id, amount=19.99)
    assert isinstance(e["amount"], float) and e["amount"] == 19.99
    assert e["status"] == "approved"
    assert e["vendor_name"] == "Microsoft"
    assert e["history"][0]["action"] == "created"

    page = auth_client.get("/api/expenses").json()
    assert page["total"] == 1
    assert isinstance(page["items"][0]["amount"], float)
    assert isinstance(page["total_amount"], float)


def test_validation_rejects_bad_amount(auth_client: TestClient, category_id: str) -> None:
    for bad in (0, -5, 1.234):
        r = auth_client.post("/api/expenses", json={
            "expense_date": "2026-10-01", "category_id": category_id, "description": "x", "amount": bad})
        assert r.status_code == 422, bad


def test_vendor_reused_case_insensitively(auth_client: TestClient, category_id: str) -> None:
    make_expense(auth_client, category_id, vendor_name="Amazon")
    make_expense(auth_client, category_id, vendor_name="amazon")
    vendors = auth_client.get("/api/vendors", params={"q": "ama"}).json()
    assert [v["name"] for v in vendors] == ["Amazon"]


def test_status_with_approval_disabled(auth_client: TestClient, category_id: str) -> None:
    assert make_expense(auth_client, category_id, amount=5000)["status"] == "approved"


def test_status_with_approval_enabled(auth_client: TestClient, category_id: str,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "APPROVAL_REQUIRED", True)
    assert make_expense(auth_client, category_id, amount=499.99)["status"] == "approved"
    assert make_expense(auth_client, category_id, amount=500)["status"] == "pending"
    # Category threshold overrides the default.
    auth_client.put(f"/api/categories/{category_id}", json={"approval_threshold": 100})
    assert make_expense(auth_client, category_id, amount=150)["status"] == "pending"
    assert make_expense(auth_client, category_id, amount=99)["status"] == "approved"


def test_editing_amount_over_threshold_requires_reapproval(auth_client: TestClient, category_id: str,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "APPROVAL_REQUIRED", True)
    e = make_expense(auth_client, category_id, amount=50)
    body = {"expense_date": "2026-10-01", "category_id": category_id, "description": "Bigger", "amount": 900}
    r = auth_client.put(f"/api/expenses/{e['id']}", json=body)
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


def test_status_transitions(auth_client: TestClient, category_id: str) -> None:
    e = make_expense(auth_client, category_id)
    assert e["allowed_transitions"] == ["paid"]
    r = auth_client.post(f"/api/expenses/{e['id']}/status", json={"status": "paid"})
    assert r.status_code == 200 and r.json()["status"] == "paid" and r.json()["paid_at"]
    r = auth_client.post(f"/api/expenses/{e['id']}/status", json={"status": "approved"})
    assert r.status_code == 200 and r.json()["paid_at"] is None


def test_invalid_status_transition_returns_409(auth_client: TestClient, category_id: str) -> None:
    e = make_expense(auth_client, category_id)
    r = auth_client.post(f"/api/expenses/{e['id']}/status", json={"status": "pending"})
    assert r.status_code == 409


def test_update_records_audit_diff(auth_client: TestClient, category_id: str) -> None:
    e = make_expense(auth_client, category_id)
    body = {"expense_date": "2026-10-02", "vendor_name": "Microsoft", "category_id": category_id,
            "description": "Microsoft 365 Business Standard", "amount": 15.00}
    r = auth_client.put(f"/api/expenses/{e['id']}", json=body)
    assert r.status_code == 200
    latest = r.json()["history"][0]
    assert latest["action"] == "updated"
    assert latest["changes"]["amount"] == [12.5, 15.0]
    assert latest["changes"]["expense_date"] == ["2026-10-01", "2026-10-02"]
    assert "payment_method" in latest["changes"]


def test_soft_delete_hides_from_list_and_reports(auth_client: TestClient, category_id: str) -> None:
    keep = make_expense(auth_client, category_id, amount=10)
    gone = make_expense(auth_client, category_id, amount=90)
    assert auth_client.delete(f"/api/expenses/{gone['id']}").status_code == 204
    page = auth_client.get("/api/expenses").json()
    assert [i["id"] for i in page["items"]] == [keep["id"]]
    assert auth_client.get(f"/api/expenses/{gone['id']}").status_code == 404
    assert auth_client.get("/api/reports/summary").json()["total_spent"] == 10.0


def test_filters_search_sort_and_pagination(auth_client: TestClient, category_id: str) -> None:
    cats = auth_client.get("/api/categories").json()
    travel = next(c["id"] for c in cats if c["code"] == "travel")
    make_expense(auth_client, category_id, amount=30, expense_date="2026-09-01")
    make_expense(auth_client, travel, amount=200, vendor_name="Delta", description="Flight 100%_off",
                 expense_date="2026-09-15")
    make_expense(auth_client, category_id, amount=5, expense_date="2026-10-01")

    assert auth_client.get("/api/expenses", params={"category_id": travel}).json()["total"] == 1
    assert auth_client.get("/api/expenses", params={"search": "delta"}).json()["total"] == 1
    # Wildcards in search text are treated literally.
    assert auth_client.get("/api/expenses", params={"search": "100%_"}).json()["total"] == 1
    assert auth_client.get("/api/expenses", params={"search": "%"}).json()["total"] == 1
    r = auth_client.get("/api/expenses", params={"date_from": "2026-09-10", "date_to": "2026-09-30"}).json()
    assert r["total"] == 1 and r["total_amount"] == 200.0
    amounts = [i["amount"] for i in auth_client.get("/api/expenses", params={"sort": "amount_desc"}).json()["items"]]
    assert amounts == [200.0, 30.0, 5.0]
    p2 = auth_client.get("/api/expenses", params={"page_size": 2, "page": 2}).json()
    assert p2["total"] == 3 and len(p2["items"]) == 1 and p2["total_amount"] == 235.0


def test_inactive_category_cannot_be_used(auth_client: TestClient, category_id: str) -> None:
    auth_client.put(f"/api/categories/{category_id}", json={"is_active": False})
    r = auth_client.post("/api/expenses", json={
        "expense_date": "2026-10-01", "category_id": category_id, "description": "x", "amount": 1})
    assert r.status_code == 422


def test_csv_export_and_formula_injection(auth_client: TestClient, category_id: str) -> None:
    make_expense(auth_client, category_id, description="=HYPERLINK(\"http://evil\")", amount=42)
    r = auth_client.get("/api/expenses/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("Date,Vendor,Description")
    assert "'=HYPERLINK" in lines[1] and "42.00" in lines[1]


# ---------- categories ----------
def test_create_category_and_duplicate(auth_client: TestClient) -> None:
    r = auth_client.post("/api/categories", json={"name": "Domain Names"})
    assert r.status_code == 201 and r.json()["code"] == "domain_names"
    assert auth_client.post("/api/categories", json={"name": "domain names"}).status_code == 409


# ---------- receipts ----------
def test_receipt_upload_view_delete(auth_client: TestClient, category_id: str, storage: FakeStorage) -> None:
    e = make_expense(auth_client, category_id)
    r = auth_client.post(f"/api/expenses/{e['id']}/receipts",
                         files={"file": ("..\\..\\evil invoice.pdf", PDF, "application/pdf")})
    assert r.status_code == 201, r.text
    receipt = r.json()
    assert receipt["original_filename"] == "evil invoice.pdf"
    (key,) = storage.objects
    assert key.split("/")[2] == e["id"] and ".." not in key and not key.startswith("expenses/")

    detail = auth_client.get(f"/api/expenses/{e['id']}").json()
    assert detail["receipt_count"] == 1
    assert [h["action"] for h in detail["history"]][:1] == ["receipt_added"]

    content = auth_client.get(f"/api/receipts/{receipt['id']}/content")
    assert content.status_code == 200 and content.content == PDF
    assert content.headers["content-type"] == "application/pdf"

    assert auth_client.delete(f"/api/receipts/{receipt['id']}").status_code == 204
    assert storage.objects == {}


def test_receipt_rejects_wrong_type_and_spoofed_content(auth_client: TestClient, category_id: str) -> None:
    e = make_expense(auth_client, category_id)
    url = f"/api/expenses/{e['id']}/receipts"
    assert auth_client.post(url, files={"file": ("x.exe", b"MZ...", "application/octet-stream")}).status_code == 415
    assert auth_client.post(url, files={"file": ("x.pdf", b"MZ not a pdf", "application/pdf")}).status_code == 415
    assert auth_client.post(url, files={"file": ("x.png", PNG, "image/png")}).status_code == 201


def test_receipt_too_large(auth_client: TestClient, category_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "MAX_RECEIPT_MB", 1)
    e = make_expense(auth_client, category_id)
    big = PDF + b"0" * (1024 * 1024)
    r = auth_client.post(f"/api/expenses/{e['id']}/receipts", files={"file": ("big.pdf", big, "application/pdf")})
    assert r.status_code == 413


def test_storage_down_returns_503(auth_client: TestClient, category_id: str, storage: FakeStorage) -> None:
    e = make_expense(auth_client, category_id)
    storage.available = False
    r = auth_client.post(f"/api/expenses/{e['id']}/receipts", files={"file": ("a.pdf", PDF, "application/pdf")})
    assert r.status_code == 503
    assert auth_client.get("/api/expenses").status_code == 200  # rest of the app still works


# ---------- reports ----------
def test_summary_totals(auth_client: TestClient, category_id: str) -> None:
    cats = auth_client.get("/api/categories").json()
    travel = next(c["id"] for c in cats if c["code"] == "travel")
    make_expense(auth_client, category_id, amount=10.10, expense_date="2026-08-05")
    make_expense(auth_client, category_id, amount=20.20, expense_date="2026-09-05")
    make_expense(auth_client, travel, amount=300.30, expense_date="2026-09-20", is_reimbursable=True)
    paid = make_expense(auth_client, travel, amount=0.40, expense_date="2026-09-21", is_reimbursable=True)
    auth_client.post(f"/api/expenses/{paid['id']}/status", json={"status": "paid"})

    s = auth_client.get("/api/reports/summary", params={"date_to": "2026-09-30"}).json()
    assert s["total_spent"] == pytest.approx(331.00)
    assert Decimal(str(s["total_spent"])) == Decimal("331.00")
    assert s["expense_count"] == 4
    assert s["reimbursable_owed"] == pytest.approx(300.30)
    assert s["by_category"][0]["label"] == "Travel" and s["by_category"][0]["amount"] == pytest.approx(300.70)
    months = {m["key"]: m["amount"] for m in s["by_month"]}
    assert len(s["by_month"]) == 12 and s["by_month"][-1]["key"] == "2026-09"
    assert months["2026-08"] == pytest.approx(10.10) and months["2026-09"] == pytest.approx(320.90)
    statuses = {x["key"]: x["count"] for x in s["by_status"]}
    assert statuses == {"pending": 0, "approved": 3, "paid": 1, "rejected": 0}

    ranged = auth_client.get("/api/reports/summary", params={"date_from": "2026-09-01", "date_to": "2026-09-30"}).json()
    assert ranged["total_spent"] == pytest.approx(320.90)


# ---------- misc ----------
def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["database"] == "ok"


def test_unknown_api_path_is_404(auth_client: TestClient) -> None:
    assert auth_client.get("/api/does-not-exist").status_code == 404
