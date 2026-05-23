from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.dependencies import get_current_user, get_db
from models import Category, Transaction
import schemas
from services.smart_categorization_service import SmartCategorizationService
from user_models import User

router = APIRouter(prefix="/categorize", tags=["categorize"])


@router.post("/suggest", response_model=schemas.CategorizationSuggestion)
def suggest_category(
    request: schemas.CategorizationSuggestionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SmartCategorizationService()
    suggestion = service.categorize_transaction(
        user_id=current_user.id,
        description=request.description or "",
        merchant=request.merchant or "",
        amount=request.amount,
        type=request.type,
        db=db,
    )
    category = db.query(Category).filter(Category.id == suggestion["category_id"]).first() if suggestion["category_id"] else None
    return {
        **suggestion,
        "category_name": category.name if category else None,
    }


@router.post("/bulk", response_model=list[schemas.BulkCategorizationSuggestion])
def bulk_categorize(
    request: schemas.BulkCategorizationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SmartCategorizationService()
    results = []

    for item in request.transactions:
        transaction = None
        if item.transaction_id:
            transaction = (
                db.query(Transaction)
                .filter(Transaction.id == item.transaction_id, Transaction.owner_id == current_user.id)
                .first()
            )
            if not transaction:
                raise HTTPException(status_code=404, detail=f"Transaction {item.transaction_id} not found")

        description = item.description or (transaction.description if transaction else "")
        merchant = item.merchant or (transaction.merchant if transaction else "")
        amount = item.amount if item.amount is not None else (transaction.amount if transaction else 0)
        tx_type = item.type or (transaction.type if transaction else None)

        suggestion = service.categorize_transaction(
            user_id=current_user.id,
            description=description or "",
            merchant=merchant or "",
            amount=amount or 0,
            type=tx_type,
            db=db,
        )
        category = db.query(Category).filter(Category.id == suggestion["category_id"]).first() if suggestion["category_id"] else None

        applied = False
        if (
            request.apply
            and transaction is not None
            and transaction.category_id is None
            and suggestion["category_id"]
            and suggestion["confidence"] >= SmartCategorizationService.AUTO_ASSIGN_CONFIDENCE
        ):
            transaction.category_id = suggestion["category_id"]
            transaction.categorization_method = suggestion["method"]
            transaction.categorization_confidence = suggestion["confidence"]
            if suggestion.get("normalized_merchant") and not transaction.merchant:
                transaction.merchant = suggestion["normalized_merchant"]
            applied = True

        results.append(
            {
                **suggestion,
                "transaction_id": item.transaction_id,
                "category_name": category.name if category else None,
                "applied": applied,
            }
        )

    db.commit()
    return results


@router.get("/patterns", response_model=list[schemas.MerchantCategoryPattern])
def list_patterns(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return SmartCategorizationService().get_learned_patterns(current_user.id, db)
