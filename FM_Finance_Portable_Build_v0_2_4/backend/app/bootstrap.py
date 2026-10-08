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
from .models import ExpenseCategory, User
from .paths import alembic_dir, app_dir, is_frozen
from .security import hash_password
from .storage import StorageUnavailable, get_storage

log = logging.getLogger("fm_finance")

DEFAULT_CATEGORIES: list[tuple[str, str]] = [
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
                password_hash=hash_password(password), role="admin"))
    db.commit()
    log.info("Created admin user %s. Change the password after first login.", settings.ADMIN_EMAIL)


def seed_categories(db: Session) -> None:
    if db.scalar(select(func.count(ExpenseCategory.id))):
        return
    for i, (code, name) in enumerate(DEFAULT_CATEGORIES):
        db.add(ExpenseCategory(code=code, name=name, sort_order=(i + 1) * 10))
    db.commit()
    log.info("Seeded %d expense categories", len(DEFAULT_CATEGORIES))


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
        seed_categories(db)
    ensure_storage()
    return settings
