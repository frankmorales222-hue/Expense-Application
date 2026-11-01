"""Turn uploaded files into plain text plus the parts an AI reader can use."""

from __future__ import annotations

import email
import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from email import policy
from email.utils import parsedate_to_datetime, parseaddr
from datetime import date
from typing import Any

from . import ocr

MAX_BYTES = 15 * 1024 * 1024
PDF_OCR_PAGES = 3
SUPPORTED = ("pdf", "docx", "eml", "msg", "jpg", "jpeg", "png", "webp", "heic", "txt", "html", "htm")


class UnsupportedDocument(ValueError):
    pass


@dataclass
class Document:
    kind: str
    text: str = ""
    used_ocr: bool = False
    email_from_name: str | None = None
    email_from_address: str | None = None
    email_subject: str | None = None
    email_date: date | None = None
    # The best original for an AI reader: (media_type, bytes). PDFs and images go as-is.
    ai_payload: tuple[str, bytes] | None = None
    attachments: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def read(filename: str, data: bytes) -> Document:
    if len(data) > MAX_BYTES:
        raise UnsupportedDocument("The file is larger than 15 MB.")
    if not data:
        raise UnsupportedDocument("The file is empty.")
    ext = extension(filename)
    if ext not in SUPPORTED:
        raise UnsupportedDocument("Use a PDF, Word (.docx), email (.eml or .msg) or photo (JPG, PNG, WEBP).")
    if ext == "pdf":
        return _pdf(data)
    if ext == "docx":
        return Document("docx", text=_docx_text(data))
    if ext == "eml":
        return _eml(data)
    if ext == "msg":
        return _msg(data)
    if ext in ("txt",):
        return Document("text", text=_decode(data))
    if ext in ("html", "htm"):
        return Document("text", text=_html_to_text(_decode(data)))
    return _image(ext, data)


# ---------------------------------------------------------------- formats
def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _html_to_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d|table)>", "\n", markup)
    markup = re.sub(r"(?i)</t[dh]>", "  ", markup)
    text = html.unescape(re.sub(r"<[^>]+>", " ", markup))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _pdf(data: bytes) -> Document:
    if not data.startswith(b"%PDF"):
        raise UnsupportedDocument("This file is not a valid PDF.")
    doc = Document("pdf", ai_payload=("application/pdf", data))
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                doc.notes.append("The PDF is password protected.")
                return doc
        pages = [(p.extract_text() or "") for p in reader.pages[:10]]
        doc.text = "\n".join(pages).strip()
        page_count = len(reader.pages)
    except Exception:  # noqa: BLE001 - damaged PDFs still go to OCR/AI
        doc.notes.append("The PDF text layer could not be read.")
        page_count = 1
    if len(re.sub(r"\s", "", doc.text)) < 40 * max(1, min(page_count, PDF_OCR_PAGES)) // 2:
        scanned = _pdf_ocr(data)
        if scanned:
            doc.text, doc.used_ocr = scanned, True
        elif not doc.text:
            doc.notes.append("This looks like a scanned PDF and offline OCR is unavailable.")
    return doc


def _pdf_ocr(data: bytes) -> str:
    if not ocr.available():
        return ""
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(data)
        texts = []
        for i in range(min(len(pdf), PDF_OCR_PAGES)):
            image = pdf[i].render(scale=2.0).to_pil()
            texts.append(ocr.image_to_text(image))
        pdf.close()
        return "\n".join(t for t in texts if t).strip()
    except Exception:  # noqa: BLE001
        return ""


