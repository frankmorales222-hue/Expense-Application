# F&M Finance v0.2.2 handoff

Use this complete project as the working baseline. Preserve the existing structure,
UI, FastAPI/SQLAlchemy/Alembic/React/TypeScript/Vite stack, PostgreSQL support,
MinIO private receipt storage and Windows PyInstaller/NSSM/Inno Setup packaging.
Do not return to the v0.1 prototype or add frameworks/runtime dependencies.

This version adds SQLite for local testing. SQLite is the default for new installs;
PostgreSQL remains selectable. SQLite uses integer cents with Decimal application
values, JSON audit payloads and UTC timestamps. PostgreSQL keeps NUMERIC and JSONB.
`0001_initial.py` is immutable. SQLite and PostgreSQL have independent Alembic
branches; use sqlite@head or postgresql@head. Never use Base.metadata.create_all.
Any future schema change needs new migrations on the affected branch(es).

Local source testing: packaging\run_local.bat. A prebuilt frontend is included.
Windows installer build: packaging\build_installer.bat. First-run configuration
allows SQLite without a database installation and receipt storage configured later.
No credentials means receipts are unavailable, while expense workflows still run.
With MinIO configured, receipts remain streamed through authenticated app routes.

Read README.md for setup, test databases and the one-time --migrate-to-postgresql
command. That command refuses populated destination databases, preserves IDs and
records, verifies counts/money totals, writes a transfer audit entry and retains
the SQLite source. Receipt files stay in MinIO; only metadata is transferred.

Verified here on Linux: 41 backend tests passed; one real PostgreSQL destination
integration test skipped; strict TypeScript/Vite build passed; real-server startup,
authentication, expenses, reports, deep links and restart persistence passed;
Linux PyInstaller packaging and executable-adjacent configuration/migrations passed.
Windows installer/PowerShell/NSSM behavior has NOT been run here. The original
PostgreSQL suite and actual SQLite-to-PostgreSQL transfer still need real PostgreSQL
validation before production use. The source ZIP is not a compiled Windows EXE.

For every change: list files and purposes before editing; preserve Decimal and the
Money JSON-number serializer; keep calendar date strings unchanged; audit mutations
in their database transaction; require current_user/require_roles on API endpoints
except health/login; preserve Argon2, httpOnly cookies, login throttling, upload
signature/safe-name checks, CSV escaping and security headers; keep receipts private.
The existing logout route is a known baseline exception to the login rule; do not
silently claim it is secured or weaken any other endpoint. Add/update backend tests,
keep frontend builds passing, bump backend/frontend release versions and matching
packaging/lockfile versions, and update README for changed behavior/setup.
Deliver complete changed files or the full project ZIP; identify checks not run.
