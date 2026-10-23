# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
import sys
sys.path.insert(0, str(ROOT / "backend"))  # lets collect_submodules("app") find the app package
frontend_dist = ROOT / "frontend" / "dist"
if not (frontend_dist / "index.html").exists():
    raise SystemExit("frontend/dist is missing. Run npm run build in frontend first.")

hiddenimports = [
    "app.schema_phase1", "app.banking", "app.banking.engine", "app.banking.importers",
    "app.banking.normalize", "app.schema_phase2", "app.schema_branding", "app.schema_multicompany",
    "app.schema_ledger", "app.tenancy", "app.access", "app.ledger", "app.ledger.chart", "app.ledger.posting",
    "app.ledger.sync", "app.ledger.books", "app.ledger.reports", "app.routers.bills", "app.routers.ledger",
    "app.routers.lines", "app.schema_sales", "app.invoicing", "app.invoicing.pdf", "app.invoicing.mailer",
    "app.invoicing.secretbox", "app.invoicing.service", "app.routers.invoices", "app.routers.payments",
    "app.routers.items", "app.routers.sales", "app.routers.mail", "cryptography.fernet",
    "app.schema_email_oauth", "app.invoicing.microsoft", "app.invoicing.outbox", "app.modules",
    "app.schema_modules", "app.routers.plans", "app.schema_themes", "app.routers.dashboard", "app.rules", "app.permissions", "app.schema_rules", "app.routers.rules", "app.routers.bank_rules", "app.routers.roles", "app.routers.ruleutil",
    "app.schema_owner_funds", "app.routers.owner_funds", "app.data_backups", "app.routers.backups",
    "app.schema_confidence", "app.routers.reconciliations", "app.routers.accountant",
    "app.documents", "app.documents.ai", "app.documents.fields", "app.documents.ocr",
    "app.documents.readers", "app.documents.selftest", "app.documents.service",
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "sqlalchemy.dialects.sqlite", "sqlalchemy.dialects.sqlite.pysqlite",
    "sqlite3", "mako", "mako.template", "argon2", "multipart", "python_multipart",
] + collect_submodules("alembic") + collect_submodules("app")
# collect_submodules("app") bundles every application module, including app.schema_* files that only
# Alembic migrations import at runtime, so a future migration module can't be left out again.

# Bill import (v0.4.0): OCR models (.onnx/.yaml), ONNX Runtime and PDFium DLLs, Outlook .msg reader.
extra_datas, extra_binaries = [], []
for package in ("rapidocr_onnxruntime", "onnxruntime", "pypdfium2", "pypdfium2_raw", "extract_msg", "pypdf", "fpdf", "fontTools"):
    d, b, h = collect_all(package)
    extra_datas += d
    extra_binaries += b
    hiddenimports += h

a = Analysis(
    [str(ROOT / "backend" / "run.py")],
    pathex=[str(ROOT / "backend")],
    binaries=extra_binaries,
    datas=[
        (str(frontend_dist), "frontend/dist"),
        (str(ROOT / "backend" / "alembic"), "backend/alembic"),
    ] + extra_datas,
    hiddenimports=hiddenimports,
    hookspath=[], runtime_hooks=[],
    excludes=["tkinter", "pytest", "IPython", "matplotlib", "pandas", "psycopg2", "psycopg"],
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