def _image(ext: str, data: bytes) -> Document:
    media = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext)
    doc = Document("image", ai_payload=(media, data) if media else None)
    try:
        from PIL import Image, ImageOps

        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        doc.text = ocr.image_to_text(image)
        doc.used_ocr = bool(doc.text)
    except Exception:  # noqa: BLE001 - e.g. HEIC without a decoder
        doc.notes.append("This image format can't be read offline. Save the photo as JPG or PNG.")
    if not doc.text and not ocr.available():
        doc.notes.append("Offline OCR is unavailable, so photos need AI reading.")
    return doc


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            parts = [n for n in z.namelist() if re.match(r"word/(document|header\d*|footer\d*)\.xml$", n)]
            xml = "\n".join(z.read(n).decode("utf-8", errors="replace") for n in sorted(parts))
    except (zipfile.BadZipFile, KeyError):
        raise UnsupportedDocument("This Word file can't be opened. Save it as .docx and try again.") from None
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"</w:tc>", "  ", xml)
    xml = re.sub(r"<w:tab/>", "  ", xml)
    text = html.unescape(re.sub(r"<[^>]+>", "", xml))
    return "\n".join(" ".join(l.split()) for l in text.splitlines() if l.strip())


def _from_header(value: str | None) -> tuple[str | None, str | None]:
    name, addr = parseaddr(value or "")
    return (name.strip().strip('"') or None), (addr.strip().lower() or None)


def _attachments_text(doc: Document, attachments: list[tuple[str, bytes]]) -> None:
    for name, payload in attachments[:5]:
        ext = extension(name)
        if ext not in ("pdf", "docx", "jpg", "jpeg", "png", "webp"):
            continue
        try:
            inner = read(name, payload)
        except UnsupportedDocument:
            continue
        doc.attachments.append(name)
        if inner.text:
            doc.text += f"\n\n--- Attachment: {name} ---\n{inner.text}"
        doc.used_ocr = doc.used_ocr or inner.used_ocr
        # Prefer the attached bill (PDF) over the email body for the AI reader.
        if inner.ai_payload and (doc.ai_payload is None or doc.ai_payload[0] != "application/pdf"):
            doc.ai_payload = inner.ai_payload


def _eml(data: bytes) -> Document:
    msg = email.message_from_bytes(data, policy=policy.default)
    doc = Document("email")
    doc.email_from_name, doc.email_from_address = _from_header(msg.get("From"))
    doc.email_subject = (msg.get("Subject") or "").strip() or None
    try:
        doc.email_date = parsedate_to_datetime(msg.get("Date")).date() if msg.get("Date") else None
    except (TypeError, ValueError):
        doc.email_date = None
    body = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        content = body.get_content()
        text = _html_to_text(content) if body.get_content_type() == "text/html" else content
    doc.text = text.strip()
    attachments = []
    for part in msg.iter_attachments():
        name = part.get_filename() or ""
        payload = part.get_payload(decode=True)
        if name and payload:
            attachments.append((name, payload))
    _attachments_text(doc, attachments)
    return doc


def _msg(data: bytes) -> Document:
    if not data.startswith(b"\xd0\xcf\x11\xe0"):
        raise UnsupportedDocument("This is not an Outlook .msg file.")
    try:
        import extract_msg

        m: Any = extract_msg.openMsg(data)
    except Exception:  # noqa: BLE001
        raise UnsupportedDocument("This Outlook message can't be opened.") from None
    try:
        doc = Document("email")
        doc.email_from_name, doc.email_from_address = _from_header(m.sender)
        doc.email_subject = (m.subject or "").strip() or None
        try:
            doc.email_date = m.date.date() if m.date else None
        except Exception:  # noqa: BLE001
            doc.email_date = None
        body = m.body or ""
        if not body.strip() and getattr(m, "htmlBody", None):
            body = _html_to_text(_decode(m.htmlBody))
        doc.text = body.strip()
        attachments = []
        for a in m.attachments:
            name = getattr(a, "longFilename", None) or getattr(a, "shortFilename", None) or ""
            payload = getattr(a, "data", None)
            if name and isinstance(payload, bytes):
                attachments.append((name, payload))
        _attachments_text(doc, attachments)
        return doc
    finally:
        try:
            m.close()
        except Exception:  # noqa: BLE001
            pass
