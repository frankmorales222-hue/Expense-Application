# F&M Finance (v0.12.0)

## What's new in v0.12.0: bookkeeping confidence

**Accounting › Reconcile** now matches an approved bank or credit-card transaction to a real statement.
Choose the statement date and ending balance, tick the cleared transactions, and finish only when the
difference is exactly zero. A PDF or image of the statement can be attached. Completed transactions are
locked against later banking changes, leaving a permanent record of who reconciled the account and when.

**Accounting › Accountant center** puts tax-season handoff in one place. It shows reconciliation status,
financial-report shortcuts and searchable audit history. A period export downloads one ZIP containing the
general ledger, trial balance, profit and loss, balance sheet, bank transactions, expenses, invoices, bills,
reconciliations and audit history, plus available receipts, bill documents and bank statements.

- Searchable audit history identifies the person, record, action, time and captured change details.
- Migrations 0026 (SQLite) / 0027 (PostgreSQL) add reconciliations and connect transactions to their statement.
- API: `/api/reconciliations`, `/api/audit`, and `/api/accountant/export`.

---

# F&M Finance (v0.11.0 notes)

## What's new in v0.11.0: owner money and full backups

Owner loans no longer require someone to improvise a journal entry. **Accounting › Owner funds** shows one
clear total split between loans and personally paid expenses, and records money put into or paid back by the
company. A matching bank transaction can be selected so one payment is recorded only once. Opening cash that
was funded by the owner can also be reclassified without changing the bank balance. The dashboard now shows
**Owed to owner**, and the activity remains available in the general ledger for the accountant.

**Administration › Backups** creates and restores one full `.fmbak` file containing the SQLite database,
`.env` settings and all local receipts. Backups default to `Documents\FM Finance Backups`, outside the EXE
folder, so replacing or moving the program cannot strand the data. The desktop app also takes automatic
startup and exit backups. Before any restore it creates a fresh recovery backup; if the restored copy does not
start and pass its health check, the helper puts the current data back automatically.

- Bank transactions may now post directly to a balance-sheet account. Owner-loan deposits and repayments are
  therefore neither income nor expenses and do not change profit.
- Migration 0024 (SQLite) / 0025 (PostgreSQL) adds the optional balance-sheet allocation to bank transactions.
- API: GET/POST `/api/owner-funds`; GET/POST `/api/backups`; POST `/api/backups/{name}/restore`.

---

# F&M Finance (v0.10.1 notes)

## What's new in v0.10.1: updates from inside the app

No more new EXE files on every release. From this version on, a new version arrives as one signed update
file, FMFinance_Update_v<version>.fmupdate, installed from **Administration › Updates**:

1. Choose the file. The app checks that it's signed by F&M IT Services (a private key on the build PC; the app
   only has the public half), that the program inside is complete and unchanged, and that it isn't older than
   what's installed. Anything else is refused before a single file changes.
2. **Install and restart**: the database (a consistent copy, even while running) and .env are backed up to
   backups\before-v<version>-<date> (the last 5 are kept). The app closes and a small helper puts the new
   program in place of the old one, with the same name and in the same folder, so shortcuts keep working.
   The old program is kept as FMFinance.previous.exe.
3. The helper starts the new version and waits for it to answer. If it doesn't within about two minutes, the
   helper puts the previous program and the database backup back and starts the old version. The Updates
   page says what happened; details are in updates\update.log.

- Only the installation's administrator (platform admin) sees Updates. Available in the portable Windows app
  (DESKTOP_MODE=true). A server/service install is still updated with its installer.
- Reinstalling the same version (to repair a copy) is allowed; going back to an older version isn't (the
  database may already be newer).
- Build side: `packaging\make_update.py keygen` once (creates the signing key in
  %USERPROFILE%\.fmfinance, writes the public key into backend\app\update_key.py); build_portable.bat then
  makes the EXE and the signed update file each time.
- API: GET /api/updates, POST /api/updates/upload, DELETE /api/updates/staged, POST /api/updates/apply,
  GET /api/health/version (one plain line for the helper).
