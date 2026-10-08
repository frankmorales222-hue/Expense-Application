from pydantic import BaseModel, ConfigDict
from datetime import datetime
from decimal import Decimal

class AccountCreate(BaseModel):
    company_id: int = 1
    name: str
    institution: str = "Manual"
    account_type: str = "checking"
    last4: str | None = None
    balance: Decimal = Decimal("0")

class TransactionCreate(BaseModel):
    account_id: int
    tx_date: datetime
    description: str
    amount: Decimal
    tx_type: str = "expense"
    category_id: int | None = None
    vendor_id: int | None = None
    notes: str | None = None

class TransactionUpdate(BaseModel):
    category_id: int | None = None
    vendor_id: int | None = None
    status: str | None = None
    tax_deductible: bool | None = None
    notes: str | None = None

class RuleCreate(BaseModel):
    name: str
    merchant_contains: str
    category_id: int
    auto_approve: bool = False

class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
