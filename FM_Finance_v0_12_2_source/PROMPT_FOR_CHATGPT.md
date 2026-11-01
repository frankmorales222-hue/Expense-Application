# F&M Finance v0.12.2: build handoff for ChatGPT

I'm attaching the v0.12.2 source. The application changes have been reviewed and tested. Your job is packaging
and build verification only: do not change `backend/app`, `frontend/src`, `backend/alembic` or `backend/tests`.
If something fails, show the exact error and propose the smallest packaging-only fix before applying it.

## Build

1. Use 64-bit Python 3.12 and Node.js 20 or newer.
2. In `frontend`, run `npm ci` and `npm run build`.
3. Install `backend/requirements-portable.txt` exactly as pinned, plus `pyinstaller==6.22.3`,
   `pytest==8.3.4` and `httpx==0.28.1`. Do not use `--upgrade`.
4. In `backend`, set `TEST_DATABASE_URL=sqlite:///data/fm_finance_test.db` and run `pytest -q`.
   Expected: **196 passed, 1 skipped** (the PostgreSQL transfer test).
5. Build with `packaging/fm_finance_portable.spec`. The new modules are explicitly listed as hidden imports
   and are also covered by `collect_submodules("app")`: `app.schema_confidence`,
   `app.routers.reconciliations` and `app.routers.accountant`.
6. Run `FMFinance.exe --selftest`; `selftest.txt` must start with `PASS`.
7. Start the EXE in an empty folder. It must create/use `%LOCALAPPDATA%\FM Finance`; `/api/health` must report version `0.12.2`,
   database `ok` and storage `ok`.
8. Keep the existing private update-signing key in `%USERPROFILE%\.fmfinance\update_signing_key.pem`.
   Do not replace or rotate it. `build_portable.bat` makes and verifies
   `update-output\FMFinance_Update_v0.12.2.fmupdate`; the minimum supported installed version remains 0.10.1.

Version is **0.12.2** in `backend/app/__init__.py`, `frontend/package.json`, `frontend/package-lock.json`,
`packaging/installer.iss`, `packaging/build_installer.bat` and `.github/workflows/build-windows.yml`.

## What changed

- The Windows app uses one permanent `%LOCALAPPDATA%\FM Finance` home for settings, SQLite, receipts and logs.
- On the first launch it copies existing data without deleting the old copy. If the local EXE folder is blank,
  it selects the richest valid `.fmbak` from `Documents\FM Finance Backups` rather than seeding an empty company.
- `DATA_LOCATION.txt` beside the EXE records the live location. No database migration or dependency changed.
- Closing the final F&M Finance browser tab now stops the portable local server after an eight-second grace
  period and runs the normal exit backup. Refreshing or opening another tab cancels the pending stop.
- The lifecycle signal is accepted only from the local F&M Finance origin. The existing sidebar **Exit app**
  action still stops immediately.
- There is no database migration and no dependency change in v0.12.2. Everything added in v0.12.1 and
  v0.12.0 remains.

- **Accounting > Reconcile** starts a bank or credit-card statement with its ending date and balance, shows
  approved eligible transactions, and requires the difference to reach exactly zero before completion.
- A PDF, JPG or PNG statement can be attached to each reconciliation. Completed reconciliations are permanent,
  and their transactions are locked from later banking edits, exclusion, transfer relinking or expense creation.
- **Accounting > Accountant center** shows reconciliation status and report shortcuts, plus searchable audit
  history with the person, record, action, time and change details.
- Its period ZIP export contains the general ledger, trial balance, profit and loss, balance sheet, bank
  transactions, expenses, invoices, bills, reconciliations and audit history, with available expense receipts,
  bill attachments and bank statements.
- SQLite migration `0026_sqlite_confidence` and PostgreSQL migration `0027_postgresql_confidence` add the
  reconciliations table and `transactions.reconciliation_id`. Existing transactions remain unreconciled.

## Upgrade check from v0.12.1

Use a copy of the real v0.12.1 installation data, never the original:

1. Install the v0.12.2 `.fmupdate` through Administration > Updates.
2. Confirm startup reports no migration errors; v0.12.2 adds no migration.
3. Confirm `DATA_LOCATION.txt` points to `%LOCALAPPDATA%\FM Finance`, all records and receipts are present,
   and launching a copy of the EXE from a second folder shows the same company data.
4. Sign in and confirm companies, owner funds, expenses, receipts, invoices, bills, banking, themes and rules
   are unchanged, and Settings > Books still says the books are balanced.
5. Close the only F&M Finance browser tab. The FMFinance process must stop after the grace period and the log
   must show the final-window shutdown followed by an exit backup.
6. Start it again, refresh the page and confirm the process stays running. Open a second tab, close one, and
   confirm the process stays running until the final tab closes.
7. Confirm the usual full `.fmbak` backup and restore still preserve the database, settings and receipts.

## Smoke test

- Closing the final browser tab stops the process and creates an exit backup.
- Refreshing does not stop the process; with two tabs, closing one does not stop it.
- Sidebar **Exit app** still stops immediately and a second launch still only opens the browser.
- Reconciliation, Accountant center, owner funds, backups, updates, invoices/email, bills, banking, themes,
  rules, companies and team roles still work.

Deliver `portable-output\FMFinance.exe`, `update-output\FMFinance_Update_v0.12.2.fmupdate`, the build log,
test summary, `selftest.txt` and the upgrade/reconciliation/export check results.
