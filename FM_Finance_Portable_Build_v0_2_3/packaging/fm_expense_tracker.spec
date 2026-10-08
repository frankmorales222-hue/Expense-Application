# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for F&M Finance. Build from the project root with:
#   .venv\Scripts\python.exe -m PyInstaller packaging\fm_expense_tracker.spec --noconfirm --clean
#
# Output (one-folder build):
#   dist\FMExpenseTracker\FMExpenseTracker.exe   <- the program
#   dist\FMExpenseTracker\_internal\             <- Python runtime, frontend build, migrations
# .env and logs\ live next to the .exe.

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # project root (this file lives in packaging/)

frontend_dist = ROOT / "frontend" / "dist"
if not (frontend_dist / "index.html").exists():
    raise SystemExit("frontend/dist is missing. Run 'npm run build' in the frontend folder first.")

hiddenimports = [
    # Uvicorn picks these at runtime, so PyInstaller can't see them statically.
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # Database driver and dialect (loaded by URL at runtime).
    "sqlalchemy.dialects.postgresql",
    "sqlalchemy.dialects.postgresql.psycopg2",
    "psycopg2",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.pysqlite",
    "sqlite3",
    # Used by the migration scripts, which are loaded from files at runtime.
    "mako",
    "mako.template",
    "argon2",
    "multipart",
    "python_multipart",
] + collect_submodules("alembic")

a = Analysis(
    [str(ROOT / "backend" / "run.py")],
    pathex=[str(ROOT / "backend")],
    binaries=[],
    datas=[
        (str(frontend_dist), "frontend/dist"),
        (str(ROOT / "backend" / "alembic"), "backend/alembic"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "IPython", "matplotlib", "numpy", "pandas"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FMExpenseTracker",
    debug=False,
    strip=False,
    upx=False,          # UPX-packed executables trigger antivirus false positives
    console=True,       # keep a console so the service can capture logs
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="FMExpenseTracker",
)
