"""Offline OCR for scans and photos (RapidOCR on ONNX Runtime; models ship inside the package)."""

from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger(__name__)
_engine: Any = None
_failed = False
_lock = threading.Lock()
MAX_SIDE = 2200


def _get_engine() -> Any:
    global _engine, _failed
    if _engine is not None or _failed:
        return _engine
    with _lock:
        if _engine is None and not _failed:
            try:
                from rapidocr_onnxruntime import RapidOCR

                _engine = RapidOCR()
            except Exception:  # noqa: BLE001 - OCR is optional
                log.exception("Offline OCR could not be loaded; scans and photos need AI reading")
                _failed = True
    return _engine


def available() -> bool:
    from ..config import get_settings

    return get_settings().OCR_ENABLED and _get_engine() is not None


def image_to_text(image: Any) -> str:
    """OCR a PIL image. Returns text with one line per visual row, or '' when OCR is unavailable."""
    if not available():
        return ""
    import numpy as np

    img = image.convert("RGB")
    scale = MAX_SIDE / max(img.size)
    if scale < 1:
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    with _lock:  # the ONNX session is not guaranteed thread-safe
        result, _ = _engine(np.array(img))
    if not result:
        return ""
    # Each item: [box(4 points), text, score]. Group boxes into rows by vertical centre.
    items = []
    for box, text, score in result:
        if float(score) < 0.5 or not str(text).strip():
            continue
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append(((min(ys) + max(ys)) / 2, min(xs), max(ys) - min(ys), str(text).strip()))
    items.sort()
    rows: list[list[tuple[float, str]]] = []
    last_y, tol = None, 0.0
    for y, x, h, text in items:
        if last_y is None or abs(y - last_y) > max(tol, 8):
            rows.append([])
            last_y, tol = y, h * 0.6
        rows[-1].append((x, text))
    return "\n".join("  ".join(t for _, t in sorted(row)) for row in rows)
