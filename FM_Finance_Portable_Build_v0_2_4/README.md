# F&M Finance — Expense Tracker (v0.2.2)

Expense tracking for F&M IT Services: record expenses, attach receipts, track what's been paid and what the business owes you back, and see spending by category and month. Built to be extended with invoicing and bank sync later.

**Stack:** FastAPI + SQLAlchemy + Alembic (Python 3.11+), React 18 + TypeScript + Vite, PostgreSQL (production) or SQLite (local testing), MinIO for receipts, packaged with PyInstaller and run as a Windows service via NSSM.

---

## What it does

- Sign in (single admin account created on first start; roles `admin`, `approver`, `submitter` are ready for later)
- Add, edit, and delete expenses (date, vendor with autocomplete, category, amount, description, payment method, reimbursable flag, notes)
- Attach receipts (PDF, JPG, PNG, HEIC up to 10 MB). Files are checked by content, not just extension, and stored in a private MinIO bucket. Receipts are streamed through the app, so MinIO never needs to be reachable from other computers.
- Status workflow: approved → paid (and undo). With `APPROVAL_REQUIRED=true`, amounts at or above a category's threshold start as pending and need approval.
- Full history of every change on each expense (audit log)
- Expense list with search, filters, sorting, paging, a filtered total, and CSV export
- Dashboard: total spent, owed back to you, spending by category, last 12 months
- Settings: add/rename/reorder/hide categories, per-category approval thresholds, change password

---

## Quick local test with SQLite (Windows source package)

Extract the complete ZIP into a writable folder and run:

```bat
packaging\run_local.bat
```

This needs Python 3.11+ and internet access for the existing Python dependencies.
The release ZIP includes the compiled React frontend, so Node.js is unnecessary
for this test launcher. Node.js is still needed to rebuild the UI or installer.
The script creates `.venv`, installs the existing requirements, opens first-run
setup if `.env` is absent, and starts the app. Choose SQLite and configure receipt
storage later. Enter an administrator password (10+ characters), then open
http://127.0.0.1:8010 after startup. Keep the console open; Ctrl+C stops the app.

An existing `.env` is never overwritten. To switch a previous PostgreSQL install
into a separate SQLite test, back up `.env`, then set
`DATABASE_URL=sqlite:///data/fm_finance.db`. This does not copy PostgreSQL data.
Use the built app's installation folder for executable-mode configuration.

SQLite creates `data/fm_finance.db` beside `.env`/the executable, independent of the
working directory. Money stays Decimal in Python and uses exact integer cents in
SQLite; PostgreSQL retains NUMERIC(12,2). SQLite has foreign keys, a 30-second busy
timeout, and WAL mode. It is intended for local workflow testing, not a substitute
for final PostgreSQL multi-user/production validation. Do not edit raw SQLite money
columns as dollars: their stored unit is cents.

Without MinIO credentials, expense entry, dashboards, reports, categories and
authentication work. `/api/health` reports storage degraded; receipt operations
return 503. To enable receipts, configure the MinIO endpoint/access/secret keys in
`.env` and restart. Receipt bytes remain in MinIO, not in SQLite.

### Moving the test data to PostgreSQL later

1. Stop the SQLite app and all writers. Back up `.env`, the complete SQLite data
   folder, and the MinIO bucket if receipts were uploaded.
2. Create a new empty PostgreSQL database/user. **Do not start the app against it**
   before the transfer, because startup would seed users/categories. Keep `.env`
   pointing to the SQLite source throughout the copy.
3. In the source project, set POSTGRES_MIGRATION_URL for this shell only, then run:

```bat
set POSTGRES_MIGRATION_URL=postgresql+psycopg2://fm_user:your-password@localhost:5432/fm_finance
cd backend
..\.venv\Scripts\python.exe run.py --migrate-to-postgresql
set POSTGRES_MIGRATION_URL=
```

