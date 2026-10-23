"""FastAPI application factory: API routers, error handling, and the React SPA."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import get_settings
from .paths import frontend_dist
from .routers import (
    accountant, accounts, auth, backups, bank_rules, bills, categories, companies, company, customers, dashboard, documents, roles, rules, expenses, imports, members, meta,
    invoices, items, ledger, mail, owner_funds, payments, plans, receipts, reconciliations, reports, resellers, sales, transactions, vendors, updates,
)
from .ledger import books as _books  # noqa: F401  (registers automatic posting)
from .ledger.posting import ClosedPeriod, Unbalanced
from .storage import StorageUnavailable


def create_app() -> FastAPI:
    dev = get_settings().is_dev
    app = FastAPI(
        title="F&M Finance",
        version=__version__,
        docs_url="/api/docs" if dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if dev else None,
    )

    @app.exception_handler(StorageUnavailable)
    async def storage_unavailable(_: Request, exc: StorageUnavailable) -> JSONResponse:
        return JSONResponse({"detail": "Receipt storage is currently unavailable. Try again later."}, status_code=503)

    @app.exception_handler(ClosedPeriod)
    async def closed_period(_: Request, exc: ClosedPeriod) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(Unbalanced)
    async def unbalanced(_: Request, exc: Unbalanced) -> JSONResponse:
        return JSONResponse({"detail": "This change would leave the books out of balance, so it wasn't saved."},
                            status_code=422)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    for module in (meta, auth, categories, vendors, expenses, receipts, reports, company, accounts, customers,
                   imports, transactions, documents, companies, members, resellers, bills, ledger, items, invoices,
                   payments, sales, mail, plans, dashboard, rules, bank_rules, roles, owner_funds, reconciliations,
                   accountant, updates, backups):
        app.include_router(module.router)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    dist = frontend_dist()
    index = dist / "index.html"
    if not index.exists():
        @app.get("/", include_in_schema=False)
        def no_frontend() -> JSONResponse:
            return JSONResponse({"detail": "Frontend not built. Run 'npm run build' in frontend/."}, status_code=503)
        return

    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    dist_root = dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        # Unknown API paths must 404 instead of returning the SPA shell.
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(404, "Not found")
        if full_path:
            candidate = (dist_root / full_path).resolve()
            if candidate.is_file() and dist_root in candidate.parents:
                return FileResponse(candidate)
        # SPA fallback so a browser refresh on /expenses/<id> works.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
