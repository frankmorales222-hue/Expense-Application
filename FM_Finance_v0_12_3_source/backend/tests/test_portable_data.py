"""v0.12.2 keeps company data in one permanent home shared by future EXEs."""

from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

from app import portable_data


def _database(path: Path, expenses: int = 0, transactions: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.executescript(
            "CREATE TABLE users(id TEXT); CREATE TABLE companies(id TEXT); "
            "CREATE TABLE alembic_version(version_num TEXT); CREATE TABLE expenses(id TEXT); "
            "CREATE TABLE transactions(id TEXT);"
        )
        db.execute("INSERT INTO users VALUES ('u')")
        db.execute("INSERT INTO companies VALUES ('c')")
        db.execute("INSERT INTO alembic_version VALUES ('0026_sqlite_confidence')")
        db.executemany("INSERT INTO expenses VALUES (?)", [(f"e{i}",) for i in range(expenses)])
        db.executemany("INSERT INTO transactions VALUES (?)", [(f"t{i}",) for i in range(transactions)])
        db.commit()
    finally:
        db.close()


def _paths(monkeypatch, install: Path, home: Path, backups: Path) -> None:
    monkeypatch.setattr(portable_data.paths, "is_frozen", lambda: True)
    monkeypatch.setattr(portable_data.paths, "app_dir", lambda: install)
    monkeypatch.setattr(portable_data.paths, "data_home", lambda: home)
    monkeypatch.setattr(portable_data.paths, "config_file", lambda: home / ".env")
    monkeypatch.setattr(portable_data, "_backup_dir", lambda: backups)


def test_richer_external_backup_wins_over_blank_exe_folder(tmp_path: Path, monkeypatch) -> None:
    install, home, backups = tmp_path / "new version", tmp_path / "permanent", tmp_path / "backups"
    legacy_db = install / "data" / "fm_finance.db"
    _database(legacy_db)
    install.joinpath(".env").write_text(
        "DATABASE_URL=sqlite:///data/fm_finance.db\nJWT_SECRET=" + "x" * 48 + "\n", encoding="utf-8")

    source_db = tmp_path / "source.db"
    _database(source_db, expenses=2, transactions=1)
    backups.mkdir()
    backup = backups / "FMFinance_backup_20261022-215807_exit.fmbak"
    with zipfile.ZipFile(backup, "w") as archive:
        archive.write(source_db, "data/fm_finance.db")
        archive.writestr(".env", "DATABASE_URL=sqlite:///data/old-name.db\nJWT_SECRET=" + "y" * 48 + "\n")
        archive.writestr("receipts/2026/receipt.pdf", b"%PDF recovered")

    _paths(monkeypatch, install, home, backups)
    result = portable_data.prepare()

    assert result.source == f"backup:{backup.name}"
    recovered = sqlite3.connect(home / "data" / "fm_finance.db")
    assert recovered.execute("SELECT count(*) FROM expenses").fetchone()[0] == 2
    assert recovered.execute("SELECT count(*) FROM transactions").fetchone()[0] == 1
    recovered.close()
    assert (home / "data" / "receipts" / "2026" / "receipt.pdf").read_bytes() == b"%PDF recovered"
    text = (home / ".env").read_text()
    assert "DATABASE_URL=sqlite:///data/fm_finance.db" in text
    assert "RECEIPT_DIR=data/receipts" in text
    assert legacy_db.exists()  # migration copies; it never removes the old database
    assert str(home) in (install / "DATA_LOCATION.txt").read_text()


def test_existing_permanent_home_is_never_replaced(tmp_path: Path, monkeypatch) -> None:
    install, home, backups = tmp_path / "another version", tmp_path / "permanent", tmp_path / "backups"
    stable_db = home / "data" / "fm_finance.db"
    _database(stable_db, expenses=4)
    home.joinpath(".env").write_text(
        "DATABASE_URL=sqlite:///data/fm_finance.db\nJWT_SECRET=" + "z" * 48 + "\n", encoding="utf-8")
    _paths(monkeypatch, install, home, backups)

    result = portable_data.prepare()

    assert result.source == "existing"
    db = sqlite3.connect(stable_db)
    assert db.execute("SELECT count(*) FROM expenses").fetchone()[0] == 4
    db.close()
