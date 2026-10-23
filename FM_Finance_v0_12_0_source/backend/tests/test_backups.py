"""v0.11.0 full backup files: database, settings, receipts and safe restore hand-off."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app import data_backups
from app.config import get_settings


@pytest.fixture
def portable_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    install = tmp_path / "install"
    receipts = install / "data" / "receipts"
    backups = tmp_path / "safe backups"
    receipts.mkdir(parents=True)
    install.joinpath(".env").write_text("APP_PORT=8123\nJWT_SECRET=backup-test\n", encoding="utf-8")
    receipts.joinpath("receipt.pdf").write_bytes(b"%PDF-1.4\nreceipt")
    settings = get_settings()
    monkeypatch.setattr(settings, "DESKTOP_MODE", True)
    monkeypatch.setattr(settings, "RECEIPT_STORAGE", "local")
    monkeypatch.setattr(settings, "RECEIPT_DIR", str(receipts))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(backups))
    monkeypatch.setattr(data_backups.paths, "is_frozen", lambda: True)
    monkeypatch.setattr(data_backups.paths, "app_dir", lambda: install)
    monkeypatch.setattr(data_backups.updates, "exe_path", lambda: install / "Renamed Finance.exe")
    monkeypatch.setattr(data_backups.updates, "_app_pids", lambda: [])
    launched: list[Path] = []
    monkeypatch.setattr(data_backups.updates, "_launch", lambda path: launched.append(path))
    return install, receipts, backups, launched


def test_full_backup_contains_database_settings_and_receipts(portable_backup) -> None:
    _, _, backups, _ = portable_backup
    info = data_backups.create("manual")
    path = backups / info["name"]
    assert path.is_file() and info["receipt_count"] == 1
    with zipfile.ZipFile(path) as archive:
        assert {"manifest.json", ".env", "data/fm_finance.db", "receipts/receipt.pdf"}.issubset(
            archive.namelist())
    assert data_backups.list_backups()[0]["name"] == info["name"]


def test_restore_is_staged_with_recovery_and_restored_port(portable_backup) -> None:
    install, _, backups, launched = portable_backup
    selected = data_backups.create("manual")
    result = data_backups.begin_restore(selected["name"], restore_settings=True, port=8010)
    assert result["backup"] == selected["name"]
    assert result["recovery_backup"].endswith("before-restore.fmbak")
    assert (backups / result["recovery_backup"]).is_file()
    assert launched == [install / "updates" / "restore_backup.cmd"]
    script = launched[0].read_text(encoding="ascii")
    assert 'set "PORT=8123"' in script
    assert 'set "EXENAME=Renamed Finance.exe"' in script
    assert 'taskkill /F /IM "%EXENAME%"' in script
    assert 'status=rolled_back' in script and 'rmdir /s /q "%STAGE%"' in script


def test_bad_backup_is_rejected(portable_backup) -> None:
    _, _, backups, _ = portable_backup
    bad = backups / "FMFinance_backup_bad_manual.fmbak"
    backups.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("../outside.txt", "bad")
        archive.writestr("manifest.json", "{}")
    with pytest.raises(data_backups.BackupError, match="safe"):
        data_backups._read_manifest(bad, verify_db=True)
