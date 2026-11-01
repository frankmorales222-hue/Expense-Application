"""Banking rules: duplicate detection, transfer matching, vendor/category suggestions, approval.

All functions take an open Session and leave committing to the caller.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    BankRule, Expense, ExpenseCategory, FinancialAccount, ImportBatch, Transaction, User, Vendor,
)
from .importers import ParsedRow
from .normalize import display_name, fingerprint_base, merchant_key, searchable

TRANSFER_WINDOW_DAYS = 4
DUPLICATE_WINDOW_DAYS = 3
EXPENSE_WINDOW_DAYS = 5
TRANSFER_HINTS = (" TRANSFER ", " XFER ", " TRF ", " PAYMENT ", " PMT ", " AUTOPAY ", " AUTO PAY ", " THANK YOU ",
                  " ONLINE BANKING ", " CARD SERVICES ", " CRCARDPMT ", " EPAY ", " MOBILE PMT ")

# Built-in keyword hints used only when nothing has been learned yet.
# Longer phrases are checked first so "UBER EATS" wins over "UBER".
KEYWORD_CATEGORIES: dict[str, tuple[str, ...]] = {
    "meals": ("UBER EATS", "DOORDASH", "GRUBHUB", "STARBUCKS", "DUNKIN", "MCDONALD", "CHIPOTLE", "RESTAURANT",
              "CAFE", "COFFEE", "PIZZA", "GRILL", "TST"),
    "software_licenses": ("MICROSOFT", "ADOBE", "GITHUB", "ATLASSIAN", "ZOOM", "SLACK", "DROPBOX", "OPENAI",
                          "ANTHROPIC", "CLAUDE AI", "CHATGPT", "INTUIT", "JETBRAINS", "GOOGLE WORKSPACE", "GSUITE",
                          "NOTION", "CANVA", "1PASSWORD", "LASTPASS", "DOCUSIGN", "AUTODESK"),
    "cloud_hosting": ("AMAZON WEB SERVICES", "AWS", "AZURE", "DIGITALOCEAN", "LINODE", "AKAMAI", "CLOUDFLARE",
                      "GODADDY", "NAMECHEAP", "HEROKU", "VERCEL", "HETZNER", "VULTR", "BACKBLAZE", "SQUARESPACE",
                      "WIX"),
    "internet_phone": ("COMCAST", "XFINITY", "VERIZON", "TMOBILE", "T MOBILE", "SPECTRUM", "HOTWIRE", "AT T",
                       "ATT", "RINGCENTRAL", "TWILIO", "GOOGLE FI", "MINT MOBILE"),
    "office_supplies": ("STAPLES", "OFFICE DEPOT", "OFFICEMAX", "USPS", "UPS STORE", "FEDEX OFFICE"),
    "hardware_equipment": ("BEST BUY", "BESTBUY", "NEWEGG", "B H PHOTO", "DELL", "LENOVO", "MICRO CENTER",
                           "APPLE STORE", "CDW"),
    "travel": ("UBER", "LYFT", "DELTA", "AMERICAN AIR", "JETBLUE", "SPIRIT", "SOUTHWEST", "UNITED AIR",
               "MARRIOTT", "HILTON", "HYATT", "AIRBNB", "EXPEDIA", "SUNPASS", "SHELL", "EXXON", "CHEVRON",
               "RACETRAC", "MARATHON", "SPEEDWAY", "PARKING", "TOLL", "HERTZ", "ENTERPRISE RENT", "AVIS"),
    "marketing_advertising": ("FACEBK", "META ADS", "GOOGLE ADS", "LINKEDIN", "VISTAPRINT", "MAILCHIMP", "YELP",
                              "INDEED"),
    "insurance": ("INSURANCE", "GEICO", "STATE FARM", "PROGRESSIVE", "HISCOX", "NEXT INSUR", "THE HARTFORD"),
    "taxes_licenses": ("IRS", "USATAXPYMT", "FL DEPT REVENUE", "SUNBIZ", "DIVISION OF CORP", "FLORIDA DEPT",
                       "TAX COLLECTOR", "BROWARD COUNTY"),
    "training_certifications": ("UDEMY", "COURSERA", "PLURALSIGHT", "COMPTIA", "ISC2", "ISACA", "PEARSON VUE",
                                "LINKEDIN LEARNING"),
    "bank_payment_fees": ("SERVICE CHARGE", "MONTHLY FEE", "OVERDRAFT", "WIRE FEE", "ATM FEE", "FOREIGN TRANSACTION",
                          "STRIPE FEE", "FEE"),
    "professional_services": ("LEGALZOOM", "CPA", "ACCOUNTING", "LAW OFFICE", "ATTORNEY", "NOTARY"),
}
INCOME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "interest_income": ("INTEREST",),
    "client_services_revenue": ("STRIPE", "SQUARE", "ZELLE FROM", "INVOICE", "DEPOSIT", "ACH CREDIT", "WIRE IN",
                                "PAYPAL TRANSFER"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fp(base: str, occurrence: int) -> str:
    return f"{base}:{occurrence}"


# ---------------------------------------------------------------- import
def import_rows(
    db: Session, *, account: FinancialAccount, batch: ImportBatch, rows: Iterable[ParsedRow]
) -> list[Transaction]:
    """Insert new rows, skipping exact duplicates. Returns the created transactions."""
    rows = list(rows)
    batch.rows_total = len(rows)
    valid = [r for r in rows if r.error is None]
    batch.rows_invalid = len(rows) - len(valid)

    existing_fitids = set(db.scalars(
        select(Transaction.external_id).where(Transaction.account_id == account.id, Transaction.external_id.is_not(None))
    ))
    existing_fps = set(db.scalars(select(Transaction.fingerprint).where(Transaction.account_id == account.id)))

    seen: Counter[str] = Counter()
    created: list[Transaction] = []
    for row in valid:
        assert row.txn_date is not None and row.amount is not None
        base = fingerprint_base(row.txn_date, row.amount, row.description)
        fingerprint = _fp(base, seen[base])
        seen[base] += 1
        if (row.external_id and row.external_id in existing_fitids) or fingerprint in existing_fps:
            batch.rows_duplicate += 1
            continue
        txn = Transaction(
            id=uuid.uuid4(), company_id=account.company_id, account_id=account.id, import_batch_id=batch.id,
            source=batch.source, txn_date=row.txn_date, amount=row.amount, description=row.description,
            normalized=merchant_key(row.description), external_id=row.external_id, fingerprint=fingerprint,
        )
        db.add(txn)
        created.append(txn)
        existing_fps.add(fingerprint)
        if row.external_id:
            existing_fitids.add(row.external_id)
    db.flush()
    batch.rows_imported = len(created)

    flag_possible_duplicates(db, created)
    match_transfers(db, created)
    suggest(db, [t for t in created if not t.is_transfer])
    auto_link_expenses(db, created)
    batch.rows_flagged = sum(1 for t in created if t.duplicate_of_id is not None)
    return created


def flag_possible_duplicates(db: Session, txns: list[Transaction]) -> None:
    """Same account, same amount, within a few days, different wording, from an earlier import."""
    for t in txns:
        candidate = db.scalar(
            select(Transaction).where(
                Transaction.account_id == t.account_id,
                Transaction.id != t.id,
                Transaction.amount == t.amount,
                Transaction.review_status != "excluded",
                Transaction.txn_date.between(t.txn_date - timedelta(days=DUPLICATE_WINDOW_DAYS),
                                             t.txn_date + timedelta(days=DUPLICATE_WINDOW_DAYS)),
                or_(Transaction.import_batch_id.is_(None), Transaction.import_batch_id != t.import_batch_id),
                Transaction.duplicate_of_id.is_(None),
            ).order_by(func.abs(func.julianday(Transaction.txn_date) - func.julianday(t.txn_date))
                       if db.get_bind().dialect.name == "sqlite"
                       else func.abs(Transaction.txn_date - t.txn_date)).limit(1)
        )
        if candidate is not None:
            t.duplicate_of_id = candidate.id


# ---------------------------------------------------------------- transfers
def _has_transfer_hint(*descriptions: str) -> bool:
    return any(h in searchable(d) for d in descriptions for h in TRANSFER_HINTS)


def transfer_candidates(db: Session, t: Transaction, window: int = TRANSFER_WINDOW_DAYS) -> list[Transaction]:
    return list(db.scalars(
        select(Transaction).where(
            Transaction.company_id == t.company_id,
            Transaction.account_id != t.account_id,
            Transaction.amount == -t.amount,
            Transaction.is_transfer.is_(False),
            Transaction.review_status == "unreviewed",
            Transaction.txn_date.between(t.txn_date - timedelta(days=window), t.txn_date + timedelta(days=window)),
        ).order_by(Transaction.txn_date)
    ))


def link_transfer(a: Transaction, b: Transaction, confidence: int, reason: str) -> None:
    for x, y in ((a, b), (b, a)):
        x.is_transfer, x.transfer_peer_id = True, y.id
        x.confidence, x.suggestion_reason = confidence, reason
        x.suggested_category_id, x.suggested_vendor_id, x.suggested_vendor_name = None, None, None
        x.category_id = None


def unlink_transfer(db: Session, t: Transaction) -> Transaction | None:
    peer = db.get(Transaction, t.transfer_peer_id) if t.transfer_peer_id else None
    for x in (t, peer):
        if x is not None:
            x.is_transfer, x.transfer_peer_id, x.confidence, x.suggestion_reason = False, None, 0, None
    return peer


def match_transfers(db: Session, txns: list[Transaction]) -> None:
    accounts = {a.id: a.name for a in db.scalars(select(FinancialAccount))}
    for t in txns:
        if t.is_transfer:
            continue
        candidates = [c for c in transfer_candidates(db, t) if not c.is_transfer]
        if not candidates:
            continue
        hinted = [c for c in candidates if _has_transfer_hint(t.description, c.description)]
        pool = hinted or candidates
        pool.sort(key=lambda c: abs((c.txn_date - t.txn_date).days))
        best = pool[0]
        # Several equally close, un-hinted matches are too ambiguous to auto-link.
        if not hinted and len(pool) > 1 and abs((pool[1].txn_date - t.txn_date).days) == abs((best.txn_date - t.txn_date).days):
            continue
        confidence = 92 if hinted else 70
        link_transfer(t, best, confidence, "")
        t.suggestion_reason = f"Matches {abs(best.amount):,.2f} in {accounts.get(best.account_id, 'another account')}"
        best.suggestion_reason = f"Matches {abs(t.amount):,.2f} in {accounts.get(t.account_id, 'another account')}"


# ---------------------------------------------------------------- suggestions
def _categories_by_code(db: Session) -> dict[str, ExpenseCategory]:
    return {c.code: c for c in db.scalars(select(ExpenseCategory).where(ExpenseCategory.is_active.is_(True)))}


def _match_vendor(vendors: list[Vendor], key: str) -> Vendor | None:
    if not key:
        return None
    best: tuple[int, Vendor] | None = None
    for v in vendors:
        candidates = [v.match_key] if v.match_key else []
        candidates.append(merchant_key(v.name))
        for c in candidates:
            if c and (key == c or key.startswith(c + " ") or (len(c) >= 5 and key.startswith(c))):
                score = len(c) + (100 if c == v.match_key else 0)
                if best is None or score > best[0]:
                    best = (score, v)
    return best[1] if best else None


def _keyword_category(description: str, inflow: bool, cats: dict[str, ExpenseCategory]) -> ExpenseCategory | None:
    text = searchable(description)
    table = INCOME_KEYWORDS if inflow else KEYWORD_CATEGORIES
    pairs = sorted(((kw, code) for code, kws in table.items() for kw in kws), key=lambda p: -len(p[0]))
    for kw, code in pairs:
        if f" {kw} " in text and code in cats:
            return cats[code]
    return None


def rule_matches(rule: BankRule, t: Transaction) -> bool:
    text = (t.description or "").upper()
    needle = (rule.match_text or "").strip().upper()
    if not needle:
        return False
    hit = {"contains": needle in text, "starts_with": text.startswith(needle), "equals": text.strip() == needle,
           "not_contains": needle not in text}.get(rule.match_type, needle in text)
    if not hit:
        return False
    amount = Decimal(t.amount)
    if rule.direction == "in" and amount <= 0 or rule.direction == "out" and amount >= 0:
        return False
    if rule.amount_min is not None and abs(amount) < Decimal(rule.amount_min):
        return False
    if rule.amount_max is not None and abs(amount) > Decimal(rule.amount_max):
        return False
    return rule.account_id is None or rule.account_id == t.account_id


def _apply_rules(db: Session, todo: list[Transaction]) -> list[Transaction]:
    """The company's own bank rules (v0.10.0) come first. Returns the transactions no rule handled."""
    rules = list(db.scalars(select(BankRule).where(BankRule.is_active.is_(True))
                            .order_by(BankRule.priority, BankRule.created_at)))
    if not rules:
        return todo
    rest = []
    auto = db.info.setdefault("rule_auto_approve", set())
    for t in todo:
        rule = next((r for r in rules if rule_matches(r, t)), None)
        if rule is None:
            rest.append(t)
            continue
        rule.times_used = (rule.times_used or 0) + 1
        t.suggested_category_id = rule.category_id
        if rule.vendor_name:
            v = db.scalar(select(Vendor).where(func.lower(Vendor.name) == rule.vendor_name.strip().lower()))
            t.suggested_vendor_id = v.id if v else None
            t.suggested_vendor_name = v.name if v else rule.vendor_name.strip()
        else:
            t.suggested_vendor_id, t.suggested_vendor_name = None, display_name(t.description)
        if rule.customer_id and t.customer_id is None:
            t.customer_id = rule.customer_id
        if rule.memo and not t.memo:
            t.memo = rule.memo
        t.confidence = 100
        t.suggestion_reason = f"Your rule: {rule.name}"
        if rule.auto_approve and (rule.category_id or t.amount > 0 and t.customer_id):
            auto.add(t.id)
    return rest


