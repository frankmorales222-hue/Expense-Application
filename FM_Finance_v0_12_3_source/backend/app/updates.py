"""In-app updates for the portable Windows app (v0.10.1).

An update is one signed file, FMFinance_Update_v<version>.fmupdate (a zip):
    manifest.json   {"format": 1, "app": "fm-finance", "version", "min_version", "exe_sha256", "exe_size",
                     "notes", "built_at"}
    manifest.sig    Ed25519 signature of manifest.json (base64), made with the build PC's private key
    FMFinance.exe   the new program

Installing: the administrator uploads the file (Administration > Updates). The app checks the signature, the
version and the program's SHA-256, and keeps it in updates/staged. "Install and restart" backs up the
database and .env to backups/, then hands over to a small helper script and closes. The helper waits for the
app to exit, keeps the old program as <name>.previous.exe, puts the new one in its place (same name and folder,
so shortcuts keep working), starts it and waits for it to answer with the new version. If it doesn't within
two minutes, the helper puts the old program and the database backup back and starts the old version.
Migrations run on start as always.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import __version__, paths, update_key

log = logging.getLogger(__name__)

APP_ID = "fm-finance"
FORMAT = 1
EXE_NAME_IN_PACKAGE = "FMFinance.exe"
MAX_EXE_BYTES = 1024 * 1024 * 1024  # 1 GB
KEEP_BACKUPS = 5
HEALTH_WAIT_SECONDS = 120


class UpdateError(Exception):
    """Shown to the administrator as is."""


# ---------------------------------------------------------------- versions
def parse_version(v: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+(\.\d+){1,3}", v or ""):
        raise UpdateError(f"Not a version number: {v!r}")
    return tuple(int(x) for x in v.split("."))


# ---------------------------------------------------------------- where things are (patched in tests)
def exe_path() -> Path:
    return Path(sys.executable).resolve()


def base_dir() -> Path:
    return paths.app_dir()


def updates_dir() -> Path:
    return base_dir() / "updates"


def staged_dir() -> Path:
    return updates_dir() / "staged"


def backups_dir() -> Path:
    return base_dir() / "backups"


def public_key_pem() -> str | None:
    return update_key.PUBLIC_KEY_PEM


def supported() -> tuple[bool, str]:
    """Updates are for the portable desktop app. (A server install is updated with its installer.)"""
    from .config import get_settings

    if not paths.is_frozen():
        return False, "Updates install into the Windows app (FMFinance.exe). This copy runs from source."
    if not get_settings().DESKTOP_MODE:
        return False, "This copy runs as a server (DESKTOP_MODE is off). Update it with the installer."
    if not public_key_pem():
        return False, "This build has no update key, so it can't check update files. Install the next version by hand once."
    if re.search(r"[%!^\"]", str(exe_path())):
        return False, "The folder name of the app contains % ! ^ or a quote. Move FMFinance.exe to a plain folder to use updates."
    return True, ""


# ---------------------------------------------------------------- checking an update file
@dataclass
class Manifest:
    version: str
    min_version: str
    exe_sha256: str
    exe_size: int
    notes: str
    built_at: str

    def as_dict(self) -> dict:
        return {"format": FORMAT, "app": APP_ID, "version": self.version, "min_version": self.min_version,
                "exe_sha256": self.exe_sha256, "exe_size": self.exe_size, "notes": self.notes,
                "built_at": self.built_at}


def _verify_signature(manifest_bytes: bytes, sig_b64: bytes) -> None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    pem = public_key_pem()
    if not pem:
        raise UpdateError("This build has no update key.")
    key = load_pem_public_key(pem.encode("ascii"))
    if not isinstance(key, Ed25519PublicKey):
        raise UpdateError("The update key in this build is not valid.")
    try:
        key.verify(base64.b64decode(sig_b64.strip(), validate=True), manifest_bytes)
    except (InvalidSignature, ValueError):
        raise UpdateError("This update file isn't signed by F&M IT Services (or it was changed). It was not installed.") from None


def _read_manifest(raw: bytes) -> Manifest:
    try:
        m = json.loads(raw.decode("utf-8"))
        if m.get("format") != FORMAT or m.get("app") != APP_ID:
            raise UpdateError("This isn't an F&M Finance update file.")
        man = Manifest(version=str(m["version"]), min_version=str(m.get("min_version") or "0.0.0"),
                       exe_sha256=str(m["exe_sha256"]).lower(), exe_size=int(m["exe_size"]),
                       notes=str(m.get("notes") or "")[:5000], built_at=str(m.get("built_at") or ""))
    except UpdateError:
        raise
    except Exception:  # noqa: BLE001
        raise UpdateError("The update file's details can't be read.") from None
    parse_version(man.version)
    parse_version(man.min_version)
    if not re.fullmatch(r"[0-9a-f]{64}", man.exe_sha256) or not 0 < man.exe_size <= MAX_EXE_BYTES:
        raise UpdateError("The update file's details can't be read.")
    return man


def check_versions(man: Manifest, current: str = __version__) -> str:
    """'upgrade' or 'reinstall' (same version, to repair a copy). Older versions are refused."""
    new, cur = parse_version(man.version), parse_version(current)
    if parse_version(man.min_version) > cur:
        raise UpdateError(f"Version {man.version} needs version {man.min_version} or newer first. "
                          f"This copy is {current}.")
    if new < cur:
        raise UpdateError(f"This file has version {man.version}, older than the {current} you have. "
                          "Going back a version isn't supported (the database may already be newer).")
    return "reinstall" if new == cur else "upgrade"


def stage(package: Path) -> dict:
    """Check an uploaded update file and keep its program in updates/staged. Returns what it contains."""
    try:
        zf = zipfile.ZipFile(package)
    except (zipfile.BadZipFile, OSError):
        raise UpdateError("This isn't an F&M Finance update file (.fmupdate).") from None
    with zf:
        names = set(zf.namelist())
        if names != {"manifest.json", "manifest.sig", EXE_NAME_IN_PACKAGE}:
            raise UpdateError("This isn't an F&M Finance update file (.fmupdate).")
        manifest_bytes = zf.read("manifest.json")
        _verify_signature(manifest_bytes, zf.read("manifest.sig"))
        man = _read_manifest(manifest_bytes)
        kind = check_versions(man)
        info = zf.getinfo(EXE_NAME_IN_PACKAGE)
        if info.file_size != man.exe_size:
            raise UpdateError("The program inside the update file doesn't match its details.")

        target = staged_dir()
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        new_exe = target / "FMFinance.new.exe"
        digest, written = hashlib.sha256(), 0
        with zf.open(info) as src, open(new_exe, "wb") as dst:
            for chunk in iter(lambda: src.read(1024 * 1024), b""):
                written += len(chunk)
                if written > man.exe_size:
                    break
                digest.update(chunk)
                dst.write(chunk)
    if written != man.exe_size or digest.hexdigest() != man.exe_sha256:
        shutil.rmtree(target, ignore_errors=True)
        raise UpdateError("The program inside the update file is damaged or was changed. It was not installed.")
    (target / "manifest.json").write_text(json.dumps(man.as_dict(), indent=2), encoding="utf-8")
    log.info("Update %s checked and staged (%s)", man.version, kind)
    return {**man.as_dict(), "kind": kind}


def staged() -> dict | None:
    m = staged_dir() / "manifest.json"
    exe = staged_dir() / "FMFinance.new.exe"
    if not (m.exists() and exe.exists()):
        return None
    try:
        data = json.loads(m.read_text(encoding="utf-8"))
        data["kind"] = check_versions(_read_manifest(json.dumps(data).encode("utf-8")))
        return data
    except UpdateError:
        return None


def discard() -> None:
    shutil.rmtree(staged_dir(), ignore_errors=True)


# ---------------------------------------------------------------- backups
def _sqlite_file() -> Path | None:
    from .database import get_engine

    url = get_engine().url
    if url.get_backend_name() != "sqlite" or not url.database:
        return None
    return Path(url.database).resolve()


def backup(version: str) -> Path:
    """The database (a consistent copy, even while the app is running) and .env, before an update."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = backups_dir() / f"before-v{version}-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    db = _sqlite_file()
    if db is not None and db.exists():
        src = sqlite3.connect(str(db))
        dst = sqlite3.connect(str(folder / db.name))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    env = paths.config_file()
    if env.exists():
        shutil.copy2(env, folder / ".env")
    old = sorted((p for p in backups_dir().iterdir() if p.is_dir() and p.name.startswith("before-v")),
                 key=lambda p: p.name)
    for p in old[:-KEEP_BACKUPS]:
        shutil.rmtree(p, ignore_errors=True)
    return folder


