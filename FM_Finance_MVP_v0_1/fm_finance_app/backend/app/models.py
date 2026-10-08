from sqlalchemy import String, Integer, Numeric, Date, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from decimal import Decimal
from .database import Base

class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    accounts = relationship("Account", back_populates="company", cascade="all, delete-orphan")

class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    institution: Mapped[str] = mapped_column(String(120), default="Manual")
    account_type: Mapped[str] = mapped_column(String(40), default="checking")
    last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(14,2), default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    company = relationship("Company", back_populates="accounts")
    transactions = relationship("Transaction", back_populates="account", cascade="all, delete-orphan")

class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="expense")
    tax_deductible_default: Mapped[bool] = mapped_column(Boolean, default=False)

class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)

class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"), nullable=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    tx_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    description: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(14,2))
    tx_type: Mapped[str] = mapped_column(String(20), default="expense")
    status: Mapped[str] = mapped_column(String(20), default="review")
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receipt_attached: Mapped[bool] = mapped_column(Boolean, default=False)
    tax_deductible: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    account = relationship("Account", back_populates="transactions")
    vendor = relationship("Vendor")
    category = relationship("Category")

class Rule(Base):
    __tablename__ = "rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    merchant_contains: Mapped[str] = mapped_column(String(120))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    category = relationship("Category")

class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    vendor_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    total: Mapped[Decimal | None] = mapped_column(Numeric(14,2), nullable=True)
    receipt_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