def approve_by_rules(db: Session, user: User) -> int:
    """Approve what a rule marked "approve automatically" (after an import or a new transaction)."""
    ids = db.info.pop("rule_auto_approve", set())
    done = 0
    for tid in ids:
        t = db.get(Transaction, tid)
        if t is None or t.review_status != "unreviewed" or t.duplicate_of_id is not None or t.is_transfer:
            continue
        try:
            approve(db, t, user, learn=False)
            done += 1
        except ApprovalError:
            continue
    return done


def suggest(db: Session, txns: list[Transaction]) -> None:
    """Fill suggested vendor/category + confidence for unreviewed, non-transfer transactions."""
    todo = [t for t in txns if t.review_status == "unreviewed" and not t.is_transfer]
    todo = _apply_rules(db, todo)
    if not todo:
        return
    cats = _categories_by_code(db)
    cat_by_id = {c.id: c for c in cats.values()}
    vendors = list(db.scalars(select(Vendor)))
    keys = {t.normalized for t in todo if t.normalized}

    # What did we decide last time for the same merchant key (and direction)?
    history: dict[tuple[str, bool], Counter[uuid.UUID]] = defaultdict(Counter)
    vendor_history: dict[str, Counter[uuid.UUID]] = defaultdict(Counter)
    if keys:
        for normalized, amount, category_id, vendor_id in db.execute(
            select(Transaction.normalized, Transaction.amount, Transaction.category_id, Transaction.vendor_id).where(
                Transaction.review_status == "approved", Transaction.is_transfer.is_(False),
                Transaction.normalized.in_(keys),
            )
        ):
            if category_id:
                history[(normalized, amount > 0)][category_id] += 1
            if vendor_id:
                vendor_history[normalized][vendor_id] += 1
    vendor_by_id = {v.id: v for v in vendors}

    for t in todo:
        inflow = t.amount > 0
        vendor = None
        if t.normalized in vendor_history:
            vendor = vendor_by_id.get(vendor_history[t.normalized].most_common(1)[0][0])
        vendor = vendor or _match_vendor(vendors, t.normalized)
        t.suggested_vendor_id = vendor.id if vendor else None
        t.suggested_vendor_name = vendor.name if vendor else display_name(t.description)

        category, confidence, reason = None, 0, "No match yet. Choose a category."
        past = history.get((t.normalized, inflow))
        if past:
            cat_id, n = past.most_common(1)[0]
            share = n / sum(past.values())
            if cat_id in cat_by_id:
                category = cat_by_id[cat_id]
                confidence = round((70 + min(n, 5) * 5) * share)
                reason = f"You chose this {n} time{'s' if n != 1 else ''} for {t.normalized.title()}"
        if category is None and vendor and vendor.default_category_id in cat_by_id:
            category, confidence = cat_by_id[vendor.default_category_id], 80
            reason = f"Default category for {vendor.name}"
        if category is None:
            kw = _keyword_category(t.description, inflow, cats)
            if kw is not None:
                category, confidence, reason = kw, 50, "Matched a common merchant keyword"
        t.suggested_category_id = category.id if category else None
        t.confidence = max(0, min(100, confidence))
        t.suggestion_reason = reason


