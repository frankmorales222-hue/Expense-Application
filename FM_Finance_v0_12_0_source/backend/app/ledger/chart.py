"""Chart of accounts: system accounts, and one ledger account per category and per bank/card account."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ExpenseCategory, FinancialAccount, LedgerAccount

# key: (name, type, detail_type, description)
SYSTEM_ACCOUNTS: dict[str, tuple[str, str, str, str]] = {
    "accounts_receivable": ("Accounts Receivable (A/R)", "asset", "accounts_receivable",
                            "What customers owe you (used by invoices)."),
    "accounts_payable": ("Accounts Payable (A/P)", "liability", "accounts_payable",
                         "What you owe vendors for unpaid bills."),
    "reimbursements_owed": ("Reimbursements Owed", "liability", "other_current_liability",
                            "Expenses people paid personally that the business still owes them."),
    "due_to_owner": ("Due to Owner", "liability", "other_current_liability",
                     "Loans the owner made to the business that have not yet been repaid."),
    "payment_account_not_set": ("Payment Account Not Set", "asset", "other_current_asset",
                                "Expenses saved without saying which account paid them. Set the payment "
                                "account on those expenses to bring this to zero."),
    "opening_balance_equity": ("Opening Balance Equity", "equity", "equity",
                               "Balancing side of opening balances."),
    "retained_earnings": ("Retained Earnings", "equity", "equity",
                          "Profit from earlier years (calculated by the reports)."),
    "uncategorized_income": ("Uncategorized Income", "income", "income", "Money in without a category."),
    "billable_expense_income": ("Billable Expense Income", "income", "income",
                                "What you charge customers for billable expenses you put on their invoices."),
    "uncategorized_expense": ("Uncategorized Expense", "expense", "expense", "Money out without a category."),
}
KIND_TO_TYPE = {"expense": ("expense", "expense"), "income": ("income", "income"), "equity": ("equity", "equity")}


def account_type_for_bank(kind: str) -> tuple[str, str]:
    return ("liability", "credit_card") if kind == "credit_card" else ("asset", "bank")


def system_account(db: Session, company_id: uuid.UUID, key: str) -> LedgerAccount:
    acct = db.scalar(select(LedgerAccount).where(LedgerAccount.company_id == company_id,
                                                 LedgerAccount.system_key == key))
    if acct is None:
        name, type_, detail, desc = SYSTEM_ACCOUNTS[key]
        # Adopt the account people created by hand before v0.11.0, preserving every journal line already on it.
        aliases = ("due to owner", "owner loan payable", "loan payable to owner") if key == "due_to_owner" else ()
        acct = db.scalar(select(LedgerAccount).where(
            LedgerAccount.company_id == company_id, LedgerAccount.type == type_,
            func.lower(LedgerAccount.name).in_(aliases)).order_by(LedgerAccount.created_at).limit(1)) if aliases else None
        if acct is not None:
            acct.system_key, acct.detail_type, acct.description = key, detail, acct.description or desc
        else:
            acct = LedgerAccount(id=uuid.uuid4(), company_id=company_id, name=name, type=type_, detail_type=detail,
                                 system_key=key, description=desc)
            db.add(acct)
        db.flush()
    return acct


def ledger_for_category(cat: ExpenseCategory) -> LedgerAccount:
    type_, detail = KIND_TO_TYPE.get(cat.kind, ("expense", "expense"))
    return LedgerAccount(id=uuid.uuid4(), company_id=cat.company_id, name=cat.name, type=type_, detail_type=detail)


def ledger_for_bank(fa: FinancialAccount) -> LedgerAccount:
    type_, detail = account_type_for_bank(fa.kind)
    return LedgerAccount(id=uuid.uuid4(), company_id=fa.company_id, name=fa.name, type=type_, detail_type=detail)


def ensure_chart(db: Session, company_id: uuid.UUID) -> None:
    """System accounts plus a ledger account for every category and bank/card account. Idempotent."""
    for key in SYSTEM_ACCOUNTS:
        system_account(db, company_id, key)
    for cat in db.scalars(select(ExpenseCategory).where(ExpenseCategory.company_id == company_id,
                                                        ExpenseCategory.ledger_account_id.is_(None))):
        acct = ledger_for_category(cat)
        db.add(acct)
        cat.ledger_account_id = acct.id
    for fa in db.scalars(select(FinancialAccount).where(FinancialAccount.company_id == company_id,
                                                        FinancialAccount.ledger_account_id.is_(None))):
        acct = ledger_for_bank(fa)
        db.add(acct)
        fa.ledger_account_id = acct.id
    db.flush()
