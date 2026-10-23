"""Entry point for development (`python run.py`) and for the PyInstaller executable."""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

log = logging.getLogger("fm_finance")


def _notify(message: str, title: str = "F&M Finance", error: bool = True) -> None:
    """Show a message box in the windowed EXE (no console), otherwise print."""
    if os.name == "nt" and getattr(sys, "frozen", False):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10 if error else 0x40)
            return
        except Exception:  # noqa: BLE001
            pass
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        print(message, file=stream)


def _port_in_use(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((probe_host, port)) == 0


def _is_fm_finance(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8")).get("app") == "fm-finance"
    except Exception:  # noqa: BLE001
        return False


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
            "DESKTOP_MODE=true",
            "ADMIN_EMAIL=admin@fmitai.com",
            "ADMIN_NAME=Administrator",
            f"ADMIN_INITIAL_PASSWORD={initial_password}",
            "RECEIPT_STORAGE=local",
            "RECEIPT_DIR=data/receipts",
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
    _notify(
        f"F&M Finance is ready.\n\nEmail: admin@fmitai.com\nTemporary password: {initial_password}\n\n"
        "The same information was saved to INITIAL_LOGIN.txt next to the app. It is deleted "
        "automatically when you change your password in Settings.",
        "F&M Finance - First Run", error=False,
    )


def _open_browser(port: int) -> None:
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()


def main() -> int:
    if sys.argv[1:] == ["--selftest"]:
        # Checks the bundled PDF/Word/email/OCR readers; writes selftest.txt next to the app (no console).
        from app.documents.selftest import run as selftest
        from app.paths import app_dir

        ok, report = selftest()
        (app_dir() / "selftest.txt").write_text(("PASS" if ok else "FAIL") + "\n" + report, encoding="utf-8")
        return 0 if ok else 1
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
        print("Usage: FMFinance.exe [--migrate-to-postgresql | --selftest]", file=sys.stderr)
        return 1
    from app.bootstrap import StartupError, startup
    from app.config import get_settings

    settings = get_settings()
    if _port_in_use(settings.APP_HOST, settings.APP_PORT):
        if _is_fm_finance(settings.APP_PORT):
            # Already running: just bring up the browser instead of starting a second copy.
            webbrowser.open(f"http://127.0.0.1:{settings.APP_PORT}/")
            return 0
        _notify(f"Port {settings.APP_PORT} is used by another program.\n\n"
                "Close that program, or change APP_PORT in the .env file next to FMFinance.exe.")
        return 1

    try:
        settings = startup()
    except StartupError as exc:
        _notify(f"F&M Finance could not start:\n\n{exc}\n\nDetails are in the logs folder next to the app.")
        return 1
    except Exception as exc:  # noqa: BLE001
        log.exception("Unexpected startup failure")
        _notify(f"F&M Finance could not start ({type(exc).__name__}).\n\n"
                "Details are in the logs folder next to the app.")
        return 1

    import uvicorn

    from app.main import create_app

    app = create_app()
    config = uvicorn.Config(app, host=settings.APP_HOST, port=settings.APP_PORT, log_config=None,
                            proxy_headers=True, forwarded_allow_ips="127.0.0.1")
    server = uvicorn.Server(config)
    app.state.server = server  # lets the desktop "Exit app" button stop the server
    if os.environ.get("FM_NO_BROWSER") != "1":  # the update helper restarts the app; the browser tab is already open
        _open_browser(settings.APP_PORT)
    try:
        server.run()
    except Exception as exc:  # noqa: BLE001
        log.exception("Server stopped unexpectedly")
        _notify(f"F&M Finance stopped unexpectedly ({type(exc).__name__}). See the logs folder.")
        return 1
    log.info("F&M Finance stopped")
    from app.data_backups import backup_on_exit

    backup_on_exit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
