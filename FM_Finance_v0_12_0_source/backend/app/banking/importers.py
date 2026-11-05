"""Parse bank files (CSV and OFX/QFX) into plain rows. No database access here."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_AMOUNT = Decimal("9999999999.99")
DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%m-%d-%y", "%Y/%m/%d", "%d/%m/%Y", "%b %d, %Y",
                "%d-%b-%Y", "%Y%m%d")


class ImportFormatError(ValueError):
    """The file can't be read as a bank statement."""


@dataclass
class ParsedRow:
    line: int
    txn_date: date | None
    amount: Decimal | None
    description: str
    external_id: str | None = None
    error: str | None = None


@dataclass
class ParseResult:
    source: str  # csv | ofx
    rows: list[ParsedRow]
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def valid(self) -> list[ParsedRow]:
        return [r for r in self.rows if r.error is None]


def decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def detect_source(filename: str, text: str) -> str:
    name = filename.lower()
    if name.endswith((".ofx", ".qfx", ".qbo")) or "<OFX>" in text[:5000].upper():
        return "ofx"
    if name.endswith((".csv", ".txt")) or "," in text[:2000] or ";" in text[:2000] or "\t" in text[:2000]:
        return "csv"
    raise ImportFormatError("Unsupported file. Export a CSV, OFX or QFX file from your bank.")


def parse_amount(value: str) -> Decimal:
    text = (value or "").strip().replace("\u2212", "-")
    if not text:
        raise ValueError("empty")
    negative = False
    upper = text.upper()
    if upper.endswith(("CR", "DR")):
        negative = upper.endswith("DR")
        text = text[:-2].strip()
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    if text.endswith("-"):
        negative, text = True, text[:-1]
    text = re.sub(r"[$\s,]", "", text)
    if text.startswith("-"):
        negative, text = not negative, text[1:]
    if text.startswith("+"):
        text = text[1:]
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"not a number: {value!r}") from None
    if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")) or abs(amount) > MAX_AMOUNT:
        raise ValueError(f"invalid amount: {value!r}")
    return -amount if negative else amount


def parse_date(value: str, fmt: str) -> date:
    return datetime.strptime(value.strip(), fmt).date()


def guess_date_format(values: list[str]) -> str | None:
    samples = [v.strip() for v in values if v and v.strip()][:50]
    if not samples:
        return None
    for fmt in DATE_FORMATS:
        try:
            for v in samples:
                datetime.strptime(v, fmt)
            return fmt
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- CSV
def _read_rows(text: str) -> tuple[list[list[str]], str]:
    sample = text[:8192]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter)]
    return rows, delimiter


def _find_header(rows: list[list[str]]) -> int:
    """Banks sometimes put summary lines above the real header; find the header row."""
    for i, row in enumerate(rows[:25]):
        cells = [c.strip().lower() for c in row]
        has_date = any("date" in c for c in cells)
        has_money = any(re.search(r"amount|debit|credit|withdraw|deposit", c) for c in cells)
        if has_date and has_money:
            return i
    return 0


def _pick(headers: list[str], *patterns: str, avoid: tuple[str, ...] = ()) -> int | None:
    lowered = [h.strip().lower() for h in headers]
    for pattern in patterns:
        for i, h in enumerate(lowered):
            if re.search(pattern, h) and not any(a in h for a in avoid):
                return i
    return None


