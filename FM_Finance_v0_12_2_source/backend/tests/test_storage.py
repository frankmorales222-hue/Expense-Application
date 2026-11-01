import uuid

import pytest

from app.storage import LocalReceiptStorage, StorageUnavailable


def test_local_storage_roundtrip_and_key_validation(tmp_path):
    s = LocalReceiptStorage(tmp_path / "receipts")
    s.ensure_bucket()
    assert s.ping()
    key = f"2026/10/{uuid.uuid4()}/{uuid.uuid4()}.pdf"
    s.put(key, b"%PDF-1.4 hello", "application/pdf")
    assert b"".join(s.open(key)) == b"%PDF-1.4 hello"
    s.delete(key)
    assert not (tmp_path / "receipts" / key).exists()
    for bad in ("../../etc/passwd", "2026/10/x/../../y.pdf", "C:/Windows/win.ini"):
        with pytest.raises(StorageUnavailable):
            s.put(bad, b"x", "application/pdf")
