from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import shutil

from .database import Base, engine, get_db
from . import models, schemas

Base.metadata.create_all(bind=engine)

app = FastAPI(title="FM Finance API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
STATIC_DIR = Path(__file__).parent / "static"

@app.on_event("startup")
def seed():
    db = next(get_db())
    try:
        if not db.query(models.Company).first():
            company = models.Company(name="FM Finance Demo")
            db.add(company); db.flush()
            categories = [
                ("Sales / Income", "income", False),
                ("Software & Subscriptions", "expense", True),
                ("Fuel", "expense", True),
                ("Meals", "expense", True),
                ("Office Supplies", "expense", True),
                ("Repairs & Maintenance", "expense", True),
                ("Travel", "expense", True),
                ("Utilities", "expense", True),
                ("Uncategorized", "expense", False),
            ]
            cats = {}
            for name, kind, deductible in categories:
                c = models.Category(name=name, kind=kind, tax_deductible_default=deductible)
                db.add(c); db.flush(); cats[name] = c
            acct = models.Account(company_id=company.id, name="Business Checking", institution="Demo Bank", account_type="checking", last4="4821", balance=Decimal("84321.18"))
            cc = models.Account(company_id=company.id, name="Business Credit Card", institution="Demo Bank", account_type="credit", last4="1174", balance=Decimal("-2842.77"))
            db.add_all([acct, cc]); db.flush()
            vendors = {}
            for name in ["Microsoft", "Home Depot", "Shell", "Amazon", "Client Deposit"]:
                v = models.Vendor(name=name); db.add(v); db.flush(); vendors[name] = v
            now = datetime.utcnow()
            demo = [
                (acct, "Client Deposit", Decimal("12400.00"), "income", "Sales / Income", 99, True, 1),
                (cc, "Microsoft 365", Decimal("-24.99"), "expense", "Software & Subscriptions", 99, True, 2),
                (cc, "Home Depot", Decimal("-327.42"), "expense", "Repairs & Maintenance", 94, True, 3),
                (cc, "Shell", Decimal("-68.20"), "expense", "Fuel", 97, False, 4),
                (cc, "Amazon Marketplace", Decimal("-143.74"), "expense", "Uncategorized", 62, True, 5),
            ]
            for account, desc, amt, typ, cat, conf, receipt, days in demo:
                vendor = vendors["Client Deposit"] if "Deposit" in desc else next((v for n,v in vendors.items() if n in desc), None)
                db.add(models.Transaction(account_id=account.id, vendor_id=vendor.id if vendor else None, category_id=cats[cat].id, tx_date=now-timedelta(days=days), description=desc, amount=amt, tx_type=typ, status="review" if conf < 98 else "approved", confidence=conf, receipt_attached=receipt, tax_deductible=cats[cat].tax_deductible_default))
            db.add(models.Rule(name="Microsoft software", merchant_contains="Microsoft", category_id=cats["Software & Subscriptions"].id, auto_approve=True))
            db.commit()
    finally:
        db.close()

@app.get("/api/health")
def health():
    return {"status": "ok", "app": "FM Finance", "version": "0.1.0"}

@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    txs = db.query(models.Transaction).all()
    income = sum((Decimal(t.amount) for t in txs if Decimal(t.amount) > 0), Decimal("0"))
    expenses = sum((-Decimal(t.amount) for t in txs if Decimal(t.amount) < 0), Decimal("0"))
    cash = sum((Decimal(a.balance) for a in db.query(models.Account).filter(models.Account.account_type != "credit").all()), Decimal("0"))
    needs_review = db.query(models.Transaction).filter(models.Transaction.status == "review").count()
    return {"cash": float(cash), "income": float(income), "expenses": float(expenses), "net_cash_flow": float(income-expenses), "needs_review": needs_review}

@app.get("/api/accounts")
def accounts(db: Session = Depends(get_db)):
    return [{"id": a.id, "name": a.name, "institution": a.institution, "account_type": a.account_type, "last4": a.last4, "balance": float(a.balance), "active": a.active} for a in db.query(models.Account).all()]

@app.post("/api/accounts")
def create_account(payload: schemas.AccountCreate, db: Session = Depends(get_db)):
    a = models.Account(**payload.model_dump())
    db.add(a); db.commit(); db.refresh(a)
    return {"id": a.id}

@app.get("/api/categories")
def categories(db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name, "kind": c.kind, "tax_deductible_default": c.tax_deductible_default} for c in db.query(models.Category).order_by(models.Category.name).all()]