- No database changes in this version.

Validated: 181 tests on SQLite and 179 on PostgreSQL 16 pass.

---

# F&M Finance (v0.10.0 notes)

## What's new in v0.10.0: every company works its own way

Nothing about how a company does business is fixed in the code anymore. Each company sets its own rules in
**Settings › Company rules** (owners change them; everyone else can see them). Other companies keep theirs.

- **Money and dates**: currency, the symbol shown, number style (1,234.56 / 1.234,56 / 1 234,56 / 1'234.56)
  and date order. Used on every screen, report, invoice PDF and email.
- **Approvals**: whether expenses need approval and from what amount, per company (this used to be one
  APPROVAL_REQUIRED switch in .env for the whole installation; .env now only sets the starting default).
  Category thresholds still work.
- **Payment terms**: add your own (Net 10, end of month + 5, the 10th of next month...), rename or turn off
  the built-in ones, and pick the default for new invoices and bills. Due dates follow the term.
- **Payment methods**: your own lists for paying expenses (e.g. Amex Business Gold) and for receiving
  payments (e.g. Zelle). The database no longer restricts expense payment methods to a fixed list.
- **Custom fields** on customers, products and services, invoices, bills and expenses: text, number, date,
  list of choices or yes/no; optional or required. Invoice and customer fields can print on the PDF
  (e.g. PO number, VAT ID, region).
- **Invoices and email**: number prefix and next number (FMIT-5000), PDF accent color, every word printed
  on the invoice (FACTURA, TAX INVOICE, CLIENTE...), and the invoice email subject and message with
  placeholders such as {customer}, {invoice_number}, {total}, {due_date}.
- **Banking and dashboard**: how sure "Approve all" must be, the cash forecast period and the "Coming up"
  period.
- **Bank rules** (Banking › Bank rules): "when the description contains ADP and money goes out, put it in
  Payroll, payee ADP, and approve it". Your rules run before the app's own suggestions, on every import
  and new transaction; "Run on waiting" applies a new rule to what's already in review.
- **Your company's roles** (Team): start from a built-in role and take areas away (banking, sales,
  expenses, bills, reports, accounting, settings, team), e.g. a Front desk role that sends invoices but never
  sees the bank. A role can only narrow access, never widen it. The server enforces it and the menu follows.
- **Plans are data** (Administration › Plans and modules): the platform owner and each reseller can create
  and edit plans (name, modules, users, price, offered or not), optionally updating companies already on
  the plan. Resellers' plans are their own.
- Codes in use can be turned off but not deleted, so old records always read correctly.
- **Security**: react-router-dom 6.30.6, and the after-sign-in return address only accepts pages inside the app.
- **API**: GET/PUT /api/rules; /api/bank-rules (+ POST /apply); /api/roles (+ /areas);
  POST /api/plans/catalog and PUT /api/plans/catalog/{id}?apply_to_companies=.
- **Upgrade**: migrations 0022 (SQLite) / 0023 (PostgreSQL) add companies.rules, a custom column on five
  tables, the plans table (seeded with Starter, Essentials, Plus, Advanced), company_roles, bank_rules,
  and remove the fixed list of expense payment methods. Existing companies keep working exactly as before
  until they change a rule.

Validated: 164 tests on SQLite and 162 on PostgreSQL 16 pass, plus the self-test and an upgrade of a
v0.9.0 database (record counts and ledger totals unchanged, foreign keys and integrity check clean).

---

# F&M Finance (v0.9.0 notes)

## What's new in v0.9.0: a new look, in three themes

- **Three looks, chosen per person** in Settings › Appearance; the choice follows the login to every company:
  - **Classic** (default): clean and bright, navy with green for paid and red for overdue (Lexend + Source Sans 3).
  - **Executive**: navy menu with gold accents, like a private bank (IBM Plex Sans).
  - **Dark**: dark and compact for long sessions, amounts in a fixed-width font (Fira Sans + Fira Code).
  Fonts are bundled, so the desktop app looks right offline.
