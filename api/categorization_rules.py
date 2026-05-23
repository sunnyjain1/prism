from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import uuid

from core.dependencies import get_db, get_current_user
from user_models import User
import schemas
from models import CategorizationRule

router = APIRouter(prefix="/categorization-rules", tags=["categorization-rules"])

@router.get("", response_model=List[schemas.CategorizationRule])
def get_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all categorization rules for the current user."""
    return db.query(CategorizationRule).filter(
        CategorizationRule.owner_id == current_user.id
    ).order_by(CategorizationRule.priority.desc()).all()

@router.post("", response_model=schemas.CategorizationRule)
def create_rule(
    rule_in: schemas.CategorizationRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new categorization rule."""
    rule_data = rule_in.model_dump()
    if not rule_data.get("id"):
        rule_data["id"] = str(uuid.uuid4())
    
    rule_data["owner_id"] = current_user.id
    
    new_rule = CategorizationRule(**rule_data)
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    return new_rule

@router.put("/{rule_id}", response_model=schemas.CategorizationRule)
def update_rule(
    rule_id: str,
    rule_in: schemas.CategorizationRuleBase,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update an existing categorization rule."""
    rule = db.query(CategorizationRule).filter(
        CategorizationRule.id == rule_id,
        CategorizationRule.owner_id == current_user.id
    ).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    update_data = rule_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(rule, key, value)
    
    db.commit()
    db.refresh(rule)
    return rule

@router.delete("/{rule_id}", response_model=schemas.OkResponse)
def delete_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a categorization rule."""
    rule = db.query(CategorizationRule).filter(
        CategorizationRule.id == rule_id,
        CategorizationRule.owner_id == current_user.id
    ).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    db.delete(rule)
    db.commit()
    return {"ok": True}
