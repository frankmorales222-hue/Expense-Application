"""`FMFinance.exe --selftest`: proves the bundled readers work in the packaged build (used by CI)."""

from __future__ import annotations

import io
import traceback
import zipfile
from email.message import EmailMessage

# A one-page PDF with a real text layer, written by hand so no PDF writer is needed at runtime.
SAMPLE_LINES = ("ACME WEB HOSTING", "Invoice Number: INV-2041", "Invoice Date: 10/01/2026", "Amount Due: $129.50")


def make_pdf(lines: tuple[str, ...] | list[str] = SAMPLE_LINES) -> bytes:
    """Build a one-page PDF with a real text layer (Helvetica, one line per entry)."""
    ops = [b"BT /F1 14 Tf 72 720 Td"]
    for i, line in enumerate(lines):
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace")
        ops.append((b"" if i == 0 else b"0 -24 Td ") + b"(" + safe + b") Tj")
    ops.append(b"ET")
    _PDF_TEXT = b" ".join(ops)
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(_PDF_TEXT) + _PDF_TEXT + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def _pdf() -> bytes:
    return make_pdf()


def _docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                   '<w:p><w:r><w:t>Bright Lawn Care</w:t></w:r></w:p>'
                   '<w:p><w:r><w:t>Invoice Date: 10/02/2026</w:t></w:r></w:p>'
                   '<w:p><w:r><w:t>Total Due: $85.00</w:t></w:r></w:p></w:body></w:document>')
    return buf.getvalue()


def _eml() -> bytes:
    msg = EmailMessage()
    msg["From"] = "Contoso Billing <billing@contoso.com>"
    msg["To"] = "owner@example.com"
    msg["Subject"] = "Your Contoso invoice"
    msg["Date"] = "Fri, 02 Oct 2026 10:00:00 -0400"
    msg.set_content("Thanks for your business. Your invoice is attached.")
    msg.add_attachment(_pdf(), maintype="application", subtype="pdf", filename="invoice.pdf")
    return msg.as_bytes()


def _png() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (900, 360), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=40)
    for i, line in enumerate(("CORNER CAFE", "Date: 10/03/2026", "TOTAL $12.34")):
        draw.text((40, 40 + i * 100), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def run() -> tuple[bool, str]:
    from . import fields, ocr, readers

    lines, ok = [], True
    checks = [("pdf", "bill.pdf", _pdf, "129.50"), ("docx", "bill.docx", _docx, "85.00"),
              ("eml", "bill.eml", _eml, "129.50"), ("ocr", "photo.png", _png, "12.34")]
    for label, name, make, expected in checks:
        try:
            doc = readers.read(name, make())
            got = fields.extract(doc.text, email_from_name=doc.email_from_name,
                                 email_from_address=doc.email_from_address).amount.value
            passed = got is not None and f"{got:.2f}" == expected
            lines.append(f"{label}: {'ok' if passed else 'FAILED'} (amount {got}, expected {expected})")
            ok = ok and passed
        except Exception:  # noqa: BLE001
            ok = False
            lines.append(f"{label}: ERROR\n{traceback.format_exc()}")
    lines.append(f"ocr_available: {ocr.available()}")
    # v0.7.0: the invoice PDF (fpdf2) and the encrypted mail password (cryptography) are bundled.
    try:
        import io as _io
        from datetime import date as _date
        from decimal import Decimal as _D

        from pypdf import PdfReader

        from ..invoicing.pdf import DocLine, InvoiceDoc, render_invoice

        pdf = render_invoice(InvoiceDoc(company_name="Self-test LLC", invoice_number="T-1", invoice_date=_date.today(),
                                        due_date=_date.today(), customer_name="Clínica Peña",
                                        lines=[DocLine("Check — service", _D("2"), _D("10.25"), _D("20.50"))],
                                        total=_D("20.50")))
        text = PdfReader(_io.BytesIO(pdf)).pages[0].extract_text()
        passed = "Clínica Peña" in text and "$20.50" in text
        lines.append(f"invoice_pdf: {'ok' if passed else 'FAILED'} ({len(pdf)} bytes)")
        ok = ok and passed
    except Exception:  # noqa: BLE001
        ok = False
        lines.append(f"invoice_pdf: ERROR\n{traceback.format_exc()}")
    try:
        from cryptography.fernet import Fernet

        f = Fernet(Fernet.generate_key())
        passed = f.decrypt(f.encrypt(b"smtp")) == b"smtp"
        lines.append(f"mail_password_encryption: {'ok' if passed else 'FAILED'}")
        ok = ok and passed
    except Exception:  # noqa: BLE001
        ok = False
        lines.append(f"mail_password_encryption: ERROR\n{traceback.format_exc()}")
    return ok, "\n".join(lines)