- **Default look per company**: Administration › Plans and modules has a "Default look" column. The platform
  owner sets it for any company, a reseller admin for their own clients. People who haven't picked their
  own see the company's default.
- **New dashboard** for owners, accountants and bookkeepers:
  - Key numbers: cash in the bank (change this month), profit this year (vs the same dates last year),
    what customers owe (late amount) and what you owe vendors (due in 14 days).
  - Account balances (bank, savings, credit card).
  - **Cash forecast**: actual cash for the last 30 days and the expected balance for the next 30, from open
    invoices and unpaid bills on their due dates, with the lowest point marked. Late invoices aren't
    counted; bills already past due are counted tomorrow.
  - **Coming up**: late invoices and bills first, then everything due in the next 14 days.
  - Income and expenses for 12 months with the profit for each month; invoice status (paid, open, late).
  - **New from the bank**: transactions waiting for review, with the suggestion and an Approve button.
  - **This month so far** compared with last month, by expense account.
  Employees and view-only people keep the expense dashboard.
- **Same look everywhere**: sidebar with icons, buttons, tables, forms, badges and charts follow the theme;
  readable contrast in all three; works down to phone width.
- **Keyboard shortcuts in Banking › For review**: J/K or arrows to move, A to approve, E (or Enter) to open
  details, X to exclude, Esc to close.
- **API**: GET /api/dashboard/overview, PUT /api/auth/me/theme, PUT /api/plans/companies/{id}/theme.
- **Upgrade**: migrations 0020 (SQLite) / 0021 (PostgreSQL) add users.theme and companies.default_theme.
  Everyone starts on Classic.

Validated: 143 tests on SQLite and 141 on PostgreSQL 16 pass, plus the self-test and an upgrade of a
v0.8.0 database (books still balance; every company opens the new dashboard).

---

# F&M Finance (v0.8.0 notes)

## What's new in v0.8.0: plans and modules you can sell

- **Modules**: Invoicing, Bills, Smart capture and Advanced accounting can be switched on per company.
  **Core** is in every plan: dashboard, expenses, accounts and banking, chart of accounts, profit and
  loss, balance sheet, closing date, history, export and settings.
- **Plans**: Starter (Invoicing, 1 user), Essentials (Invoicing, Bills, Smart capture, 3 users), Plus (all
  modules, 5 users), Advanced (all modules, 25 users). Any company can be adjusted by hand (Custom).
- **Plans and modules** page (Administration): the platform owner manages every company; a reseller
  admin manages their own clients. It shows names and plans only, never a company's books. The plan
  is also chosen when adding a company.
- **Turned off = read-only**: a module that's off keeps its records viewable, printable and exportable;
  nothing new can be created or changed (the server enforces it, not just the menu). Nothing is deleted
  and the books keep working. Turning the module back on restores everything.
- **The Accountant always has the accounting tools** (journal entries, trial balance) in every plan and
  doesn't count as a user. The platform owner doesn't take a seat either.
- **User limits** per plan, shown on the Team page and in Settings › Your plan.
- **Settings › Your plan** shows the client what's included (read-only).
- **Single-company users** see their company name without a company menu.
- **Microsoft 365 single-tenant apps**: each company can use an app registration in its own Microsoft 365
  (Application ID + Directory (tenant) ID), saved only in that company's settings.
- **Upgrade**: existing companies keep every module with no user limit until you choose a plan.

Validated: 137 tests on SQLite and 135 on PostgreSQL 16 pass, plus the transfer test and an upgrade of
a v0.7.1 database. The tests cover read-only modules, the Accountant exemption, user limits, who can
manage plans, reseller limits and single-tenant Microsoft sign-in.

---

# F&M Finance (v0.7.1 notes)

## v0.7.1: email invoices through Microsoft 365 with MFA

Microsoft 365 accounts with MFA (and tenants with security defaults) block apps that send mail with a
username and password over SMTP, and Microsoft is turning that off for every tenant (disabled by default
from late December 2026). v0.7.1 adds **Connect Microsoft 365** in Settings › Email:

- You sign in on Microsoft's own page (microsoft.com/devicelogin) with your password and MFA. F&M Finance
  never sees the password; it keeps only a sign-in token, encrypted.
- Invoices are sent through Microsoft Graph from your mailbox and saved in its Sent Items.
- Clear messages for the usual problems (app not found, public client flows off, admin consent needed,
  sign-in expired after a password change, mailbox without a license).
- Disconnect / Reconnect; reply-to and "send me a copy" still work. Gmail (app password) and other SMTP
  servers work as before.

One-time setup (a Microsoft 365 admin, about 5 minutes; the steps are also shown in Settings › Email):
1. entra.microsoft.com › Applications › App registrations › New registration. Name "F&M Finance";
   account types "Accounts in this organizational directory only" (single tenant, one app per company;
   v0.8.0) or multitenant; no redirect URI.
2. Authentication › Allow public client flows: Yes.
3. API permissions › Microsoft Graph › Delegated: Mail.Send and offline_access (User.Read is there
   already) › Grant admin consent.
4. Copy the Application (client) ID into Settings › Email (or into .env as MS_CLIENT_ID for every
   company) and click Connect Microsoft 365.

No client secret is needed. One registration serves every company; client companies on other
Microsoft 365 tenants may need their own admin to consent the first time.

Validated: 129 tests on SQLite and 127 on PostgreSQL 16 pass (Microsoft's sign-in and Graph are
simulated in the tests), plus the transfer test, an upgrade of a v0.7.0 database, and a live run of the
connect flow and invoice sending.

---

# F&M Finance (v0.7.0 notes)

## What's new in v0.7.0: invoices, PDF and email, getting paid

- **Invoices** (Sales › Invoices; owners, accountants and bookkeepers): customer, email, invoice number
  (numbered automatically from 1001, or continue your own like INV-0042), invoice date, terms and due
  date, lines with service date, product/service, description, quantity × rate, a message to the
  customer and an internal memo. Statuses: Not sent, Sent, Partly paid, Paid, Overdue (with days late)
  and Void. Each invoice goes to Accounts Receivable and income in the books automatically.
- **Invoice PDF** with your logo, company address, phone, email, website and payment instructions
  (Settings › Company › On your invoices). Preview, download or print it. Paid and void invoices are
  stamped.
- **Email invoices** from your own mailbox with the PDF attached (Settings › Email: Microsoft 365,
  Gmail / Google Workspace or any SMTP server). The email is pre-written and editable; customer Cc
  addresses are added; you can Bcc yourself; every send (or failure, with the reason) is logged on the
  invoice. The mail password is stored encrypted. If email isn't set up, download the PDF, send it
  yourself and click "Mark as sent".
- **Billable expenses**: expense and bill lines marked Billable for a customer appear on that
  customer's next invoice ("Add" or "Add all"), at cost or with your markup, posted to Billable
  Expense Income. Each one can be billed once; voiding the invoice frees it again.
- **Receive payment**: one payment can cover several invoices (applied oldest first, editable). Match
  it to the bank deposit already imported in Banking, so the money is counted once and the deposit is
  approved. From Banking, a deposit has a "Receive payment" button that fills everything in.
- **Customers** page: open and overdue balance, invoices, payments, average days to pay and on-time
  percentage, unbilled expenses, billing address, Cc emails, phone and default terms.
- **Products and services**: what you sell, with a default rate, description and income category.
- **Reports**: A/R aging (current, 1–30, 31–60, 61–90, 91+) as of any date, and Sales by customer.
  The dashboard shows open, overdue and recently paid invoices.
- **Navigation** is grouped: Sales, Expenses, Accounting.
- **Upgrade**: adds the new tables and columns; existing data isn't changed. The books gain a
  "Billable Expense Income" account. Back up the data folder first.

Notes:
- Microsoft 365: SMTP AUTH has to be allowed for the sending mailbox (Microsoft 365 admin center ›
  Users › Active users › Mail › Manage email apps › Authenticated SMTP). Gmail needs an app password.