def resuggest_similar(db: Session, t: Transaction) -> None:
    if not t.normalized:
        return
    siblings = list(db.scalars(select(Transaction).where(
        Transaction.normalized == t.normalized, Transaction.review_status == "unreviewed",
        Transaction.is_transfer.is_(False), Transaction.id != t.id,
    )))
    suggest(db, siblings)


# ---------------------------------------------------------------- approval
class ApprovalError(ValueError):
    pass


def approve(db: Session, t: Transaction, user: User, *, learn: bool = True) -> list[Transaction]:
    """Approve a transaction (and its transfer peer). Returns everything that changed."""
    if t.review_status == "approved":
        return []
    now = _now()
    if t.is_transfer:
        peer = db.get(Transaction, t.transfer_peer_id) if t.transfer_peer_id else None
        changed = [x for x in (t, peer) if x is not None and x.review_status != "approved"]
        for x in changed:
            x.review_status, x.approved_by, x.approved_at = "approved", user.id, now
            x.duplicate_of_id = None
        return changed
    if t.allocation_account_id is None and t.category_id is None:
        t.category_id = t.suggested_category_id
    if t.allocation_account_id is None and t.category_id is None and not covered_by_record(db, t):
        raise ApprovalError("Choose a category before approving.")
    if t.vendor_id is None and t.suggested_vendor_id is not None:
        t.vendor_id = t.suggested_vendor_id
    if t.vendor_id is None and t.suggested_vendor_name and t.amount < 0:
        t.vendor_id = get_or_create_vendor_by_name(db, t.suggested_vendor_name).id
    t.review_status, t.approved_by, t.approved_at = "approved", user.id, now
    t.duplicate_of_id = None
    if learn and t.allocation_account_id is None:
        learn_from(db, t)
    return [t]