def backups() -> list[dict]:
    if not backups_dir().exists():
        return []
    out = []
    for p in sorted(backups_dir().iterdir(), key=lambda p: p.name, reverse=True):
        if p.is_dir() and p.name.startswith("before-v"):
            size = sum(f.stat().st_size for f in p.iterdir() if f.is_file())
            out.append({"name": p.name, "bytes": size})
    return out


# ---------------------------------------------------------------- the helper script
def helper_script(*, pids: list[int], exe: Path, new_exe: Path, version: str, port: int,
                  db: Path | None, db_backup: Path | None) -> str:
    """A plain .cmd file (no PowerShell needed). Paths are checked for characters cmd treats specially."""
    prev = exe.with_name(exe.stem + ".previous.exe")
    upd = updates_dir()
    lines = [
        "@echo off",
        "setlocal",
        "rem F&M Finance update helper (written by the app; safe to delete afterwards)",
        f'set "EXE={exe}"',
        f'set "EXENAME={exe.name}"',
        f'set "NEW={new_exe}"',
        f'set "PREV={prev}"',
        f'set "VERSION={version}"',
        f'set "PORT={port}"',
        f'set "DB={db or ""}"',
        f'set "DBBACKUP={db_backup or ""}"',
        f'set "LOG={upd / "update.log"}"',
        f'set "RESULT={upd / "last_result.txt"}"',
        f'set "PROBE={upd / "probe.txt"}"',
        'set "FM_NO_BROWSER=1"',
        "rem Start the new program as a fresh one-file app, not as a child of the old one (PyInstaller).",
        'set "PYINSTALLER_RESET_ENVIRONMENT=1"',
        'set "_PYI_APPLICATION_HOME_DIR="',
        'set "_PYI_ARCHIVE_FILE="',
        'set "_PYI_PARENT_PROCESS_LEVEL="',
        'set "_PYI_SPLASH_IPC="',
        'set "_MEIPASS2="',
        'echo %date% %time% Updating to %VERSION% >> "%LOG%"',
        "",
        "rem 1. Wait for the app to close (at most 3 minutes).",
        "set /a n=0",
        ":wait",
    ]
    for pid in pids:
        lines.append(f'tasklist /FI "PID eq {pid}" /NH 2>nul | find " {pid} " >nul && goto :still')
    lines += [
        "goto :closed",
        ":still",
        "set /a n+=1",
        "if %n% GEQ 90 goto :notclosed",
        "ping -n 3 127.0.0.1 >nul",
        "goto :wait",
        "",
        ":closed",
        "rem 2. Keep the old program, put the new one in its place.",
        'copy /y "%EXE%" "%PREV%" >nul || goto :notreplaced',
        "set /a n=0",
        ":swap",
        'copy /y "%NEW%" "%EXE%" >nul && goto :start',
        "set /a n+=1",
        "if %n% GEQ 15 goto :rollback",
        "ping -n 3 127.0.0.1 >nul",
        "goto :swap",
        "",
        ":start",
        'echo %date% %time% New program in place, starting it >> "%LOG%"',
        'start "" "%EXE%"',
        "rem 3. Wait for the new version to answer (about 2 minutes).",
        "set /a n=0",
        ":health",
        "ping -n 3 127.0.0.1 >nul",
        'del "%PROBE%" 2>nul',
        f'where curl.exe >nul 2>nul && curl.exe -s -m 3 "http://127.0.0.1:%PORT%/api/health/version" > "%PROBE%" 2>nul',
        'where curl.exe >nul 2>nul || powershell -NoProfile -Command "try{(Invoke-WebRequest -UseBasicParsing '
        '-TimeoutSec 3 http://127.0.0.1:%PORT%/api/health/version).Content}catch{}" > "%PROBE%" 2>nul',
        "rem No /x: curl output may lack a final newline. ':ok' right after the version keeps 0.10.1 from matching 0.10.11.",
        'findstr /c:"fm-finance:%VERSION%:ok" "%PROBE%" >nul && goto :ok',
        "set /a n+=1",
        f"if %n% GEQ {HEALTH_WAIT_SECONDS // 2} goto :rollback",
        "goto :health",
        "",
        ":ok",
        '> "%RESULT%" echo status=ok',
        '>> "%RESULT%" echo version=%VERSION%',
        '>> "%RESULT%" echo when=%date% %time%',
        'echo %date% %time% Update to %VERSION% finished >> "%LOG%"',
        'del "%NEW%" 2>nul',
        'del "%PROBE%" 2>nul',
        "exit /b 0",
        "",
        ":rollback",
        'echo %date% %time% The new version did not start; putting the previous one back >> "%LOG%"',
        'taskkill /F /IM "%EXENAME%" >nul 2>nul',
        "ping -n 4 127.0.0.1 >nul",
        'copy /y "%PREV%" "%EXE%" >nul',
        'if "%DBBACKUP%"=="" goto :restarted',
        'if not exist "%DBBACKUP%" goto :restarted',
        'del "%DB%-wal" 2>nul',
        'del "%DB%-shm" 2>nul',
        'copy /y "%DBBACKUP%" "%DB%" >nul',
        'echo %date% %time% Database put back from the backup >> "%LOG%"',
        ":restarted",
        'start "" "%EXE%"',
        '> "%RESULT%" echo status=rolled_back',
        '>> "%RESULT%" echo version=%VERSION%',
        '>> "%RESULT%" echo when=%date% %time%',
        "exit /b 1",
        "",
        ":notreplaced",
        ":notclosed",
        'echo %date% %time% Could not replace the program; nothing was changed >> "%LOG%"',
        'start "" "%EXE%"',
        '> "%RESULT%" echo status=not_installed',
        '>> "%RESULT%" echo version=%VERSION%',
        '>> "%RESULT%" echo when=%date% %time%',
        "exit /b 1",
        "",
    ]
    return "\r\n".join(lines)


