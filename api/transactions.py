from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .. import models, schemas, database

from datetime import datetime
from typing import Optional
import csv
import io
from fastapi.responses import StreamingResponse
from fastapi import UploadFile, File
import uuid

router = APIRouter(prefix="/api/transactions", tags=["transactions"])

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/", response_model=schemas.Transaction)
def create_transaction(transaction: schemas.TransactionCreate, db: Session = Depends(get_db)):
    db_transaction = models.Transaction(**transaction.dict())
    db.add(db_transaction)
    
    # Balance update logic
    if transaction.type == schemas.TransactionType.income:
        account = db.query(models.Account).filter(models.Account.id == transaction.account_id).first()
        if account:
            account.balance += transaction.amount
    elif transaction.type == schemas.TransactionType.expense:
        account = db.query(models.Account).filter(models.Account.id == transaction.account_id).first()
        if account:
            account.balance -= transaction.amount
    elif transaction.type == schemas.TransactionType.transfer:
        if not transaction.destination_account_id:
            raise HTTPException(status_code=400, detail="Destination account required for transfer")
        
        src = db.query(models.Account).filter(models.Account.id == transaction.account_id).first()
        dst = db.query(models.Account).filter(models.Account.id == transaction.destination_account_id).first()
        
        if src:
            src.balance -= transaction.amount
        if dst:
            dst.balance += transaction.amount

    db.commit()
    db.refresh(db_transaction)
    return db_transaction

@router.get("/", response_model=List[schemas.Transaction])
def read_transactions(
    skip: int = 0, 
    limit: int = 100, 
    month: Optional[int] = None, 
    year: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.Transaction)
    
    if month is not None and year is not None:
        start_date = datetime(year, month, 1)
        if month == 12:
            next_month, next_year = 1, year + 1
        else:
            next_month, next_year = month + 1, year
        end_date = datetime(next_year, next_month, 1)
        query = query.filter(models.Transaction.date >= start_date, models.Transaction.date < end_date)
    
    transactions = query.order_by(models.Transaction.date.desc()).offset(skip).limit(limit).all()
    return transactions


@router.delete("/{transaction_id}")
def delete_transaction(transaction_id: str, db: Session = Depends(get_db)):
    db_transaction = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
    if db_transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    db.delete(db_transaction)
    db.commit()
    return {"ok": True}
@router.get("/export")
def export_transactions(db: Session = Depends(get_db)):
    transactions = db.query(models.Transaction).order_by(models.Transaction.date.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "amount", "type", "description", "date", "account_id", "category_id", "destination_account_id"])
    
    for t in transactions:
        writer.writerow([
            t.id, 
            t.amount, 
            t.type, 
            t.description, 
            t.date.isoformat(), 
            t.account_id, 
            t.category_id, 
            t.destination_account_id
        ])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]), 
        media_type="text/csv", 
        headers={"Content-Disposition": "attachment; filename=transactions.csv"}
    )

@router.post("/import")
async def import_transactions(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    decoded = content.decode('utf-8')
    reader = csv.DictReader(io.StringIO(decoded))
    
    imported_count = 0
    for row in reader:
        # Simple import logic, assuming the CSV follows the exported format
        try:
            # Check if transaction already exists to avoid duplicates
            existing = db.query(models.Transaction).filter(models.Transaction.id == row['id']).first()
            if existing:
                continue
                
            db_transaction = models.Transaction(
                id=row['id'] if row['id'] else str(uuid.uuid4()),
                amount=float(row['amount']),
                type=row['type'],
                description=row['description'],
                date=datetime.fromisoformat(row['date'].replace('Z', '')),
                account_id=row['account_id'],
                category_id=row['category_id'] if row['category_id'] else None,
                destination_account_id=row['destination_account_id'] if row['destination_account_id'] else None
            )
            db.add(db_transaction)
            
            # Update account balances
            if db_transaction.type == "income":
                account = db.query(models.Account).filter(models.Account.id == db_transaction.account_id).first()
                if account: account.balance += db_transaction.amount
            elif db_transaction.type == "expense":
                account = db.query(models.Account).filter(models.Account.id == db_transaction.account_id).first()
                if account: account.balance -= db_transaction.amount
            elif db_transaction.type == "transfer":
                src = db.query(models.Account).filter(models.Account.id == db_transaction.account_id).first()
                dst = db.query(models.Account).filter(models.Account.id == db_transaction.destination_account_id).first()
                if src: src.balance -= db_transaction.amount
                if dst: dst.balance += db_transaction.amount
            
            imported_count += 1
        except Exception as e:
            print(f"Error importing row: {e}")
            continue
            
    db.commit()
    return {"message": f"Successfully imported {imported_count} transactions"}
