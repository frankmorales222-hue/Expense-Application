"""Turn raw bank descriptions into stable merchant keys.

"SQ *BLUE BOTTLE COFFEE Miami FL"         -> "BLUE BOTTLE COFFEE"
"AMAZON.COM*AB12CD3 AMZN.COM/BILL WA"      -> "AMAZON COM AMZN"
"POS DEBIT 10/02 MICROSOFT*365 800-642-76" -> "MICROSOFT"
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from decimal import Decimal

# Payment-processor prefixes that come before the real merchant name.
_PROCESSOR_PREFIX = re.compile(
    r"^(?:SQ|SQU|SQSP|TST|PP|PAYPAL|SP|GOOGLE|IN|PY|BT|EB|FS|DD|CKO|AMZ|WPY|PAR)\s*\*\s*", re.I
)
_PURCHASE_AUTH = re.compile(r"PURCHASE AUTHORI[SZ]ED ON \d{1,2}/\d{1,2}", re.I)
_DATE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_STOP = {
    "POS", "DEBIT", "CREDIT", "CARD", "PURCHASE", "CHECKCARD", "CHECK", "ACH", "RECURRING", "AUTHORIZED",
    "ON", "WEB", "ID", "PPD", "CCD", "WITHDRAWAL", "DES", "INDN", "CO", "VISA", "MC", "MASTERCARD", "DBT",
    "PMT", "TRN", "REF", "XX", "XXXX", "THE", "INC", "LLC", "CORP", "USA", "US", "WWW", "HTTP", "HTTPS",
    "PREAUTHORIZED", "TRANSACTION", "ELECTRONIC", "PAYMENT", "SALE", "STORE", "PENDING", "TO", "FROM",
}
# Trailing two-letter US state codes are noise for matching.
_STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
    "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR".split()
)
MAX_KEY_TOKENS = 3


def tokens(description: str) -> list[str]:
    text = (description or "").upper().strip()
    text = _PURCHASE_AUTH.sub(" ", text)
    text = _PROCESSOR_PREFIX.sub("", text)
    text = _DATE.sub(" ", text)
    out: list[str] = []
    for tok in _NON_ALNUM.split(text):
        if not tok or tok in _STOP or any(ch.isdigit() for ch in tok) or len(tok) == 1:
            continue
        out.append(tok)
    while len(out) > 1 and out[-1] in _STATES:
        out.pop()
    return out


def merchant_key(description: str) -> str:
    """Stable key used to learn vendor/category from earlier approvals."""
    return " ".join(tokens(description)[:MAX_KEY_TOKENS])


def display_name(description: str) -> str:
    """Readable vendor-name suggestion, e.g. 'Blue Bottle Coffee'."""
    toks = tokens(description)[:MAX_KEY_TOKENS]
    if not toks:
        return (description or "").strip()[:60]
    return " ".join(t.capitalize() for t in toks)


def searchable(description: str) -> str:
    """Upper-case words separated by single spaces and padded, for keyword matching."""
    return " " + " ".join(_NON_ALNUM.split((description or "").upper())).strip() + " "


def fingerprint_base(txn_date: date, amount: Decimal, description: str) -> str:
    desc = " ".join((description or "").upper().split())
    raw = f"{txn_date.isoformat()}|{amount:.2f}|{desc}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]