def guess_mapping(headers: list[str], rows: list[list[str]], account_kind: str) -> dict[str, Any]:
    date_col = _pick(headers, r"^post(ed|ing)? date", r"^transaction date", r"^trans\.? date", r"date")
    desc_col = _pick(headers, r"^description", r"^payee", r"^merchant", r"^name", r"details", r"memo", r"description")
    amount_col = _pick(headers, r"^amount", r"amount", avoid=("balance",))
    debit_col = _pick(headers, r"debit", r"withdraw", r"money out", r"charge")
    credit_col = _pick(headers, r"credit", r"deposit", r"money in", r"payment")
    mapping: dict[str, Any] = {
        "date_column": date_col,
        "description_column": desc_col,
        "amount_column": amount_col if amount_col is not None and (debit_col is None or credit_col is None) else None,
        "debit_column": None,
        "credit_column": None,
        "invert_amounts": False,
        "date_format": None,
    }
    if mapping["amount_column"] is None:
        mapping["debit_column"], mapping["credit_column"] = debit_col, credit_col
    if date_col is not None:
        mapping["date_format"] = guess_date_format([r[date_col] for r in rows if len(r) > date_col])
    # A credit card file whose purchases are positive needs inverting (purchases are money out).
    if account_kind == "credit_card" and mapping["amount_column"] is not None:
        col = mapping["amount_column"]
        signs = []
        for r in rows[:100]:
            try:
                signs.append(parse_amount(r[col]) > 0)
            except (ValueError, IndexError):
                continue
        if signs and sum(signs) / len(signs) > 0.6:
            mapping["invert_amounts"] = True
    return mapping


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def parse_csv(text: str, mapping: dict[str, Any] | None, account_kind: str) -> ParseResult:
    rows, delimiter = _read_rows(text)
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ImportFormatError("The file is empty.")
    header_index = _find_header(rows)
    headers = [h.strip() for h in rows[header_index]]
    body = rows[header_index + 1:]
    guessed = guess_mapping(headers, body, account_kind)
    # A saved per-account profile only applies to files with the same columns.
    saved_headers = (mapping or {}).get("headers")
    if saved_headers is not None and [h.strip().lower() for h in saved_headers] != [h.lower() for h in headers]:
        mapping = None
    m = {**guessed, **{k: v for k, v in (mapping or {}).items() if k in guessed}}
    for key in ("date_column", "description_column", "amount_column", "debit_column", "credit_column"):
        if m.get(key) is not None and not 0 <= m[key] < len(headers):
            m[key] = None
    if not m.get("date_format") and m.get("date_column") is not None:
        m["date_format"] = guess_date_format([r[m["date_column"]] for r in body if len(r) > m["date_column"]])

    out: list[ParsedRow] = []
    problems: list[str] = []
    if m["date_column"] is None:
        problems.append("Choose the date column.")
    if m["description_column"] is None:
        problems.append("Choose the description column.")
    if m["amount_column"] is None and (m["debit_column"] is None and m["credit_column"] is None):
        problems.append("Choose an amount column, or debit and credit columns.")
    if not m.get("date_format"):
        problems.append("The date format could not be detected.")

    if not problems:
        for offset, row in enumerate(body):
            line = header_index + offset + 2
            description = _cell(row, m["description_column"])
            try:
                txn_date = parse_date(_cell(row, m["date_column"]), m["date_format"])
            except ValueError:
                out.append(ParsedRow(line, None, None, description, error="Unreadable date"))
                continue
            try:
                if m["amount_column"] is not None:
                    amount = parse_amount(_cell(row, m["amount_column"]))
                else:
                    debit = _cell(row, m["debit_column"])
                    credit = _cell(row, m["credit_column"])
                    amount = Decimal("0")
                    if debit:
                        amount -= abs(parse_amount(debit))
                    if credit:
                        amount += abs(parse_amount(credit))
                if m.get("invert_amounts"):
                    amount = -amount
            except ValueError:
                out.append(ParsedRow(line, txn_date, None, description, error="Unreadable amount"))
                continue
            if amount == 0:
                out.append(ParsedRow(line, txn_date, amount, description, error="Zero amount"))
                continue
            if not description:
                out.append(ParsedRow(line, txn_date, amount, description, error="Missing description"))
                continue
            out.append(ParsedRow(line, txn_date, amount, description[:500]))

    return ParseResult(
        source="csv",
        rows=out,
        info={
            "headers": headers,
            "header_row": header_index + 1,
            "delimiter": delimiter,
            "mapping": m,
            "profile": {**m, "headers": headers},
            "problems": problems,
            "sample": [r[: len(headers)] for r in body[:8]],
        },
    )


# ---------------------------------------------------------------- OFX / QFX
_TRN = re.compile(r"<STMTTRN>(.*?)(?=</STMTTRN>|<STMTTRN>|</BANKTRANLIST>)", re.S | re.I)
_TAG = re.compile(r"<([A-Z0-9.]+)>([^<\r\n]*)", re.I)


def _tags(block: str) -> dict[str, str]:
    return {k.upper(): v.strip() for k, v in _TAG.findall(block)}


def parse_ofx(text: str) -> ParseResult:
    if "<OFX>" not in text.upper():
        raise ImportFormatError("This does not look like an OFX/QFX file.")
    head = _tags(text.split("<BANKTRANLIST>")[0] if "<BANKTRANLIST>" in text else text[:4000])
    out: list[ParsedRow] = []
    for n, block in enumerate(_TRN.findall(text), start=1):
        t = _tags(block)
        name, memo = t.get("NAME", ""), t.get("MEMO", "")
        description = name if not memo or memo.upper() in name.upper() else f"{name} {memo}".strip()
        description = re.sub(r"&amp;", "&", description)[:500]
        fitid = t.get("FITID") or None
        raw_date = (t.get("DTPOSTED") or t.get("DTUSER") or "")[:8]
        try:
            txn_date = datetime.strptime(raw_date, "%Y%m%d").date()
        except ValueError:
            out.append(ParsedRow(n, None, None, description, fitid, "Unreadable date"))
            continue
        try:
            amount = parse_amount(t.get("TRNAMT", ""))
        except ValueError:
            out.append(ParsedRow(n, txn_date, None, description, fitid, "Unreadable amount"))
            continue
        if amount == 0:
            out.append(ParsedRow(n, txn_date, amount, description, fitid, "Zero amount"))
            continue
        out.append(ParsedRow(n, txn_date, amount, description or "(no description)", fitid))
    if not out:
        raise ImportFormatError("No transactions were found in this OFX/QFX file.")
    acct = head.get("ACCTID", "")
    return ParseResult(
        source="ofx",
        rows=out,
        info={
            "account_last4": acct[-4:] if acct else None,
            "currency": head.get("CURDEF"),
            "statement_type": "credit_card" if "<CCSTMTRS>" in text.upper() else "bank",
        },
    )


def parse_file(filename: str, data: bytes, mapping: dict[str, Any] | None, account_kind: str) -> ParseResult:
    if len(data) > MAX_FILE_BYTES:
        raise ImportFormatError("The file is larger than 5 MB. Export a shorter date range.")
    if not data.strip():
        raise ImportFormatError("The file is empty.")
    text = decode(data)
    source = detect_source(filename, text)
    return parse_ofx(text) if source == "ofx" else parse_csv(text, mapping, account_kind)
