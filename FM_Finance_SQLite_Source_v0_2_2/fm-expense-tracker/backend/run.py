"""Entry point for development (`python run.py`) and for the PyInstaller executable."""

from __future__ import annotations

import sys
import os


def main() -> int:
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

    # Pass the app object (not an import string) so this works inside PyInstaller.
    uvicorn.run(create_app(), host=settings.APP_HOST, port=settings.APP_PORT,
                log_config=None, proxy_headers=True, forwarded_allow_ips="127.0.0.1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
