from fastapi import APIRouter, Depends, UploadFile, File, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from core.dependencies import get_db, get_current_user
from user_models import User
import schemas
from services.transaction_service import TransactionService
from fastapi.responses import StreamingResponse
import io
import csv

router = APIRouter(prefix="/api/transactions", tags=["transactions"])

@router.post("", response_model=schemas.Transaction)
def create_transaction(
    transaction: schemas.TransactionCreate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    service = TransactionService(db)
    return service.create_transaction(transaction, current_user.id)

@router.get("", response_model=List[schemas.Transaction])
def read_transactions(
    month: Optional[int] = None, 
    year: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    category_ids: Optional[List[str]] = Query(None),
    account_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = TransactionService(db)
    
    # helper for date parsing
    from datetime import datetime
    s_date = datetime.fromisoformat(start_date) if start_date else None
    e_date = datetime.fromisoformat(end_date) if end_date else None
    
    return service.get_transactions(current_user.id, month, year, s_date, e_date, search, category_ids, account_id, skip, limit)

@router.get("/history")
def get_history(
    months: int = 6, 
    month: Optional[int] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    service = TransactionService(db)
    return service.get_monthly_history(current_user.id, months, month, year)

@router.put("/{transaction_id}", response_model=schemas.Transaction)
def update_transaction(
    transaction_id: str,
    transaction: schemas.TransactionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = TransactionService(db)
    return service.update_transaction(transaction_id, transaction, current_user.id)

@router.delete("/{transaction_id}")
def delete_transaction(
    transaction_id: str, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    service = TransactionService(db)
    service.delete_transaction(transaction_id, current_user.id)
    return {"ok": True}

@router.get("/export")
def export_transactions(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    service = TransactionService(db)
    transactions = service.get_transactions(current_user.id)
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "amount", "type", "description", "date", "account_id", "category_id", "destination_account_id"])
    
    for t in transactions:
        writer.writerow([
            t.id, t.amount, t.type, t.description, t.date.isoformat(), 
            t.account_id, t.category_id, t.destination_account_id
        ])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]), 
        media_type="text/csv", 
        headers={"Content-Disposition": "attachment; filename=transactions.csv"}
    )

# Import logic can be migrated to service too, but for speed let's keep it here or just refactor later.
@router.post("/import")
async def import_transactions(
    file: UploadFile = File(...), 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    # This should also move to a service eventually for Clean Architecture
    content = await file.read()
    decoded = content.decode('utf-8')
    reader = csv.DictReader(io.StringIO(decoded))
    
    service = TransactionService(db)
    imported_count = 0
    for row in reader:
        try:
            # Basic validation/mapping...
            tx_in = schemas.TransactionCreate(
                id=row['id'],
                amount=float(row['amount']),
                type=row['type'],
                description=row['description'],
                date=row['date'],
                timestamp=0, # Placeholder
                account_id=row['account_id'],
                category_id=row['category_id'] if row['category_id'] else None,
                destination_account_id=row['destination_account_id'] if row['destination_account_id'] else None
            )
            service.create_transaction(tx_in, current_user.id)
            imported_count += 1
        except Exception:
            continue
            
    return {"message": f"Successfully imported {imported_count} transactions"}
