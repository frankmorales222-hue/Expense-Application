"""Full portable data backups and safe restore hand-off (v0.11.0).

Backups are ordinary zip-compatible ``.fmbak`` files containing a consistent SQLite copy, local receipts and
the app's settings. They default to Documents/FM Finance Backups, outside the EXE folder. Restore is performed
by a Windows helper after the running process exits; if the restored copy cannot start, the helper puts the
pre-restore data back automatically.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import __version__, paths, updates
from .config import get_settings

log = logging.getLogger(__name__)
FORMAT = 1
AUTO_KEEP = 14
MAX_BACKUP_BYTES = 10 * 1024 * 1024 * 1024  # protects extraction; local receipts may be large


class BackupError(Exception):
    """Safe message shown to the installation administrator."""


def backup_dir() -> Path:
    return get_settings().backup_path


def sqlite_file() -> Path | None:
    from .database import get_engine

    url = get_engine().url
    return Path(url.database).resolve() if url.get_backend_name() == "sqlite" and url.database else None


def supported() -> tuple[bool, str]:
    settings = get_settings()
    if not paths.is_frozen():
        return False, "Full backups are available in the Windows app. This copy runs from source."
    if not settings.DESKTOP_MODE:
        return False, "This copy runs as a server. Back it up with the server's database and storage tools."
    if sqlite_file() is None:
        return False, "Portable backup and restore is for the SQLite edition."
    if settings.receipt_backend != "local":
        return False, "Receipts are stored on a server. Back up that storage and the database together."
    helper_paths = (paths.app_dir(), settings.receipt_path, sqlite_file())
    if any(path is not None and re.search(r'[%!^\"]', str(path)) for path in helper_paths):
        return False, "An app, data or receipt folder contains % ! ^ or a quote. Move it to a plain folder before restoring."
    return True, ""


def _safe_reason(reason: str) -> str:
    clean = re.sub(r"[^a-z0-9-]+", "-", reason.strip().lower()).strip("-")
    return clean[:30] or "manual"


def _copy_database(target: Path) -> None:
    db = sqlite_file()
    if db is None or not db.exists():
        raise BackupError("The SQLite database file could not be found.")
    src = sqlite3.connect(str(db))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
        if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise BackupError("The database did not pass its integrity check.")
    finally:
        dst.close()
        src.close()


def create(reason: str = "manual") -> dict:
    ok, why = supported()
    if not ok:
        raise BackupError(why)
    root = backup_dir()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    reason = _safe_reason(reason)
    name = f"FMFinance_backup_{stamp}_{reason}.fmbak"
    final, part = root / name, root / (name + ".part")
    settings = get_settings()
    try:
        with tempfile.TemporaryDirectory(prefix="fmfinance-backup-", dir=root) as temp:
            db_copy = Path(temp) / "fm_finance.db"
            _copy_database(db_copy)
            receipt_root = settings.receipt_path
            manifest = {
                "format": FORMAT, "app": "fm-finance", "version": __version__,
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"), "reason": reason,
                "database": "data/fm_finance.db", "settings": ".env",
                "receipts_included": True, "receipt_count": 0,
            }
            with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                zf.write(db_copy, "data/fm_finance.db")
                env = paths.config_file()
                if env.is_file():
                    zf.write(env, ".env")
                if receipt_root.is_dir():
                    for file in sorted(receipt_root.rglob("*")):
                        if file.is_file() and not file.is_symlink():
                            rel = file.relative_to(receipt_root).as_posix()
                            zf.write(file, f"receipts/{rel}")
                            manifest["receipt_count"] += 1
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        _read_manifest(part, verify_db=True)
        os.replace(part, final)
    except BackupError:
        part.unlink(missing_ok=True)
        raise
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise BackupError(f"The backup could not be written to {root}.") from exc
    _trim_auto()
    log.info("Full data backup created: %s", final)
    return _info(final)


def _read_manifest(path: Path, *, verify_db: bool = False) -> dict:
    try:
        if path.stat().st_size > MAX_BACKUP_BYTES:
            raise BackupError("The backup file is too large.")
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if len(names) != len(set(names)) or sum(info.file_size for info in zf.infolist()) > MAX_BACKUP_BYTES:
                raise BackupError("This backup file is too large or contains duplicate files.")
            for name in names:
                p = PurePosixPath(name)
                if p.is_absolute() or ".." in p.parts or not (
                    name in ("manifest.json", ".env", "data/fm_finance.db") or name.startswith("receipts/")
                ):
                    raise BackupError("This is not a safe F&M Finance backup file.")
            if "manifest.json" not in names or "data/fm_finance.db" not in names:
                raise BackupError("This is not an F&M Finance backup file.")
            m = json.loads(zf.read("manifest.json").decode("utf-8"))
            if m.get("format") != FORMAT or m.get("app") != "fm-finance":
                raise BackupError("This is not an F&M Finance backup file.")
            if verify_db:
                # A packaged Windows app can be denied access to the redirected system temp folder. The backup's
                # own folder is already known to be writable and is also the safest place for this short-lived copy.
                with tempfile.TemporaryDirectory(prefix="fmfinance-check-", dir=path.parent) as temp:
                    db = Path(temp) / "db.sqlite"
                    with zf.open("data/fm_finance.db") as src, open(db, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    conn = sqlite3.connect(str(db))
                    try:
                        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                            raise BackupError("The database in this backup is damaged.")
                        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                        if not {"users", "companies", "alembic_version"}.issubset(tables):
                            raise BackupError("The backup does not contain an F&M Finance database.")
                    finally:
                        conn.close()
            return m
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise BackupError("This backup file is damaged or cannot be read.") from exc


def _info(path: Path) -> dict:
    m = _read_manifest(path)
    return {"name": path.name, "bytes": path.stat().st_size, "created_at": str(m.get("created_at") or ""),
            "version": str(m.get("version") or ""), "reason": str(m.get("reason") or ""),
            "receipt_count": int(m.get("receipt_count") or 0)}


def list_backups() -> list[dict]:
    root = backup_dir()
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("FMFinance_backup_*.fmbak"), reverse=True):
        try:
            out.append(_info(path))
        except BackupError:
            log.warning("Ignoring unreadable backup %s", path)
    return out


def _trim_auto() -> None:
    autos = [backup_dir() / x["name"] for x in list_backups() if x["reason"] in ("startup", "exit")]
    for path in autos[AUTO_KEEP:]:
        path.unlink(missing_ok=True)


def ensure_daily() -> None:
    ok, _ = supported()
    if not ok:
        return
    day = datetime.now().date().isoformat()
    if any(x["created_at"].startswith(day) for x in list_backups() if x["reason"] == "startup"):
        return
    try:
        create("startup")
    except BackupError:
        log.warning("Automatic startup backup failed", exc_info=True)


def backup_on_exit() -> None:
    ok, _ = supported()
    if not ok:
        return
    try:
        create("exit")
    except BackupError:
        log.warning("Automatic exit backup failed", exc_info=True)


def _extract(path: Path, target: Path) -> dict:
    m = _read_manifest(path, verify_db=True)
    target.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if name in ("data/fm_finance.db", ".env") or name.startswith("receipts/"):
                zf.extract(name, target)
    (target / "receipts").mkdir(exist_ok=True)
    return m


def _restore_script(*, restore: Path, recovery: Path, stage_root: Path,
                    restore_env: bool, port: int) -> str:
    db = sqlite_file()
    assert db is not None
    exe = updates.exe_path()
    receipts = get_settings().receipt_path.resolve()
    env = paths.config_file()
    result = paths.app_dir() / "updates" / "restore_result.txt"
    probe = paths.app_dir() / "updates" / "restore_probe.txt"
    lines = [
        "@echo off", "setlocal", "rem F&M Finance backup restore helper",
        f'set "EXE={exe}"', f'set "EXENAME={exe.name}"', f'set "PORT={port}"',
        f'set "DB={db}"', f'set "RECEIPTS={receipts}"', f'set "STAGE={stage_root}"',
        f'set "RESTORE={restore}"', f'set "RECOVERY={recovery}"', f'set "ENV={env}"',
        f'set "RESULT={result}"', f'set "PROBE={probe}"', 'set "FM_NO_BROWSER=1"',
        "set /a n=0", ":wait",
    ]
    for pid in updates._app_pids():
        lines.append(f'tasklist /FI "PID eq {pid}" /NH 2>nul | find " {pid} " >nul && goto :still')
    lines += [
        "goto :closed", ":still", "set /a n+=1", "if %n% GEQ 90 goto :failed",
        "ping -n 3 127.0.0.1 >nul", "goto :wait", ":closed",
        'del "%DB%-wal" 2>nul', 'del "%DB%-shm" 2>nul',
        'copy /y "%RESTORE%\\data\\fm_finance.db" "%DB%" >nul || goto :rollback',
        'if not exist "%RECEIPTS%" mkdir "%RECEIPTS%"',
        'robocopy "%RESTORE%\\receipts" "%RECEIPTS%" /MIR /R:2 /W:1 >nul',
        "if errorlevel 8 goto :rollback",
    ]
    if restore_env:
        lines.append('if exist "%RESTORE%\\.env" copy /y "%RESTORE%\\.env" "%ENV%" >nul')
    lines += [
        'start "" "%EXE%"', "set /a n=0", ":health", "ping -n 3 127.0.0.1 >nul",
        'del "%PROBE%" 2>nul',
        'curl.exe -s -m 3 "http://127.0.0.1:%PORT%/api/health/version" > "%PROBE%" 2>nul',
        'findstr /r /c:"fm-finance:.*:ok" "%PROBE%" >nul && goto :ok',
        "set /a n+=1", "if %n% GEQ 60 goto :rollback", "goto :health", ":ok",
        '> "%RESULT%" echo status=ok', 'rmdir /s /q "%STAGE%" 2>nul', "exit /b 0", ":rollback",
        'taskkill /F /IM "%EXENAME%" >nul 2>nul', "ping -n 4 127.0.0.1 >nul",
        'del "%DB%-wal" 2>nul', 'del "%DB%-shm" 2>nul',
        'copy /y "%RECOVERY%\\data\\fm_finance.db" "%DB%" >nul',
        'robocopy "%RECOVERY%\\receipts" "%RECEIPTS%" /MIR /R:2 /W:1 >nul',
    ]
    if restore_env:
        lines += ['if exist "%RECOVERY%\\.env" copy /y "%RECOVERY%\\.env" "%ENV%" >nul',
                  'if not exist "%RECOVERY%\\.env" del "%ENV%" 2>nul']
    lines += ['start "" "%EXE%"', '> "%RESULT%" echo status=rolled_back',
              'rmdir /s /q "%STAGE%" 2>nul', "exit /b 1", ":failed",
              '> "%RESULT%" echo status=not_restored', 'rmdir /s /q "%STAGE%" 2>nul', "exit /b 1", ""]
    return "\r\n".join(lines)


def _port_from_env(path: Path, fallback: int) -> int:
    """Read APP_PORT from a staged .env without applying any other restored setting yet."""
    if not path.is_file():
        return fallback
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = re.match(r"\s*APP_PORT\s*=\s*['\"]?([0-9]+)", line)
        if match:
            value = int(match.group(1))
            return value if 1 <= value <= 65535 else fallback
    return fallback


def begin_restore(name: str, *, restore_settings: bool, port: int) -> dict:
    ok, why = supported()
    if not ok:
        raise BackupError(why)
    if Path(name).name != name or not name.endswith(".fmbak"):
        raise BackupError("Backup not found.")
    selected = backup_dir() / name
    if not selected.is_file():
        raise BackupError("Backup not found.")
    _read_manifest(selected, verify_db=True)
    recovery_info = create("before-restore")
    recovery = backup_dir() / recovery_info["name"]
    stage_root = paths.app_dir() / "updates" / f"restore-{uuid.uuid4().hex}"
    restore_stage, recovery_stage = stage_root / "selected", stage_root / "recovery"
    try:
        manifest = _extract(selected, restore_stage)
        _extract(recovery, recovery_stage)
        health_port = _port_from_env(restore_stage / ".env", port) if restore_settings else port
        script = paths.app_dir() / "updates" / "restore_backup.cmd"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(_restore_script(restore=restore_stage, recovery=recovery_stage, stage_root=stage_root,
                                          restore_env=restore_settings, port=health_port),
                          encoding="ascii", newline="")
        (paths.app_dir() / "updates" / "restore_result.txt").unlink(missing_ok=True)
        updates._launch(script)
    except Exception:
        shutil.rmtree(stage_root, ignore_errors=True)
        raise
    log.info("Restore started from %s; current data saved as %s", name, recovery.name)
    return {"backup": name, "version": str(manifest.get("version") or ""),
            "recovery_backup": recovery.name}


def last_result() -> dict | None:
    path = paths.app_dir() / "updates" / "restore_result.txt"
    if not path.is_file():
        return None
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, _, value = line.partition("=")
        if key:
            out[key.strip()] = value.strip()
    return out or None