- The mail password is encrypted with a key made from JWT_SECRET in .env. If JWT_SECRET changes, enter
  the mail password again in Settings › Email.

Validated: 125 tests pass on SQLite and 123 on PostgreSQL 16, plus the SQLite-to-PostgreSQL transfer
test, including invoices and payments posting to the books, billable expenses billed once, deposit
matching without double counting, void and delete rules, the closing date, PDF content (logo, paid
stamp, accented names), email sending with a test mail server, aging and sales reports, and
two-company isolation.

---

# F&M Finance (v0.6.0 notes)

## What's new in v0.6.0: real books (double-entry accounting), split expenses and bills

- **The books.** Every company now keeps a double-entry ledger, the way QuickBooks does. You don't
  enter debits and credits yourself: expenses, bills, bill payments, approved bank transactions and
  bank opening balances are recorded for you, and kept in step when you edit or delete them.
- **Chart of accounts** (Owners, Accountants, Bookkeepers): every account with its balance, grouped as
  assets, liabilities, equity, income and expenses. Categories and bank/card accounts appear
  automatically; built-in accounts (Accounts Payable, Accounts Receivable, Reimbursements Owed,
  Opening Balance Equity, Retained Earnings, Uncategorized Income/Expense, Payment Account Not Set)
  are created for each company. Owners can add accounts such as fixed assets or loans. Click an account
  for its **register** with a running balance; click a line to open the expense, bill or entry behind it.
- **Expense form like QuickBooks**: Payee, **Payment account** (the bank or card it came out of, or
  "Paid personally"), Payment date, Payment method, Ref no., and **Category details** with several
  lines (category, description, amount, **Billable** and **Customer**), plus Memo and attachments.
  Linking an expense to a bank charge fills in the payment account.
- **Bills** (money you owe and will pay later): vendor, bill date, terms (Net 15/30/60, due on
  receipt), due date, bill no., category lines, attachments. Unpaid, overdue and paid lists with
  totals. **Pay bill** records the payment and matches it to the bank charge so it isn't counted twice.
  When you drop in a document that has a due date, the expense form offers to enter it as a bill.
- **Journal entries** for adjustments (depreciation, owner contributions, loans, corrections). They
  must balance; the "All activity" tab shows every entry the app made.