def learn_from(db: Session, t: Transaction) -> None:
    if t.vendor_id and t.normalized:
        vendor = db.get(Vendor, t.vendor_id)
        if vendor is not None:
            if not vendor.match_key:
                vendor.match_key = t.normalized
            cat = db.get(ExpenseCategory, t.category_id) if t.category_id else None
            if vendor.default_category_id is None and cat is not None and cat.kind == "expense" and t.amount < 0:
                vendor.default_category_id = cat.id
    db.flush()
    resuggest_similar(db, t)


def get_or_create_vendor_by_name(db: Session, name: str) -> Vendor:
    name = " ".join(name.split())[:255]
    vendor = db.scalar(select(Vendor).where(func.lower(Vendor.name) == name.lower()))
    if vendor is None:
        vendor = Vendor(name=name)
        db.add(vendor)
        db.flush()
    return vendor


# ---------------------------------------------------------------- expenses / receipts
def expense_candidates(db: Session, t: Transaction) -> list[Expense]:
    if t.amount >= 0:
        return []
    linked = select(Transaction.expense_id).where(Transaction.expense_id.is_not(None), Transaction.id != t.id)
    return list(db.scalars(
        select(Expense).where(
            Expense.is_deleted.is_(False), Expense.status != "rejected", Expense.amount == -t.amount,
            Expense.expense_date.between(t.txn_date - timedelta(days=EXPENSE_WINDOW_DAYS),
                                         t.txn_date + timedelta(days=EXPENSE_WINDOW_DAYS)),
            Expense.id.not_in(linked),
        ).order_by(Expense.expense_date)
    ))


