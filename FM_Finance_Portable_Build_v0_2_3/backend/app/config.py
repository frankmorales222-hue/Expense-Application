"""Application settings, loaded from the .env file next to the executable."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from .paths import app_dir

PLACEHOLDER = "CHANGE_ME"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(app_dir() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8010
    APP_ENV: str = "production"

    # Database
    DATABASE_URL: str = "sqlite:///data/fm_finance.db"

    # Auth
    JWT_SECRET: str = ""
    JWT_EXPIRE_HOURS: int = 12
    COOKIE_SECURE: bool = False  # set true when served over HTTPS
    ADMIN_EMAIL: str = "admin@fmitai.com"
    ADMIN_NAME: str = "Administrator"
    ADMIN_INITIAL_PASSWORD: str = ""

    # MinIO / S3
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_SECURE: bool = False
    MINIO_BUCKET: str = "expenses"
    MINIO_REGION: str = "us-east-1"
    MAX_RECEIPT_MB: int = 10

    # Business rules
    CURRENCY: str = "USD"
    APPROVAL_REQUIRED: bool = False
    DEFAULT_APPROVAL_THRESHOLD: Decimal = Decimal("500.00")

    # Logging
    LOG_DIR: str = "logs"

    @property
    def is_dev(self) -> bool:
        return self.APP_ENV.strip().lower() == "development"

    @property
    def log_path(self) -> Path:
        path = Path(self.LOG_DIR)
        return path if path.is_absolute() else app_dir() / path

    @property
    def minio_url(self) -> str:
        if self.MINIO_ENDPOINT.startswith(("http://", "https://")):
            return self.MINIO_ENDPOINT
        scheme = "https" if self.MINIO_SECURE else "http"
        return f"{scheme}://{self.MINIO_ENDPOINT}"

    def validate_for_startup(self) -> tuple[list[str], list[str]]:
        """Return (errors, warnings). Errors stop the app from starting."""
        errors: list[str] = []
        warnings: list[str] = []
        if not self.DATABASE_URL:
            errors.append("DATABASE_URL is not set.")
        if not self.JWT_SECRET or PLACEHOLDER in self.JWT_SECRET:
            errors.append("JWT_SECRET is not set. Use a long random string (40+ characters).")
        elif len(self.JWT_SECRET) < 32:
            warnings.append("JWT_SECRET is shorter than 32 characters; use a longer random value.")
        for name in ("DATABASE_URL", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"):
            if PLACEHOLDER in str(getattr(self, name)):
                warnings.append(f"{name} still contains the placeholder value '{PLACEHOLDER}'.")
        if not self.MINIO_ACCESS_KEY or not self.MINIO_SECRET_KEY:
            warnings.append("MinIO credentials are not set; receipt upload will be unavailable.")
        return errors, warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()
