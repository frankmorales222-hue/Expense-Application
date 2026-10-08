"""Entry point for development (`python run.py`) and for the PyInstaller executable."""

from __future__ import annotations

import sys
import os
import secrets
import threading
import webbrowser
from pathlib import Path


def _prepare_portable_first_run() -> None:
    """Create a secure local config automatically for the portable Windows build."""
    if not getattr(sys, "frozen", False):
        return
    app_dir = Path(sys.executable).resolve().parent
    env_path = app_dir / ".env"
    if env_path.exists():
        return

    jwt_secret = secrets.token_urlsafe(48)
    initial_password = secrets.token_urlsafe(14)
    env_path.write_text(
        "\n".join([
            "APP_HOST=127.0.0.1",
            "APP_PORT=8010",
            "APP_ENV=production",
            "DATABASE_URL=sqlite:///data/fm_finance.db",
            f"JWT_SECRET={jwt_secret}",
            "JWT_EXPIRE_HOURS=12",
            "COOKIE_SECURE=false",
            "ADMIN_EMAIL=admin@fmitai.com",
            "ADMIN_NAME=Administrator",
            f"ADMIN_INITIAL_PASSWORD={initial_password}",
            "MINIO_ENDPOINT=localhost:9000",
            "MINIO_ACCESS_KEY=",
            "MINIO_SECRET_KEY=",
            "MINIO_SECURE=false",
            "MINIO_BUCKET=expenses",
            "MAX_RECEIPT_MB=10",
            "CURRENCY=USD",
            "APPROVAL_REQUIRED=false",
            "DEFAULT_APPROVAL_THRESHOLD=500.00",
            "LOG_DIR=logs",
            "",
        ]),
        encoding="utf-8",
    )
    login_note = app_dir / "INITIAL_LOGIN.txt"
    login_note.write_text(
        "F&M Finance - Initial Login\n"
        "===========================\n"
        "Email: admin@fmitai.com\n"
        f"Temporary password: {initial_password}\n\n"
        "Change this password after your first login.\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"F&M Finance is ready.\n\nEmail: admin@fmitai.com\nTemporary password: {initial_password}\n\nThe same information was saved to INITIAL_LOGIN.txt next to the app.",
                "F&M Finance - First Run",
                0x40,
            )
        except Exception:
            pass


def _open_browser(port: int) -> None:
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()


def main() -> int:
    _prepare_portable_first_run()
    if sys.argv[1:] == ["--migrate-to-postgresql"]:
        from app.config import get_settings
        from app.transfer import TransferError, transfer_to_postgresql

        target = os.environ.get("POSTGRES_MIGRATION_URL", "")
        if not target:
            print("Set POSTGRES_MIGRATION_URL to the empty PostgreSQL destination first.", file=sys.stderr)
            return 1
        try:
            counts = transfer_to_postgresql(get_settings().DATABASE_URL, target)
        except TransferError as exc:
            print(f"Transfer stopped: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            # Do not print database URLs, SQL parameters, passwords or financial data.
            print(f"Transfer failed ({type(exc).__name__}). Check the connections, schema and permissions. "
                  "No destination application records were committed by this attempt.", file=sys.stderr)
            return 1
        print(f"Transfer complete. Copied records: {counts}. Source is retained. "
              "Update DATABASE_URL only after verifying the destination and receipt storage.")
        return 0
    if sys.argv[1:]:
        print("Usage: FMExpenseTracker.exe [--migrate-to-postgresql]", file=sys.stderr)
        return 1
    from app.bootstrap import StartupError, startup

    try:
        settings = startup()
    except StartupError as exc:
        print(f"\nF&M Finance could not start:\n  {exc}\n", file=sys.stderr)
        return 1

    import uvicorn

    from app.main import create_app

    _open_browser(settings.APP_PORT)

    # Pass the app object (not an import string) so this works inside PyInstaller.
    uvicorn.run(create_app(), host=settings.APP_HOST, port=settings.APP_PORT,
                log_config=None, proxy_headers=True, forwarded_allow_ips="127.0.0.1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
