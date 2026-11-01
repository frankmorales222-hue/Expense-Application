"""Move packaged installations onto one durable per-user data home.

Older portable builds kept ``.env``, SQLite and receipts beside each EXE. That made a newly downloaded EXE
look like a blank company when it was launched from another folder. v0.12.2 copies the best existing data
into a stable LocalAppData home. The old files and external backups are never removed.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy.engine import make_url

from . import paths

BUSINESS_TABLES = (
    "expenses", "transactions", "journal_entries", "invoices", "bills", "customers",
    "financial_accounts", "receipts", "customer_payments", "bill_payments",
)


@dataclass(frozen=True)
class Preparation:
    home: Path
    source: str = "existing"


def _env_value(text: str, key: str, default: str = "") -> str:
    prefix = key.upper() + "="
    for line in text.splitlines():
        if line.strip().upper().startswith(prefix):
            return line.strip().split("=", 1)[1].strip()
    return default


def _set_env(text: str, key: str, value: str) -> str:
    prefix = key.upper() + "="
    out, replaced = [], False
    for line in text.splitlines():
        if line.strip().upper().startswith(prefix):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    return "\n".join(out).rstrip() + "\n"


def _legacy_sqlite(text: str, base: Path) -> Path | None:
    value = _env_value(text, "DATABASE_URL", "sqlite:///data/fm_finance.db")
    try:
        url = make_url(value)
    except Exception:  # noqa: BLE001
        return None
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    path = Path(url.database)
    return path if path.is_absolute() else base / path


def _score(path: Path) -> int:
    if not path.is_file():
        return -1
    try:
        db = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        try:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                return -1
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"users", "companies", "alembic_version"}.issubset(tables):
                return -1
            return sum(db.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                       for name in BUSINESS_TABLES if name in tables)
        finally:
            db.close()
    except sqlite3.Error:
        return -1


def _copy_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    part.unlink(missing_ok=True)
    src, dst = sqlite3.connect(str(source)), sqlite3.connect(str(part))
    try:
        src.backup(dst)
        if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("copied database failed its integrity check")
    finally:
        dst.close()
        src.close()
    os.replace(part, target)


def _copy_receipts(source: Path, target: Path) -> None:
    if not source.is_dir():
        return
    for file in source.rglob("*"):
        if file.is_file() and not file.is_symlink():
            destination = target / file.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copy2(file, destination)


def _backup_dir() -> Path:
    return Path.home() / "Documents" / "FM Finance Backups"


def _best_backup() -> tuple[Path | None, int]:
    root, best, best_score = _backup_dir(), None, -1
    if not root.is_dir():
        return best, best_score
    for backup in sorted(root.glob("FMFinance_backup_*.fmbak"), reverse=True):
        try:
            with zipfile.ZipFile(backup) as archive:
                if "data/fm_finance.db" not in archive.namelist():
                    continue
                with tempfile.TemporaryDirectory(prefix="fmfinance-find-", dir=root) as temp:
                    candidate = Path(temp) / "candidate.db"
                    with archive.open("data/fm_finance.db") as src, open(candidate, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    score = _score(candidate)
            if score > best_score:
                best, best_score = backup, score
        except (OSError, zipfile.BadZipFile, KeyError):
            continue
    return best, best_score


def _portable_env(text: str) -> str:
    text = _set_env(text, "DATABASE_URL", "sqlite:///data/fm_finance.db")
    text = _set_env(text, "RECEIPT_STORAGE", "local")
    text = _set_env(text, "RECEIPT_DIR", "data/receipts")
    return _set_env(text, "LOG_DIR", "logs")


def _write_env(text: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(".part")
    part.write_text(_portable_env(text), encoding="utf-8")
    os.replace(part, target)


def _import_backup(backup: Path, home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fmfinance-recover-", dir=home) as temp:
        temp_root = Path(temp)
        with zipfile.ZipFile(backup) as archive:
            database = temp_root / "fm_finance.db"
            with archive.open("data/fm_finance.db") as src, open(database, "wb") as dst:
                shutil.copyfileobj(src, dst)
            env_text = archive.read(".env").decode("utf-8") if ".env" in archive.namelist() else ""
            receipts = temp_root / "receipts"
            for name in archive.namelist():
                pure = PurePosixPath(name)
                if not name.startswith("receipts/") or pure.is_absolute() or ".." in pure.parts or name.endswith("/"):
                    continue
                destination = receipts.joinpath(*pure.parts[1:])
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as src, open(destination, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        _copy_database(database, home / "data" / "fm_finance.db")
        _copy_receipts(receipts, home / "data" / "receipts")
        _write_env(env_text, home / ".env")


def _import_legacy(env: Path, database: Path, home: Path) -> None:
    text = env.read_text(encoding="utf-8", errors="replace")
    receipt_value = _env_value(text, "RECEIPT_DIR", "data/receipts")
    receipts = Path(receipt_value)
    if not receipts.is_absolute():
        receipts = env.parent / receipts
    _copy_database(database, home / "data" / "fm_finance.db")
    _copy_receipts(receipts, home / "data" / "receipts")
    _write_env(text, home / ".env")


def _write_pointer(home: Path) -> None:
    if paths.app_dir() == home:
        return
    try:
        (paths.app_dir() / "DATA_LOCATION.txt").write_text(
            "F&M Finance keeps the live company database and receipts here:\n"
            f"{home}\n\nDo not delete this folder. Use Settings > Backup and restore for copies.\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def prepare() -> Preparation:
    """Prepare the stable home before Settings is imported. Existing sources are copied, never removed."""
    home, config = paths.data_home(), paths.config_file()
    if not paths.is_frozen():
        return Preparation(home)
    home.mkdir(parents=True, exist_ok=True)
    if config.is_file():
        _write_pointer(home)
        return Preparation(home)

    legacy_env = paths.app_dir() / ".env"
    legacy_db, legacy_score = None, -1
    if legacy_env.is_file():
        legacy_db = _legacy_sqlite(legacy_env.read_text(encoding="utf-8", errors="replace"), paths.app_dir())
        if legacy_db is not None:
            legacy_score = _score(legacy_db)
    backup, backup_score = _best_backup()

    source = "new"
    if backup is not None and backup_score > legacy_score:
        _import_backup(backup, home)
        source = f"backup:{backup.name}"
    elif legacy_env.is_file() and legacy_db is not None and legacy_score >= 0:
        _import_legacy(legacy_env, legacy_db, home)
        source = f"legacy:{legacy_db}"
    _write_pointer(home)
    return Preparation(home, source)
