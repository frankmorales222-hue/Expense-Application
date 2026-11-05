"""Startup sequence: logging, settings validation, migrations, admin user, seed data, storage."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.engine import make_url

from . import __version__
from .config import PLACEHOLDER, Settings, get_settings
from .database import get_session_factory
from .models import Company, CompanyMember, ExpenseCategory, User
from .paths import alembic_dir, app_dir, is_frozen
from .security import hash_password
from .storage import StorageUnavailable, get_storage

log = logging.getLogger("fm_finance")

DEFAULT_CATEGORIES: list[tuple[str, str]] = [  # expense categories
    ("software_licenses", "Software & Licenses"),
    ("cloud_hosting", "Cloud & Hosting"),
    ("hardware_equipment", "Hardware & Equipment"),
    ("internet_phone", "Internet & Phone"),
    ("office_supplies", "Office Supplies"),
    ("marketing_advertising", "Marketing & Advertising"),
    ("professional_services", "Professional Services (legal, accounting)"),
    ("contractor_fees", "Contractor Fees"),
    ("travel", "Travel"),
    ("meals", "Meals"),
    ("training_certifications", "Training & Certifications"),
    ("insurance", "Insurance"),
    ("bank_payment_fees", "Bank & Payment Fees"),
    ("taxes_licenses", "Taxes & Licenses"),
    ("other", "Other"),
]
# Added in v0.3.0 so deposits and owner money have somewhere to go.
EXTRA_CATEGORIES: list[tuple[str, str, str]] = [
    ("client_services_revenue", "Client services revenue", "income"),
    ("consulting_income", "Consulting income", "income"),
    ("interest_income", "Interest income", "income"),
    ("other_income", "Other income", "income"),
    ("owner_contribution", "Owner contribution", "equity"),
    ("owner_draw", "Owner draw", "equity"),
]


class StartupError(Exception):
    pass


def configure_logging(settings: Settings) -> None:
    log_dir = settings.log_path
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    file_handler = RotatingFileHandler(log_dir / "fm_finance.log", maxBytes=10 * 1024 * 1024,
                                       backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(file_handler)
    root.addHandler(console)
    # Keep library noise down; never log SQL parameters (they can contain personal data).
    for noisy in ("botocore", "boto3", "urllib3", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def run_migrations(url: str | None = None) -> None:
    value = url or get_settings().DATABASE_URL
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir()))
    cfg.attributes["database_url"] = value
    branch = "sqlite" if make_url(value).get_backend_name() == "sqlite" else "postgresql"
    command.upgrade(cfg, f"{branch}@head")


def ensure_admin(db: Session, settings: Settings) -> None:
    if db.scalar(select(func.count(User.id))):
        return
    password = settings.ADMIN_INITIAL_PASSWORD
    if not password or PLACEHOLDER in password or len(password) < 10:
        raise StartupError(
            "No users exist yet. Set ADMIN_INITIAL_PASSWORD in .env (10+ characters) to create the admin account."
        )
    db.add(User(email=settings.ADMIN_EMAIL.strip().lower(), name=settings.ADMIN_NAME,
                password_hash=hash_password(password), role="admin", is_platform_admin=True))
    db.commit()
    log.info("Created admin user %s. Change the password after first login.", settings.ADMIN_EMAIL)


def seed_company_categories(db: Session, company_id) -> int:
    """Give a company the default categories it is missing. Caller commits."""
    scoped = (ExpenseCategory.company_id == company_id,)
    added = 0
    if not db.scalar(select(func.count(ExpenseCategory.id)).where(*scoped)):
        for i, (code, name) in enumerate(DEFAULT_CATEGORIES):
            db.add(ExpenseCategory(company_id=company_id, code=code, name=name, kind="expense",
                                   sort_order=(i + 1) * 10))
            added += 1
        db.flush()
    existing = set(db.scalars(select(ExpenseCategory.code).where(*scoped)))
    top = db.scalar(select(func.max(ExpenseCategory.sort_order)).where(*scoped)) or 0
    for code, name, kind in EXTRA_CATEGORIES:
        if code not in existing:
            added += 1
            top += 10
            db.add(ExpenseCategory(company_id=company_id, code=code, name=name, kind=kind, sort_order=top))
    return added


def seed_categories(db: Session) -> None:
    for company_id in db.scalars(select(Company.id)):
        if seed_company_categories(db, company_id):
            log.info("Added default categories to company %s", company_id)
    db.commit()


def ensure_company(db: Session) -> Company:
    """A fresh install gets one company, owned by the first administrator."""
    company = db.scalar(select(Company).order_by(Company.created_at).limit(1))
    if company is None:
        company = Company(name=get_settings().COMPANY_NAME, base_currency=get_settings().CURRENCY)
        db.add(company)
        db.flush()
        log.info("Created company %s", company.name)
    if not db.scalar(select(func.count()).select_from(CompanyMember)):
        admin = db.scalar(select(User).where(User.is_platform_admin.is_(True)).order_by(User.created_at).limit(1))
        if admin is not None:
            db.add(CompanyMember(company_id=company.id, user_id=admin.id, role="owner"))
    db.commit()
    return company


def ensure_storage() -> None:
    try:
        get_storage().ensure_bucket()
        log.info("Receipt storage ready")
    except StorageUnavailable as exc:
        log.warning("Receipt storage unavailable (%s). Receipt features will return 503 until MinIO is reachable.", exc)


def startup() -> Settings:
    settings = get_settings()
    configure_logging(settings)
    log.info("F&M Finance %s starting (frozen=%s, app dir=%s)", __version__, is_frozen(), app_dir())

    errors, warnings = settings.validate_for_startup()
    for w in warnings:
        log.warning(w)
    if errors:
        for e in errors:
            log.error(e)
        raise StartupError(f"Configuration problem in {app_dir() / '.env'}: " + " ".join(errors))

    try:
        run_migrations()
    except Exception as exc:
        log.exception("Database migration failed")
        raise StartupError(f"Could not connect to or migrate the database: {exc}") from exc
    log.info("Database schema is up to date")

    with get_session_factory()() as db:
        ensure_admin(db, settings)
        ensure_company(db)
        seed_categories(db)
        from .ledger.books import ensure_books

        ensure_books(db)
    ensure_storage()
    from .updates import after_start

    after_start()
    from .data_backups import ensure_daily

    ensure_daily()
    return settings