def covered_by_record(db: Session, t: Transaction) -> bool:
    """The transaction is the payment of an expense or bill, or a customer payment, that already records it
    in the books."""
    from ..models import BillPayment

    if t.expense_id:
        e = db.get(Expense, t.expense_id)
        if e is not None and not e.is_deleted and e.status in ("approved", "paid"):
            return True
    from ..models import CustomerPayment

    if db.scalar(select(BillPayment.id).where(BillPayment.transaction_id == t.id)) is not None:
        return True
    return db.scalar(select(CustomerPayment.id).where(CustomerPayment.transaction_id == t.id)) is not None


def link_expense(t: Transaction, expense: Expense) -> None:
    t.expense_id = expense.id
    if expense.payment_account_id is None and not expense.is_reimbursable:
        expense.payment_account_id = t.account_id


def auto_link_expenses(db: Session, txns: list[Transaction]) -> None:
    for t in txns:
        if t.expense_id is None and t.amount < 0 and not t.is_transfer:
            found = [e for e in expense_candidates(db, t)
                     if not e.is_reimbursable and e.payment_account_id in (None, t.account_id)]
            if len(found) == 1:
                link_expense(t, found[0])


def account_balances(db: Session) -> dict[uuid.UUID, Decimal]:
    rows = db.execute(
        select(Transaction.account_id, func.coalesce(func.sum(Transaction.amount), 0))
        .where(Transaction.review_status != "excluded")
        .group_by(Transaction.account_id)
    ).all()
    return {a: Decimal(s) for a, s in rows}

