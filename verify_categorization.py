import sys
import os
from sqlalchemy.orm import Session
from database import SessionLocal, engine, Base
import models
import user_models
from services.category_inference_service import CategoryInferenceService
from schemas import TransactionType

def verify():
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    # Use a dummy owner_id or an existing one if available
    owner_id = "test-user-rule"
    
    try:
        service = CategoryInferenceService(db, owner_id)
        
        print("Seeding default rules...")
        service.seed_default_rules()
        
        # Test 1: Simple keyword match
        desc1 = "Payment to Swiggy #12345"
        cat1 = service.infer_category(desc1, TransactionType.expense)
        print(f"Test 1 (Swiggy): Inferred '{cat1}' - Expected 'Food & Dining'")
        
        # Test 2: Another keyword
        desc2 = "Uber Ride"
        cat2 = service.infer_category(desc2, TransactionType.expense)
        print(f"Test 2 (Uber): Inferred '{cat2}' - Expected 'Transportation'")
        
        # Test 3: Custom rule via DB
        from models import CategorizationRule, Category
        import uuid
        
        # Find or create category
        cat_obj = db.query(Category).filter(Category.name == "Custom Cat").first()
        if not cat_obj:
            cat_obj = Category(id=str(uuid.uuid4()), name="Custom Cat", type="expense", owner_id=owner_id)
            db.add(cat_obj)
            db.commit()
            
        custom_rule = CategorizationRule(
            id=str(uuid.uuid4()),
            pattern=r"SPECIFIC_TOKEN_\d+",
            category_id=cat_obj.id,
            priority=200, # Higher priority
            owner_id=owner_id,
            is_regex=True
        )
        db.add(custom_rule)
        db.commit()
        
        desc3 = "Transaction SPECIFIC_TOKEN_999"
        cat3 = service.infer_category(desc3, TransactionType.expense)
        print(f"Test 3 (Regex): Inferred '{cat3}' - Expected 'Custom Cat'")
        
    finally:
        db.close()

if __name__ == "__main__":
    verify()
