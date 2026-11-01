"""Optional AI reading through the Anthropic Messages API (standard library HTTP only)."""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

from ..config import get_settings

log = logging.getLogger(__name__)
API_URL = "https://api.anthropic.com/v1/messages"
MAX_TEXT = 30000
AI_MEDIA = ("application/pdf", "image/jpeg", "image/png", "image/webp")

PROMPT = """You read a bill, invoice or receipt for a small business's expense tracker.
Return ONLY a JSON object, no other text, with these keys:
  "vendor_name": the business that issued the bill (not the customer), or null
  "invoice_date": date issued or paid, "YYYY-MM-DD", or null
  "due_date": "YYYY-MM-DD" or null
  "total_amount": the final total to pay or paid, as a number without currency symbols, or null
  "currency": 3-letter code, default "USD"
  "invoice_number": invoice/receipt/order number, or null
  "description": short plain description of what was bought, max 120 characters
  "category": the best match from this list, exactly as written, or null: {categories}
  "confidence": your confidence in total_amount, vendor_name and invoice_date together, 0 to 1
Use the amount actually due or paid, not a subtotal, tax line or previous balance."""


class AIUnavailable(RuntimeError):
    pass


def enabled_mode() -> str:
    s = get_settings()
    mode = s.AI_EXTRACTION.strip().lower()
    return mode if mode in ("fallback", "always") and s.ANTHROPIC_API_KEY else "off"


def read_bill(*, text: str, payload: tuple[str, bytes] | None, categories: list[str]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        raise AIUnavailable("No ANTHROPIC_API_KEY is set.")
    content: list[dict[str, Any]] = []
    if payload and payload[0] in AI_MEDIA and len(payload[1]) <= 20 * 1024 * 1024:
        media, data = payload
        block_type = "document" if media == "application/pdf" else "image"
        content.append({"type": block_type,
                        "source": {"type": "base64", "media_type": media, "data": base64.b64encode(data).decode()}})
    if text.strip():
        content.append({"type": "text", "text": "Text found in the file:\n" + text[:MAX_TEXT]})
    if not content:
        raise AIUnavailable("Nothing readable to send.")
    content.append({"type": "text", "text": PROMPT.format(categories=", ".join(categories))})
    body = json.dumps({"model": settings.ANTHROPIC_MODEL, "max_tokens": 600,
                       "messages": [{"role": "user", "content": content}]}).encode()
    request = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "content-type": "application/json", "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed https URL
            reply = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        log.warning("AI reading failed: HTTP %s %s", exc.code, detail)
        if exc.code in (401, 403):
            raise AIUnavailable("The Anthropic API key was rejected.") from None
        raise AIUnavailable(f"AI reading failed (HTTP {exc.code}).") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("AI reading unavailable: %s", exc)
        raise AIUnavailable("AI reading is unreachable (check the internet connection).") from None
    text_out = "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")
    match = re.search(r"\{.*\}", text_out, re.S)
    if not match:
        raise AIUnavailable("AI reading returned no data.")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        raise AIUnavailable("AI reading returned unreadable data.") from None
