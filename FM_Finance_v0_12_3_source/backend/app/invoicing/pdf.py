"""Invoice PDF (fpdf2). Letter size, company logo, one clean professional layout.

Built from a plain InvoiceDoc so it can be rendered without a database (tests, --selftest).
Uses the PDF core font (Helvetica), so text is limited to Latin-1: accents such as "Peña" or
"Medellín" are fine; other characters are replaced by close equivalents or "?".
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from fpdf import FPDF
from fpdf.fonts import FontFace

ACCENT = (31, 78, 140)  # same deep blue as the app
INK = (27, 36, 48)
MUTED = (93, 104, 120)
LINE = (210, 216, 224)
SOFT = (232, 238, 247)
GREEN = (29, 107, 69)
RED = (161, 40, 31)

_REPLACE = {"—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
            "…": "...", "•": "-", " ": " ", "™": "(TM)", "€": "EUR ", "−": "-"}


def clean(text: str | None) -> str:
    if not text:
        return ""
    out = "".join(_REPLACE.get(ch, ch) for ch in str(text))
    return out.encode("latin-1", "replace").decode("latin-1")


def money(v: Decimal | float | int) -> str:
    v = Decimal(str(v)).quantize(Decimal("0.01"))
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def qty(v: Decimal) -> str:
    v = Decimal(str(v)).quantize(Decimal("0.01"))
    return f"{v:,.2f}".rstrip("0").rstrip(".") if v != v.to_integral() else f"{v:,.0f}"


def fdate(d: date | None) -> str:
    return f"{d:%m/%d/%Y}" if d else ""


def _rgb(hex_color: str | None) -> tuple[int, int, int]:
    try:
        h = (hex_color or "").lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        return ACCENT


@dataclass
class DocLine:
    description: str
    quantity: Decimal
    rate: Decimal
    amount: Decimal
    item: str | None = None
    service_date: date | None = None


@dataclass
class InvoiceDoc:
    company_name: str
    invoice_number: str
    invoice_date: date
    due_date: date
    customer_name: str
    lines: list[DocLine]
    total: Decimal
    paid: Decimal = Decimal("0")
    terms: str | None = None
    company_legal_name: str | None = None
    company_address: str | None = None
    company_phone: str | None = None
    company_email: str | None = None
    company_website: str | None = None
    logo_png: bytes | None = None
    customer_address: str | None = None
    customer_email: str | None = None
    message: str | None = None
    footer: str | None = None
    status: str = ""  # "paid" or "void" adds a stamp
    extra: dict = field(default_factory=dict)
    # v0.10.0 company rules: money/date formats, wording, accent color, custom fields to print
    fmt: object | None = None
    labels: dict = field(default_factory=dict)
    accent: str | None = None
    terms_label: str | None = None
    extra_facts: list = field(default_factory=list)  # (label, value) under the invoice facts
    customer_extra: list = field(default_factory=list)  # (label, value) under Bill to

    def __post_init__(self) -> None:
        if self.fmt is None:
            from ..rules import CompanyRules, Formatter

            self.fmt = Formatter(CompanyRules(), "USD", ascii_only=True)

    @property
    def balance(self) -> Decimal:
        return Decimal(self.total) - Decimal(self.paid)

    def L(self, key: str) -> str:  # noqa: N802 - short on purpose, used everywhere below
        from ..rules import DEFAULT_LABELS

        return self.labels.get(key) or DEFAULT_LABELS[key]

    def money(self, v) -> str:
        return clean(self.fmt.money(v))

    def date(self, d) -> str:
        return self.fmt.date(d)


class _PDF(FPDF):
    def __init__(self, doc: InvoiceDoc):
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.doc = doc
        self.set_margins(18, 16, 18)
        self.set_auto_page_break(auto=True, margin=22)
        self.set_title(clean(f"{doc.L('invoice_title').title()} {doc.invoice_number}"))
        self.set_author(clean(doc.company_legal_name or doc.company_name))
        self.set_creator("F&M Finance")

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, clean(f"{self.doc.L('invoice_no')} {self.doc.invoice_number}  ·  {self.doc.L('page')} "
                              f"{self.page_no()} / {{nb}}"), align="C")


def render_invoice(doc: InvoiceDoc) -> bytes:
    ACCENT = _rgb(doc.accent) if doc.accent else globals()["ACCENT"]  # noqa: N806
    money, fdate = doc.money, doc.date  # noqa: F841 - the company's formats
    pdf = _PDF(doc)
    pdf.alias_nb_pages()
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin
    left, top = pdf.l_margin, pdf.t_margin

    # ---- header: logo (or name) on the left, INVOICE on the right
    logo_bottom = top
    if doc.logo_png:
        try:
            info = pdf.image(io.BytesIO(doc.logo_png), x=left, y=top, h=18, keep_aspect_ratio=True)
            w = getattr(info, "rendered_width", 0) or 0
            if w > 70:  # very wide logos: cap the width instead
                pdf.set_fill_color(255, 255, 255)
                pdf.rect(left, top, w + 1, 19, style="F")
                pdf.image(io.BytesIO(doc.logo_png), x=left, y=top, w=70, keep_aspect_ratio=True)
            logo_bottom = top + 20
        except Exception:  # noqa: BLE001 - a broken logo must not stop the invoice
            doc.logo_png = None
    if not doc.logo_png:
        pdf.set_xy(left, top + 2)
        pdf.set_font("Helvetica", "B", 17)
        pdf.set_text_color(*INK)
        pdf.cell(width * 0.6, 9, clean(doc.company_name))
        logo_bottom = top + 13

    pdf.set_xy(left + width * 0.5, top)
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(*ACCENT)
    pdf.cell(width * 0.5, 11, clean(doc.L("invoice_title")), align="R")

    # ---- stamp
    if doc.status in ("paid", "void"):
        color = GREEN if doc.status == "paid" else RED
        with pdf.local_context():
            pdf.set_draw_color(*color)
            pdf.set_text_color(*color)
            pdf.set_line_width(0.8)
            pdf.set_font("Helvetica", "B", 22)
            label = clean(doc.L("paid_stamp" if doc.status == "paid" else "void_stamp"))
            w = pdf.get_string_width(label) + 12
            x, y = left + width * 0.36, top + 3
            with pdf.rotation(12, x + w / 2, y + 6):
                pdf.rect(x, y, w, 13)
                pdf.set_xy(x, y + 1.5)
                pdf.cell(w, 10, label, align="C")

    # ---- company block (left) and invoice facts (right)
    y = max(logo_bottom, top + 14) + 2
    pdf.set_xy(left, y)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 10)
    pdf.multi_cell(width * 0.55, 5, clean(doc.company_legal_name or doc.company_name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    contact = [doc.company_address, doc.company_phone, doc.company_email, doc.company_website]
    block = "\n".join(clean(c).strip() for c in contact if c and c.strip())
    if block:
        pdf.multi_cell(width * 0.55, 4.6, block, new_x="LMARGIN", new_y="NEXT")
    company_bottom = pdf.get_y()

    facts = [(doc.L("invoice_no"), doc.invoice_number), (doc.L("invoice_date"), fdate(doc.invoice_date)),
             (doc.L("due_date"), fdate(doc.due_date))]
    if doc.terms:
        facts.append((doc.L("terms"), doc.terms_label or doc.terms))
    facts += [(lbl, val) for lbl, val in doc.extra_facts]
    fx, fy = left + width * 0.58, y
    for label, value in facts:
        pdf.set_xy(fx, fy)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(width * 0.2, 5.4, clean(label))
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*INK)
        pdf.cell(width * 0.22, 5.4, clean(value), align="R")
        fy += 5.6
    facts_bottom = fy

    # ---- bill to, and the balance due box
    y = max(company_bottom, facts_bottom) + 7
    pdf.set_draw_color(*LINE)
    pdf.line(left, y - 3, left + width, y - 3)
    pdf.set_xy(left, y)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, clean(doc.L("bill_to")), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.multi_cell(width * 0.55, 5.2, clean(doc.customer_name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    cust = "\n".join([clean(c).strip() for c in (doc.customer_address, doc.customer_email) if c and c.strip()]
                     + [clean(f"{lbl}: {val}") for lbl, val in doc.customer_extra])
    if cust:
        pdf.multi_cell(width * 0.55, 4.6, cust, new_x="LMARGIN", new_y="NEXT")
    bill_bottom = pdf.get_y()

    bx, bw = left + width * 0.58, width * 0.42
    pdf.set_fill_color(*SOFT)
    pdf.rect(bx, y, bw, 19, style="F")
    pdf.set_xy(bx + 4, y + 3)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(bw - 8, 4.5, clean(doc.L("balance_due")) if doc.status != "void" else clean(doc.L("void_stamp").title()))
    pdf.set_xy(bx + 4, y + 8)
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(*ACCENT)
    pdf.cell(bw - 8, 8, money(doc.balance if doc.status != "void" else 0), align="R")

    # ---- lines
    pdf.set_y(max(bill_bottom, y + 19) + 8)
    show_dates = any(ln.service_date for ln in doc.lines)
    show_items = any(ln.item for ln in doc.lines)
    cols: list[tuple[str, float, str]] = []
    if show_dates:
        cols.append((doc.L("col_date"), 21, "LEFT"))
    if show_items:
        cols.append((doc.L("col_item"), 38, "LEFT"))
    fixed = sum(c[1] for c in cols) + 16 + 24 + 26
    cols += [(doc.L("col_description"), width - fixed, "LEFT"), (doc.L("col_qty"), 16, "RIGHT"),
             (doc.L("col_rate"), 24, "RIGHT"), (doc.L("col_amount"), 26, "RIGHT")]
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*INK)
    pdf.set_draw_color(*LINE)
    pdf.set_fill_color(255, 255, 255)
    head = FontFace(emphasis="BOLD", color=ACCENT, fill_color=SOFT, size_pt=8.5)
    with pdf.table(col_widths=[c[1] for c in cols], text_align=[c[2] for c in cols], headings_style=head,
                   borders_layout="HORIZONTAL_LINES", line_height=5.2, padding=(1.6, 1.4, 1.6, 1.4),
                   width=width, align="LEFT", first_row_as_headings=True, cell_fill_mode="NONE") as table:
        row = table.row()
        for name, _, _ in cols:
            row.cell(clean(name.upper()))
        for ln in doc.lines:
            row = table.row()
            if show_dates:
                row.cell(fdate(ln.service_date))
            if show_items:
                row.cell(clean(ln.item))
            row.cell(clean(ln.description))
            row.cell(qty(ln.quantity))
            row.cell(money(ln.rate))
            row.cell(money(ln.amount))

    # ---- totals
    pdf.ln(4)
    tx, tw = left + width * 0.58, width * 0.42

    def total_row(label: str, value: str, bold: bool = False, color=INK, size: float = 9.5) -> None:
        pdf.set_x(tx)
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.set_text_color(*(MUTED if not bold else INK))
        pdf.cell(tw * 0.55, 6.2, label)
        pdf.set_text_color(*color)
        pdf.cell(tw * 0.45, 6.2, value, align="R", new_x="LMARGIN", new_y="NEXT")

    if pdf.get_y() > pdf.h - 60:
        pdf.add_page()
    total_row(clean(doc.L("total")), money(doc.total), bold=True)
    if doc.paid:
        total_row(clean(doc.L("payments")), money(-Decimal(doc.paid)))
    pdf.set_draw_color(*INK)
    pdf.line(tx, pdf.get_y() + 0.5, tx + tw, pdf.get_y() + 0.5)
    pdf.ln(1.5)
    total_row(clean(doc.L("balance_due")), money(doc.balance if doc.status != "void" else 0), bold=True, color=ACCENT,
              size=11)

    # ---- message and footer text
    for title, body in ((doc.L("message"), doc.message), (doc.L("payment_instructions"), doc.footer)):
        if body and body.strip():
            pdf.ln(5)
            if pdf.get_y() > pdf.h - 40:
                pdf.add_page()
            pdf.set_x(left)
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(*MUTED)
            pdf.cell(0, 5, clean(title.upper()), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*INK)
            pdf.multi_cell(width, 4.8, clean(body.strip()), new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