- **Reports**: Profit and loss (with date presets based on your fiscal year), Balance sheet (with
  retained earnings and this year's net income worked out) and Trial balance. Print or save as PDF.
- **Closing date** (Settings > Books, Owners): nothing dated on or before it can be added, changed or
  deleted. Settings > Books also shows whether the books are in balance and how many expenses still
  need a payment account.
- **Upgrade**: on first start, existing expenses become one-line expenses, linked expenses take their
  bank account as the payment account, and the books are built from your existing data. Approved bank
  transactions that already belong to an expense are counted once. **Back up the data folder first:**
  this migration can't be reversed automatically.

Validated: 106 tests pass on SQLite and 104 on PostgreSQL 16, plus the SQLite-to-PostgreSQL transfer
test. They include rebuilding the books from scratch matching the books kept as you go, two-company
isolation of the ledger, the closing date, bills and bill payments, and an upgrade of a v0.5.1 database
that comes out balanced.

---

# F&M Finance (v0.5.1 notes)

## v0.5.1 fix: company logo in the sidebar
- The sidebar logo now always follows the company you have open. Before, it relied on the company the
  browser had remembered, which is only saved at sign-in or when switching; a session still open from
  v0.4.1 had none, so the sidebar showed the default F&M Finance mark.
- Loading the app now also saves the remembered company when it's missing, so the sign-in page shows
  the right logo next time.
- No database changes. Validated: 89 tests pass on SQLite and 87 on PostgreSQL 16.

---

# F&M Finance (v0.5.0 notes)

## What's new in v0.5.0: multi-company foundation

- **Companies**: every record (expenses, receipts, categories, vendors, bank accounts, transactions,
  imports, customers, audit history) now belongs to one company. Each company has its own categories,
  logo, fiscal year and team. A **company switcher** sits at the top of the sidebar.
- **Isolation in two layers**: the routes check the company as before, and the database session itself
  filters every read to the current company and stamps every new record with it, so a missed check
  can't expose another company's data. A signed-in user with no company sees nothing (fails closed).
- **Roles per company** (Team page, owners only): Owner (everything), Accountant and Bookkeeper
  (banking, approving and editing all expenses; no settings or team), Employee (only their own
  expenses), View only (sees everything, changes nothing). The last owner can't be removed or demoted.
  New people get a temporary password shown once.
- **Resellers** (platform admins only): a partner such as an accounting firm. Its administrators add
  client companies and open them as owners. The platform admin can see how many clients a reseller has
  but can't open a client's books unless added to that company.
- **Companies page**: list, open and (for platform and reseller admins) add companies; each new
  company gets the default categories.
- **Sign-in page branding** follows the company this browser last worked in; a browser that has never
  signed in shows the default F&M Finance mark.
- **Upgrade**: an existing database moves into its current company automatically (all records, your
  logo, your categories and vendors). Existing users keep access: admin becomes Owner (and platform
  admin), approver becomes Bookkeeper, submitter becomes Employee. **Back up the data folder first:**
  this migration can't be reversed automatically.

Validated: 88 tests pass on SQLite and 86 on PostgreSQL 16 (3 SQLite-only skips), including two-company
isolation across every record type, roles, resellers, and an upgrade of a v0.4.1 database with real
records. SQLite to PostgreSQL transfer passes. The bill-reading self-test passes.

Known limits in this version: there's no password reset yet, so a person who forgets their password
needs an administrator's help; the sign-in page doesn't yet brand by web address (that comes with the
hosted edition).

---

# F&M Finance (v0.4.1 notes)

## What's new in v0.4.1: company logo

- **Settings > Company > Company logo**: upload a PNG, JPG or WEBP (up to 1 MB). Until one is uploaded
  the slot shows "Your logo here" and the app uses the default F&M Finance mark.
- The logo replaces the default mark in the sidebar and on the sign-in page (invoices will use it later).
- Uploads are checked and re-encoded as PNG (max 1200 x 400), so only clean pixel data is stored.
  SVG is not accepted on purpose (it can carry scripts).
- The logo belongs to the company record, so when multi-company arrives (v0.5.0) each company keeps its own.

Validated: 79 tests pass on SQLite and 77 on PostgreSQL 16; SQLite to PostgreSQL transfer passes.

---

# F&M Finance (v0.4.0 notes)

## What's new in v0.4.0: fill an expense from a bill

- **Add expense > "Fill this in from a bill"**: drop a PDF (digital or scanned), Word file (.docx),
  email (.eml or Outlook .msg, including its PDF/Word/photo attachments) or photo (JPG, PNG, WEBP).
  Vendor, date, amount, invoice number, due date, description and category fill in. Each filled field
  is marked "From bill" (confident) or "Check this". Nothing is saved until you click Save.
- **The bill becomes the receipt**: the original file is attached when you save. Receipts now also
  accept .docx, .eml, .msg and .webp (file signatures are still checked).
- **Offline first**: text is read locally; scans and photos use bundled offline OCR (RapidOCR on ONNX
  Runtime). Nothing leaves the PC unless AI reading is turned on.
- **Optional AI reading** (`AI_EXTRACTION=fallback` + `ANTHROPIC_API_KEY` in .env): used only when the
  offline read isn't confident (`always` uses it for every bill). Default model Claude Haiku 4.5.
  If the API can't be reached, the offline result is shown with a warning.
- **Matching**: known vendors are recognized (even when OCR drops spaces), the category comes from that
  vendor's past expenses, its default category, AI, or merchant keywords. A possible duplicate (same
  invoice number, or same vendor + amount within 3 days) is flagged. If one bank charge matches
  (same amount within 5 days), saving links the expense to it so Banking shows the receipt as attached.