def _app_pids() -> list[int]:
    """This process and, for the one-file EXE, the launcher process that keeps the .exe open."""
    pids = [os.getpid()]
    if paths.is_frozen() and os.getppid() > 0:
        pids.append(os.getppid())
    return pids


def _helper_env() -> dict[str, str]:
    """The helper (and the program it starts) must not inherit the one-file EXE's private settings, or the new
    program would try to reuse the old one's unpacked files. Used by updates and by backup restores."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("_PYI_") and k.upper() != "_MEIPASS2"}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    env["FM_NO_BROWSER"] = "1"
    return env


def _launch(script: Path) -> None:
    flags = 0
    kwargs = {"cwd": str(base_dir()), "close_fds": True, "env": _helper_env()}
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        try:  # outlive the app even if it runs inside a job object
            subprocess.Popen(["cmd.exe", "/c", str(script)],
                             creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)  # type: ignore[attr-defined]
            return
        except OSError:
            pass
    subprocess.Popen(["cmd.exe", "/c", str(script)], creationflags=flags, **kwargs)


def apply(port: int) -> dict:
    """Back up, write the helper, start it. The caller then stops the server."""
    ok, why = supported()
    if not ok:
        raise UpdateError(why)
    info = staged()
    if info is None:
        raise UpdateError("Upload an update file first.")
    folder = backup(info["version"])
    db = _sqlite_file()
    script = updates_dir() / "apply_update.cmd"
    script.write_text(helper_script(
        pids=_app_pids(), exe=exe_path(), new_exe=staged_dir() / "FMFinance.new.exe", version=info["version"],
        port=port, db=db, db_backup=(folder / db.name) if db is not None else None), encoding="ascii", newline="")
    (updates_dir() / "last_result.txt").unlink(missing_ok=True)
    _launch(script)
    log.info("Update to %s started; backup in %s", info["version"], folder)
    return {"version": info["version"], "backup": folder.name}


def last_result() -> dict | None:
    p = updates_dir() / "last_result.txt"
    if not p.exists():
        return None
    out = {}
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        k, _, v = line.partition("=")
        if k.strip():
            out[k.strip()] = v.strip()
    return out or None


def after_start() -> None:
    """On start: drop a staged program that is now installed."""
    info_file = staged_dir() / "manifest.json"
    try:
        if info_file.exists():
            v = json.loads(info_file.read_text(encoding="utf-8")).get("version")
            if v and parse_version(v) <= parse_version(__version__):
                discard()
    except Exception:  # noqa: BLE001
        log.warning("Could not tidy the updates folder", exc_info=True)
