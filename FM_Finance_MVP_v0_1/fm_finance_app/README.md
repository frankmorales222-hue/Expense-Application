# FM Finance MVP v0.1

A working local-first banking and expense-management application. The initial UI runs entirely from the Python backend, so **Node/npm is not required** to test V1.

## What works now
- Modern dashboard with cash, income, expenses and net cash flow
- Multiple financial accounts
- Banking review queue
- Approve imported/review transactions
- Add manual income or expense transactions
- Categories and tax-deductible defaults
- Expense tracking
- Merchant automation rules and auto-approval engine
- Receipt upload inbox
- Expense-by-category report
- Multi-company-ready database foundation
- REST API + interactive API documentation
- Demo data so the app is useful immediately after launch

## Run on Windows
Open PowerShell in the `backend` folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

Then open:

- App: http://127.0.0.1:8000
- API docs: http://127.0.0.1:8000/docs

The first launch automatically creates a local SQLite database and sample company data.

## Database
V1 uses SQLite so you can run it immediately. The backend uses SQLAlchemy and supports switching to PostgreSQL through the `DATABASE_URL` environment variable.

## Planned next build
1. Chart of Accounts
2. True double-entry journal/ledger posting service
3. P&L, Balance Sheet, Cash Flow and General Ledger
4. Bank connection abstraction + Plaid sandbox integration
5. Reconciliation workflow
6. Receipt OCR and automatic transaction matching
7. Full vendor management
8. Visual rule builder
9. Authentication and company/user permissions
10. AI financial assistant
11. Production PostgreSQL deployment

## Project structure
- `backend/app/main.py` — API and app routes
- `backend/app/models.py` — financial data model
- `backend/app/static/` — no-build frontend
- `frontend/` — React prototype retained for later UI migration
