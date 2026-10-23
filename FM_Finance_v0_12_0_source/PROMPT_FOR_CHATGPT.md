# F&M Finance v0.12.0: build handoff for ChatGPT

I'm attaching the v0.12.0 source. The application changes have been reviewed and tested. Your job is packaging
and build verification only: do not change `backend/app`, `frontend/src`, `backend/alembic` or `backend/tests`.
If something fails, show the exact error and propose the smallest packaging-only fix before applying it.

## Build

1. Use 64-bit Python 3.12 and Node.js 20 or newer.
2. In `frontend`, run `npm ci` and `npm run build`.
3. Install `backend/requirements-portable.txt` exactly as pinned, plus `pyinstaller==6.22.3`,
   `pytest==8.3.4` and `httpx==0.28.1`. Do not use `--upgrade`.
4. In `backend`, set `TEST_DATABASE_URL=sqlite:///data/fm_finance_test.db` and run `pytest -q`.
   Expected: **192 passed, 1 skipped** (the PostgreSQL transfer test).
5. Build with `packaging/fm_finance_portable.spec`. The new modules are explicitly listed as hidden imports
   and are also covered by `collect_submodules("app")`: `app.schema_confidence`,
   `app.routers.reconciliations` and `app.routers.accountant`.
6. Run `FMFinance.exe --selftest`; `selftest.txt` must start with `PASS`.
7. Start the EXE in an empty folder with a prepared `.env`. `/api/health` must report version `0.12.0`,
   database `ok` and storage `ok`.
8. Keep the existing private update-signing key in `%USERPROFILE%\.fmfinance\update_signing_key.pem`.
   Do not replace or rotate it. `build_portable.bat` makes and verifies
   `update-output\FMFinance_Update_v0.12.0.fmupdate`; the minimum supported installed version remains 0.10.1.

Version is **0.12.0** in `backend/app/__init__.py`, `frontend/package.json`, `frontend/package-lock.json`,
`packaging/installer.iss`, `packaging/build_installer.bat` and `.github/workflows/build-windows.yml`.

## What changed

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

## Upgrade check from v0.11.0

Use a copy of the real v0.11.0 installation data, never the original:

1. Install the v0.12.0 `.fmupdate` through Administration > Updates.
2. Confirm the log upgrades `0024_sqlite_owner_funds -> 0026_sqlite_confidence` with no errors.
3. Sign in and confirm companies, owner funds, expenses, receipts, invoices, bills, banking, themes and rules
   are unchanged, and Settings > Books still says the books are balanced.
4. Reconcile one copied bank account through its latest statement. The difference must reach $0.00, the attached
   statement must open, and a completed transaction must refuse later banking changes.
5. Open Accountant center, search the audit history for `reconciliation`, and download a ZIP. Confirm its CSVs,
   `documents/index.json`, the attached bank statement and available receipts open correctly.
6. Confirm the usual full `.fmbak` backup and restore still preserve the database, settings and receipts.

## Smoke test

- A statement cannot be finished while out of balance; at zero it completes and locks its transactions.
- Cancelling an in-progress reconciliation releases its selected transactions.
- The next statement begins at the previous completed ending balance.
- Bank statement upload/download works for PDF and images, including after completion.
- Audit search filters by record type, action and date, and identifies the user who made each change.
- Accountant ZIP opens offline and its financial CSV totals agree with the on-screen reports.
- Owner funds, backups, updates, invoices/email, bills, banking, themes, rules, companies, team roles and Exit
  app still work.

Deliver `portable-output\FMFinance.exe`, `update-output\FMFinance_Update_v0.12.0.fmupdate`, the build log,
test summary, `selftest.txt` and the upgrade/reconciliation/export check results.
