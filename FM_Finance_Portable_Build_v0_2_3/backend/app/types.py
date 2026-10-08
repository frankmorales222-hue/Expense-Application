"""Portable database types; PostgreSQL keeps its original native types."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Numeric
from sqlalchemy.types import TypeDecorator


class CurrencyAmount(TypeDecorator):
    """Decimal in Python, NUMERIC(12,2) on PostgreSQL, integer cents on SQLite."""

    impl = Numeric(12, 2)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(BigInteger() if dialect.name == "sqlite" else Numeric(12, 2))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        amount = Decimal(str(value))
        if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
            raise ValueError("Money must be finite and have at most two decimal places")
        return int(amount * 100) if dialect.name == "sqlite" else amount

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        amount = Decimal(str(value))
        if dialect.name == "sqlite":
            amount /= 100
        return amount.quantize(Decimal("0.01"))


class UTCDateTime(TypeDecorator):
    """SQLite stores UTC without an offset; restore that offset on retrieval."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        utc = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return utc.replace(tzinfo=None) if dialect.name == "sqlite" else utc

    def process_result_value(self, value: datetime | None, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
