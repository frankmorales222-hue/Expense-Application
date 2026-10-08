# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
frontend_dist = ROOT / "frontend" / "dist"
if not (frontend_dist / "index.html").exists():
    raise SystemExit("frontend/dist is missing. Run npm run build in frontend first.")

hiddenimports = [
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "sqlalchemy.dialects.sqlite", "sqlalchemy.dialects.sqlite.pysqlite",
    "sqlite3", "mako", "mako.template", "argon2", "multipart", "python_multipart",
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
    hookspath=[], runtime_hooks=[],
    excludes=["tkinter", "pytest", "IPython", "matplotlib", "numpy", "pandas", "psycopg2", "psycopg"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FMFinance",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