For the packaged app, run `FMExpenseTracker.exe --migrate-to-postgresql` from its
folder with the same environment variable. URL-encode special characters in the
PostgreSQL password. Never share the environment value or a populated .env file.

The tool applies PostgreSQL migrations, refuses a target containing application
records, locks the SQLite source for a consistent snapshot, preserves IDs/password
hashes/audit history/deleted records/receipt metadata, verifies counts and money
totals, and commits destination records in one transaction. A failed record copy
rolls back its rows; created destination schema can remain. It adds a transfer audit
entry. The source is retained, and no .env values are changed automatically.

4. Verify records and logins, then change DATABASE_URL in `.env` to PostgreSQL and
   restart. Keep the same MinIO connection/bucket so existing receipt keys still
   resolve. The transfer copies receipt metadata, **not receipt files**; move those
   separately if changing storage servers. Retain the SQLite backup until validated.

## Prerequisites

| Needed for | Software |
|---|---|
| Building | Python 3.11+ (tick "Add python.exe to PATH"), Node.js 20 LTS+ |
| Local SQLite testing | No database server; Python 3.11+ for the source launcher, or the built EXE |
| Production / receipts | PostgreSQL 14+ when selected; MinIO for uploads; [NSSM](https://nssm.cc) for Windows service mode |

### Create the PostgreSQL database (only when using PostgreSQL)

```sql
CREATE USER fm_user WITH PASSWORD 'choose-a-strong-password';
CREATE DATABASE fm_finance OWNER fm_user;
```

The app creates all tables itself on first start. The `pgcrypto` extension is enabled by the first migration; if `fm_user` isn't allowed to create extensions, run `CREATE EXTENSION pgcrypto;` once in `fm_finance` as a superuser.

### MinIO

Create an access key for the app. The `expenses` bucket is created automatically (private) on first start.

---

## Windows setup installer (v0.2.2)

This release adds SQLite compatibility to the existing application. The stack,
UI, authentication, receipt privacy and PostgreSQL support are retained. No new
runtime dependencies are required.

### Build the distributable installer

On a **64-bit Windows 10/11 build computer**, install Python 3.11+ (64-bit),
Node.js 20+, and **Inno Setup 6.3+** from https://jrsoftware.org/isdl.php.
Inno Setup is a packaging tool only; it is not an application runtime dependency.
The build downloads npm and pip dependencies, so it needs internet access.

Open Command Prompt in the project root and run:

```bat
packaging\build_installer.bat
```

This calls the existing `packaging\build.bat`, then compiles `packaging\installer.iss`.
Output: **`installer-output\FM_Finance_Setup_v0.2.2.exe`**.
Distribute that setup EXE. The destination computer needs neither Python nor Node.
The setup is unsigned; signing for public distribution requires your own certificate.
Do not disable Windows security to run it. The source ZIP is not a compiled installer.

### Install and first launch

1. For SQLite expense testing, no database server is required. MinIO is optional
   until you want receipt uploads. For PostgreSQL, provision its database/user first.
   These services are **not bundled or installed** by this setup.
2. Run the generated setup EXE. It installs for the current Windows user under
   `%LOCALAPPDATA%\Programs\FM Finance`, creates a Start Menu shortcut, and offers
   a desktop shortcut and launch after setup. Choose a folder writable by that user.
3. First launch displays database, receipt storage, and administrator tabs.
   **Use SQLite for local testing** and **Configure receipt storage later** are
   selected by default. Secrets are masked, PostgreSQL credentials are URL-encoded, and
   a cryptographically random JWT secret is generated automatically. The wizard
   creates `.env` only if it does not already exist. It does not test credentials;
   actual connection/migration validation happens when the application starts.
4. The app starts on localhost port 8010. Its normal bootstrap runs migrations,
   creates the first admin and default categories, and initializes receipt storage.
   The launcher opens your browser once the health endpoint reports the database
   ready. Storage can be degraded; receipts remain unavailable until MinIO works.
5. Sign in and change your password in Settings. Test an expense and receipt.
   The tray icon can reopen the browser or exit the local app. Closing the browser
   does not stop the server. Logging off stops this desktop launch; use NSSM for
   unattended server operation.

The **Configure F&M Finance** Start Menu entry opens the same configuration tool.
If `.env` exists it is preserved; close the app/stop the service and edit `.env`
for subsequent connection changes. Changing ADMIN_INITIAL_PASSWORD does not reset
an existing account. The wizard initially binds only to `127.0.0.1`; for shared
network use follow the HTTPS section below. Normal launches use the configured
APP_PORT (default 8010) and open a local HTTP URL; HTTPS proxy deployments should
use their HTTPS URL directly in the browser.

### Updates and removal

Close the app using its tray icon before installing an update. If using NSSM,
stop the service first, back up the database, run the installer against the same
installation folder, then restart the service. Keep the same Windows account
for this per-user installer. `.env`, `data/`, database files and logs are excluded from the payload and
are preserved. Migrations still run on application start.

Uninstall via Windows Installed Apps or the Start Menu entry. For NSSM deployments,
run `uninstall_service.bat` as administrator first. Uninstall does not remove an
NSSM service automatically. It removes installed program files and shortcuts;
`.env`, SQLite data, logs, PostgreSQL data and MinIO receipts remain. Delete retained configuration
separately only when you intend to remove it. Stop/remove the NSSM service before
unattended uninstall as well.

### Validation status

Verified on Linux with the release code: **41 backend tests pass, 1 real PostgreSQL
transfer integration test skipped**. This includes the original 31 API tests. The
strict TypeScript/Vite frontend build passes. Real-server startup/login/expense/
report/deep-link/restart-persistence checks pass. A Linux PyInstaller bundle was
built and run from an unrelated working directory; executable-adjacent .env,
SQLite migration/admin/category initialization, authentication and SPA serving pass.
Tests use simulated receipt storage; actual MinIO service integration was not
rerun for this release. The real SQLite-to-PostgreSQL integration test is included
but is skipped unless a disposable PostgreSQL destination is supplied.

Windows batch execution, PowerShell GUI/tray behavior, Inno Setup compilation,
the Windows PyInstaller executable, and install/upgrade/uninstall flow have not
been executed here. The original PostgreSQL suite and real destination transfer
must still be run against PostgreSQL before production migration. PostgreSQL
migration SQL is generated offline and checked for native NUMERIC and JSONB.

## Build the .exe (Windows)

From the project folder:

```bat
packaging\build.bat
```

Output: `dist\FMExpenseTracker\FMExpenseTracker.exe`, plus `.env.example` and the two service scripts in the same folder.

## First run

1. In `dist\FMExpenseTracker\`, copy `.env.example` to `.env` and fill in every `CHANGE_ME` value. Generate `JWT_SECRET` with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
2. Double-click `FMExpenseTracker.exe` (or run it from a command prompt to watch the log).
3. Open `http://localhost:8010` and sign in with `ADMIN_EMAIL` / `ADMIN_INITIAL_PASSWORD`.
4. Go to **Settings** and change your password.

If something is wrong (database unreachable, missing secret), the app stops with a plain-English message. Logs are in the `logs` folder next to the .exe.

## Install as a Windows service

1. Copy the whole `dist\FMExpenseTracker` folder to the server, e.g. `C:\Program Files\FM Finance\`.
2. Make sure `.env` is in that folder and `nssm.exe` is on PATH or in the same folder.
3. Right-click `install_service.bat` → **Run as administrator**.

The service starts automatically (delayed, so PostgreSQL and MinIO come up first) and restarts if it crashes. Remove it with `uninstall_service.bat`.

### Network access and HTTPS

With `APP_HOST=0.0.0.0` other computers can reach the app on port 8010 (open it in Windows Firewall). Over plain HTTP the login cookie travels unencrypted on the network, so for anything beyond your own machine put it behind HTTPS (IIS with URL Rewrite/ARR, or Caddy) and set `COOKIE_SECURE=true`. If you only use it on the server itself, set `APP_HOST=127.0.0.1`.

## Updating to a new version

1. Stop the service: `nssm stop FMExpenseTracker`
2. Back up PostgreSQL with `pg_dump`, or stop the SQLite app and copy its entire `data/` folder.
3. Replace everything in the install folder **except** `.env`, `data\` (including any SQLite sidecar files), and `logs\`.
4. Start the service: `nssm start FMExpenseTracker`

Database migrations run automatically on start.

---

## Development

```bat
rem Backend (from the project root, with .env in the project root and APP_ENV=development)
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
cd backend
..\.venv\Scripts\python.exe run.py

rem Frontend, in a second window (proxies /api to http://localhost:8010)
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. API docs are at `http://localhost:8010/api/docs` when `APP_ENV=development`.

### Tests

Explicitly select a **disposable database**; the tests erase its contents.
There is no default test database. Install backend/requirements-dev.txt first.
From the backend folder, for SQLite:

```bat
set TEST_DATABASE_URL=sqlite:///data/fm_finance_test.db
..\.venv\Scripts\python.exe -m pytest -q
```

For the original PostgreSQL suite, use a separate disposable PostgreSQL database:

```bat
set TEST_DATABASE_URL=postgresql+psycopg2://fm_user:password@localhost:5432/fm_finance_test
..\.venv\Scripts\python.exe -m pytest -q
```

To test the actual transfer, keep TEST_DATABASE_URL on SQLite and additionally set
POSTGRES_TRANSFER_TEST_URL to a **second disposable PostgreSQL database** before
running pytest. The transfer integration test resets that destination's public
schema; never use a real business database for either test variable.

### Database changes

`0001_initial.py` is unchanged and remains the PostgreSQL baseline. The independent
`0002_sqlite_initial.py` branch creates the SQLite schema with integer-cent money
columns. `0003_postgresql_branch.py` labels the existing PostgreSQL lineage without
changing tables. Startup selects `sqlite@head` or `postgresql@head` automatically.

Add a new migration on the appropriate branch. Do not run `upgrade heads` (it would
apply both schemas) or unqualified `upgrade head` (ambiguous). Future changes that
affect both databases need a migration in each branch. Example from backend/:

```bat
..\.venv\Scripts\alembic.exe revision --head sqlite@head -m "SQLite change"
..\.venv\Scripts\alembic.exe revision --head postgresql@head -m "PostgreSQL change"
```

---

## Project layout

```
backend/
  app/
    main.py          FastAPI app, security headers, SPA serving
    bootstrap.py     Startup: logging, config check, migrations, admin user, categories, storage
    config.py        Settings from .env (next to the .exe)
    paths.py         Dev vs. PyInstaller path handling
    models.py        SQLAlchemy models
    types.py         Exact money and UTC timestamp compatibility
    transfer.py      SQLite-to-PostgreSQL data transfer
    schemas.py       Request/response models (money serialized as numbers)
    security.py      Argon2, JWT cookie, roles, login throttling
    storage.py       MinIO client
    audit.py         Audit log helper
    routers/         auth, expenses, receipts, categories, vendors, reports, meta (health/settings)
  alembic/           SQLite and PostgreSQL migration branches
  tests/             pytest suite
  run.py             Entry point
frontend/src/        React app (pages, components, api client)
packaging/           PyInstaller spec, build.bat, service scripts
```

## Manual test checklist

1. `packaging\build.bat` finishes with "Build complete".
2. Fill in `.env` in the dist folder, start the .exe, sign in.
3. Add an expense with a receipt, open the receipt, mark the expense paid.
4. Refresh the browser on an expense page (`/expenses/<id>`); it loads.
5. Install as a service, reboot, confirm the app comes back.


## Portable Windows build (v0.2.4)
The portable builder uses PyInstaller 6.22.3, which supports current Python 3.14 builds. Run `packaging\build_portable.bat` on Windows. The output is `portable-output\FMFinance.exe`.
