import csv
import io
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

import schemas
from core.dependencies import get_current_user, get_db
from services.transaction_service import TransactionService
from user_models import User

HTTP_422_VALIDATION = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)

router = APIRouter(prefix="/transactions", tags=["transactions"])
v1_router = APIRouter(prefix="/transactions", tags=["transactions"])


def _parse_date(date_str: str, field_name: str, end_of_day: bool = False) -> datetime:
    try:
        dt = datetime.fromisoformat(date_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTP_422_VALIDATION,
            detail=f"{field_name} must be a valid ISO 8601 date or datetime",
        ) from exc

    if end_of_day and "T" not in date_str and dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


def _validate_period_filters(
    month: Optional[int],
    year: Optional[int],
    start_date: Optional[datetime],
    end_date: Optional[datetime],
) -> None:
    if (month is None) != (year is None):
        raise HTTPException(
            status_code=HTTP_422_VALIDATION,
            detail="month and year must be provided together",
        )
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=HTTP_422_VALIDATION,
            detail="start_date must be before or equal to end_date",
        )


@v1_router.post("", response_model=schemas.Transaction)
@router.post("", response_model=schemas.Transaction)
def create_transaction(
    transaction: schemas.TransactionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TransactionService(db)
    return service.create_transaction(transaction, current_user.id)


@v1_router.post("/bulk", response_model=List[schemas.Transaction])
@router.post("/bulk", response_model=List[schemas.Transaction])
def create_transactions_bulk(
    transactions_in: List[schemas.TransactionCreate],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TransactionService(db)
    created_transactions = []

    try:
        for tx_in in transactions_in:
            tx = service.create_transaction(tx_in, current_user.id)
            created_transactions.append(tx)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to create transactions: {exc}") from exc

    return created_transactions


@v1_router.get("", response_model=schemas.PaginatedResponse[schemas.Transaction])
@router.get("", response_model=List[schemas.Transaction])
def read_transactions(
    request: Request,
    month: Optional[int] = Query(default=None, ge=1, le=12),
    year: Optional[int] = Query(default=None, ge=1900, le=3000),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    category_ids: Optional[List[str]] = Query(default=None),
    account_id: Optional[str] = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=10000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TransactionService(db)

    s_date = _parse_date(start_date, "start_date") if start_date else None
    e_date = _parse_date(end_date, "end_date", end_of_day=True) if end_date else None
    _validate_period_filters(month, year, s_date, e_date)

    items = service.get_transactions(
        current_user.id,
        month,
        year,
        s_date,
        e_date,
        search,
        category_ids,
        account_id,
        skip,
        limit,
    )

    if request.url.path.startswith("/api/v1/"):
        total = service.count_transactions(
            current_user.id,
            month,
            year,
            s_date,
            e_date,
            search,
            category_ids,
            account_id,
        )
        return schemas.PaginatedResponse[schemas.Transaction](
            items=items,
            total=total,
            skip=skip,
            limit=limit,
        )

    return items


@v1_router.get("/summary", response_model=List[schemas.TransactionSummaryItem])
@router.get("/summary", response_model=List[schemas.TransactionSummaryItem])
def get_summary(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=1900, le=3000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TransactionService(db)
    return service.get_transaction_summary(current_user.id, month, year)


@v1_router.get("/aggregate", response_model=schemas.TransactionAggregateResponse)
@router.get("/aggregate", response_model=schemas.TransactionAggregateResponse)
def aggregate_transactions(
    month: Optional[int] = Query(default=None, ge=1, le=12),
    year: Optional[int] = Query(default=None, ge=1900, le=3000),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    category_ids: Optional[List[str]] = Query(default=None),
    account_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TransactionService(db)
    s_date = _parse_date(start_date, "start_date") if start_date else None
    e_date = _parse_date(end_date, "end_date", end_of_day=True) if end_date else None
    _validate_period_filters(month, year, s_date, e_date)
    return service.aggregate_transactions(
        current_user.id, month, year, s_date, e_date, search, category_ids, account_id
    )


@v1_router.get("/history", response_model=List[schemas.MonthlyHistoryItem])
@router.get("/history", response_model=List[schemas.MonthlyHistoryItem])
def get_history(
    months: int = Query(default=6, ge=1, le=120),
    month: Optional[int] = Query(default=None, ge=1, le=12),
    year: Optional[int] = Query(default=None, ge=1900, le=3000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if (month is None) != (year is None):
        raise HTTPException(
            status_code=HTTP_422_VALIDATION,
            detail="month and year must be provided together",
        )

    service = TransactionService(db)
    return service.get_monthly_history(current_user.id, months, month, year)


@v1_router.put("/{transaction_id}", response_model=schemas.Transaction)
@router.put("/{transaction_id}", response_model=schemas.Transaction)
def update_transaction(
    transaction_id: str,
    transaction: schemas.TransactionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TransactionService(db)
    return service.update_transaction(transaction_id, transaction, current_user.id)


@v1_router.delete("/{transaction_id}", response_model=schemas.OkResponse)
@router.delete("/{transaction_id}", response_model=schemas.OkResponse)
def delete_transaction(
    transaction_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TransactionService(db)
    service.delete_transaction(transaction_id, current_user.id)
    return {"ok": True}


@v1_router.get("/export")
@router.get("/export")
def export_transactions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TransactionService(db)
    transactions = service.get_transactions(current_user.id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "amount", "type", "description", "date", "account_id", "category_id", "destination_account_id"])

    for transaction in transactions:
        writer.writerow([
            transaction.id,
            transaction.amount,
            transaction.type,
            transaction.description,
            transaction.date.isoformat(),
            transaction.account_id,
            transaction.category_id,
            transaction.destination_account_id,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )


@v1_router.post("/import", response_model=schemas.MessageResponse)
@router.post("/import", response_model=schemas.MessageResponse)
async def import_transactions(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    decoded = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))

    service = TransactionService(db)
    imported_count = 0
    for row in reader:
        try:
            tx_in = schemas.TransactionCreate(
                id=row["id"],
                amount=float(row["amount"]),
                type=row["type"],
                description=row["description"],
                date=row["date"],
                timestamp=0,
                account_id=row["account_id"],
                category_id=row["category_id"] if row["category_id"] else None,
                destination_account_id=row["destination_account_id"] if row["destination_account_id"] else None,
            )
            service.create_transaction(tx_in, current_user.id)
            imported_count += 1
        except Exception:
            continue

    return {"message": f"Successfully imported {imported_count} transactions"}