@app.get("/api/transactions")
def transactions(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Transaction).order_by(models.Transaction.tx_date.desc())
    if status: q = q.filter(models.Transaction.status == status)
    rows = []
    for t in q.all():
        rows.append({"id": t.id, "account": t.account.name, "account_id": t.account_id, "date": t.tx_date.isoformat(), "description": t.description, "amount": float(t.amount), "type": t.tx_type, "status": t.status, "confidence": t.confidence, "receipt_attached": t.receipt_attached, "tax_deductible": t.tax_deductible, "category": t.category.name if t.category else None, "category_id": t.category_id, "vendor": t.vendor.name if t.vendor else None, "notes": t.notes})
    return rows

@app.post("/api/transactions")
def create_transaction(payload: schemas.TransactionCreate, db: Session = Depends(get_db)):
    t = models.Transaction(**payload.model_dump(), status="review")
    if t.category_id:
        cat = db.get(models.Category, t.category_id)
        if cat: t.tax_deductible = cat.tax_deductible_default
    apply_rules(t, db)
    db.add(t); db.commit(); db.refresh(t)
    return {"id": t.id, "status": t.status}

@app.patch("/api/transactions/{transaction_id}")
def update_transaction(transaction_id: int, payload: schemas.TransactionUpdate, db: Session = Depends(get_db)):
    t = db.get(models.Transaction, transaction_id)
    if not t: raise HTTPException(404, "Transaction not found")
    for k, v in payload.model_dump(exclude_unset=True).items(): setattr(t, k, v)
    db.commit()
    return {"ok": True}

@app.post("/api/transactions/{transaction_id}/approve")
def approve_transaction(transaction_id: int, db: Session = Depends(get_db)):
    t = db.get(models.Transaction, transaction_id)
    if not t: raise HTTPException(404, "Transaction not found")
    t.status = "approved"; db.commit()
    return {"ok": True}

@app.get("/api/rules")
def rules(db: Session = Depends(get_db)):
    return [{"id": r.id, "name": r.name, "merchant_contains": r.merchant_contains, "category": r.category.name, "category_id": r.category_id, "auto_approve": r.auto_approve, "active": r.active} for r in db.query(models.Rule).all()]

@app.post("/api/rules")
def create_rule(payload: schemas.RuleCreate, db: Session = Depends(get_db)):
    r = models.Rule(**payload.model_dump())
    db.add(r); db.commit(); db.refresh(r)
    return {"id": r.id}

def apply_rules(t: models.Transaction, db: Session):
    for r in db.query(models.Rule).filter(models.Rule.active == True).all():
        if r.merchant_contains.lower() in t.description.lower():
            t.category_id = r.category_id
            t.confidence = 99
            t.status = "approved" if r.auto_approve else "review"
            break

@app.post("/api/receipts/upload")
def upload_receipt(file: UploadFile = File(...), db: Session = Depends(get_db)):
    destination = UPLOAD_DIR / file.filename
    with destination.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    receipt = models.Receipt(filename=file.filename)
    db.add(receipt); db.commit(); db.refresh(receipt)
    return {"id": receipt.id, "filename": receipt.filename, "status": "uploaded"}

@app.get("/api/reports/expense-by-category")
def expense_by_category(db: Session = Depends(get_db)):
    rows = db.query(models.Category.name, func.sum(case((models.Transaction.amount < 0, -models.Transaction.amount), else_=0))).outerjoin(models.Transaction, models.Transaction.category_id == models.Category.id).group_by(models.Category.id).all()
    return [{"category": name, "amount": float(total or 0)} for name, total in rows if float(total or 0) > 0]

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")