- **New expense fields**: invoice number and due date.
- **`FMFinance.exe --selftest`** checks the bundled PDF, Word, email and OCR readers and writes
  selftest.txt next to the EXE (the GitHub build runs it).

Validated: 77 tests pass on SQLite and 75 on PostgreSQL 16 (3 SQLite-only skips); SQLite to
PostgreSQL transfer passes; Windows wheels for every pinned package were confirmed to exist for
64-bit Python 3.12. Outlook .msg reading is covered by code but not by an automated test (no sample
.msg generator). The EXE is larger in this version (OCR engine and models), roughly 150-200 MB, and
the first OCR read after starting takes a couple of extra seconds.

---

# F&M Finance (v0.3.0 notes)

## What's new in v0.3.0: Banking foundation (Phase 1)

- **Accounts** page: checking, savings, credit card and cash accounts with opening and running balances.
- **Import statement**: CSV (columns guessed and remembered per account and file layout; separate
  debit/credit columns; credit card files with positive purchases), OFX/QFX/QBO (uses the bank's FITID).
- **Duplicate protection**: re-importing the same or an overlapping file skips rows already there while
  keeping legitimate identical charges on the same day. Same-amount rows within 3 days from a different
  import are flagged "Possible duplicate" for you to exclude or keep.
- **Transfers**: card payments and account-to-account moves are paired automatically (opposite amounts
  within 4 days, higher confidence when the description says payment/transfer). Approving one side
  approves both; transfers need no category.
- **Suggestions**: vendor and category suggestions with a confidence score from (1) what you approved
  before for the same merchant, (2) the vendor's default category, (3) built-in merchant keywords.
  Approving teaches the app: matching transactions in review update immediately.
- **Banking screen**: account tiles, For review / Approved / Excluded tabs, filters, bulk approve,
  "Approve all 90%+", row detail with vendor, customer, memo, transfer linking, duplicate handling and
  "Add receipt" (creates a linked expense to attach the receipt to).
- **Undo import** (blocked while any of its transactions are approved).
- **Income and owner money**: categories now have a type (expense, income, owner/equity) and optional
  tax line. Six income/equity categories are added automatically. **Customers** (Settings) can be
  tagged on deposits for income by client. Vendors can be flagged for 1099.
- **Fixes**: local-folder receipt storage when MinIO isn't configured; startup errors shown in a message
  box (windowed EXE); second launch just opens the browser; "Exit app" in the sidebar (DESKTOP_MODE);
  password change signs out other sessions and deletes INITIAL_LOGIN.txt / clears
  ADMIN_INITIAL_PASSWORD (packaged app only); receipt record deleted before its file; default
  APP_HOST is 127.0.0.1; exact dependency pins (builds no longer use --upgrade).
- **One schema, two databases**: Phase 1 DDL lives in `backend/app/schema_phase1.py` and is called by
  both `0004_sqlite_phase1` and `0005_postgresql_phase1`. Existing v0.2.x SQLite files upgrade in place.

Validated: 60 tests pass on SQLite, 58 pass on PostgreSQL 16 (3 SQLite-only skips), and the real
SQLite to PostgreSQL transfer test passes with banking data including linked transfer pairs. Frontend
strict TypeScript build passes. Windows packaging was not run here.

Not in this phase (by design): rules screen, auto-approve, OCR, double-entry ledger, reports from bank
data, Plaid. The Dashboard still reports from Expenses only.

---

# F&M Finance — Expense Tracker (v0.2.2 notes below)

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

## Portable build note (v0.2.5)
The portable Windows build uses `backend/requirements-portable.txt`, which intentionally excludes PostgreSQL/psycopg2. This prevents `pg_config` build failures and keeps the portable EXE SQLite-only. The portable requirements also allow Python 3.14-compatible Pydantic/Argon2 versions.


## Portable build v0.2.6 compatibility fix
- Updates SQLAlchemy from 2.0.36 to 2.0.54 for Python 3.14 compatibility.
- Portable build now upgrades dependencies in the build venv before packaging.
- PostgreSQL is not required for the SQLite portable build.
