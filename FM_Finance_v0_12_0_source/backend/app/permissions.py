"""Custom roles (v0.10.0): a company can define its own roles on top of the five built-in ones.

A custom role starts from a base role (owner, accountant, bookkeeper, employee, viewer) and, for each area,
keeps the base role's access ("full"), makes it read-only ("view") or removes it ("none"). It can narrow what
the base role does, never widen it, so the security of the built-in roles still holds. Enforced on the server
for every request (see security._bind_company); the menu uses the same map.
"""

from __future__ import annotations

from typing import Literal

AREAS: dict[str, str] = {
    "banking": "Banking: accounts, bank transactions, imports and bank rules",
    "sales": "Sales: invoices, payments received, customers, products and services",
    "expenses": "Expenses and receipts",
    "bills": "Bills from vendors",
    "reports": "Dashboard figures and financial reports",
    "accounting": "Chart of accounts, journal entries and closing date",
    "settings": "Company settings and rules",
    "team": "Team and roles",
}
Level = Literal["full", "view", "none"]
ORDER = {"none": 0, "view": 1, "full": 2}

BASE: dict[str, dict[str, Level]] = {
    "owner": {a: "full" for a in AREAS},
    "accountant": {**{a: "full" for a in AREAS}, "settings": "view", "team": "none"},
    "bookkeeper": {**{a: "full" for a in AREAS}, "settings": "view", "team": "none"},
    "employee": {**{a: "none" for a in AREAS}, "expenses": "full", "settings": "view"},
    "viewer": {**{a: "view" for a in AREAS}, "team": "none"},
}

# First matching prefix wins (longer prefixes first).
PATH_AREAS: list[tuple[str, str]] = sorted([
    ("/api/accounts", "banking"), ("/api/transactions", "banking"), ("/api/imports", "banking"),
    ("/api/bank-rules", "banking"),
    ("/api/invoices", "sales"), ("/api/payments", "sales"), ("/api/items", "sales"), ("/api/customers", "sales"),
    ("/api/sales", "reports"),
    ("/api/expenses", "expenses"), ("/api/receipts", "expenses"), ("/api/documents", "expenses"),
    ("/api/vendors", "expenses"), ("/api/reports", "expenses"),
    ("/api/bills", "bills"),
    ("/api/ledger/reports", "reports"), ("/api/dashboard", "reports"),
    ("/api/ledger", "accounting"),
    ("/api/company", "settings"), ("/api/categories", "settings"), ("/api/email-settings", "settings"),
    ("/api/rules", "settings"),
    ("/api/members", "team"), ("/api/roles", "team"),
], key=lambda p: -len(p[0]))

# Lists every form needs (choosing a category, customer, account...). Reading them is allowed whatever the role
# says about their area; changing them still follows the area.
LOOKUPS = ("/api/categories", "/api/customers", "/api/vendors", "/api/items", "/api/accounts", "/api/rules",
           "/api/company", "/api/ledger/accounts")
READS = ("GET", "HEAD", "OPTIONS")


def area_for(path: str) -> str | None:
    return next((a for prefix, a in PATH_AREAS if path == prefix or path.startswith(prefix + "/")), None)


def effective(base_role: str, custom: dict | None) -> dict[str, Level]:
    base = BASE.get(base_role, BASE["viewer"])
    out: dict[str, Level] = {}
    for area, level in base.items():
        wanted = (custom or {}).get(area, "full")
        if wanted not in ORDER:
            wanted = "full"
        out[area] = wanted if ORDER[wanted] < ORDER[level] else level  # narrow only
    return out


def check(path: str, method: str, levels: dict[str, Level]) -> str | None:
    """None if allowed; otherwise the reason to refuse."""
    area = area_for(path)
    if area is None:
        return None
    level = levels.get(area, "full")
    if method in READS:
        if level == "none" and not any(path == p or path.startswith(p + "/") or path.startswith(p + "?")
                                       for p in LOOKUPS):
            return f"Your role doesn't include {AREAS[area].split(':')[0].lower()}"
        return None
    if level != "full":
        return f"Your role can view {AREAS[area].split(':')[0].lower()} but not change it"
    return None
