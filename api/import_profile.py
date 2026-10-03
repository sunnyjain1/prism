from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Dict

from core.dependencies import get_db, get_current_user
from user_models import User
from services.import_profile_service import ImportProfileService

router = APIRouter(prefix="/import-profile", tags=["import-profile"])


@router.get("", response_model=Dict[str, Any])
def get_import_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the user's saved import profile config, or an empty scaffold."""
    svc = ImportProfileService(db, current_user.id)
    config = svc.get_profile()
    if config is None:
        config = svc._empty_config()
    return config


@router.put("", response_model=Dict[str, Any])
def save_import_profile(
    config: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save (overwrite) the user's import profile config."""
    svc = ImportProfileService(db, current_user.id)
    return svc.save_profile(config)


@router.post("/generate-from-history", response_model=Dict[str, Any])
def generate_import_profile_from_history(
    save: bool = True,
    min_frequency: int = 3,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Build an import profile from transactions already in Prism.

    For users who never uploaded a Money Manager export: learns note→category
    rules from their own categorized history so auto-created entries (SMS,
    Account Aggregator, Gmail) match how they categorize things manually.
    """
    svc = ImportProfileService(db, current_user.id)
    config = svc.generate_from_history(min_frequency=min_frequency)

    if not config["note_rules"]:
        raise HTTPException(
            status_code=422,
            detail="Not enough categorized history to build a profile. "
                   f"Need at least {min_frequency} transactions sharing a description.",
        )

    if save:
        config = svc.save_profile(config)

    return {
        "saved": save,
        "rules_extracted": len(config.get("note_rules", [])),
        "config": config,
    }


@router.post("/generate", response_model=Dict[str, Any])
async def generate_import_profile(
    file: UploadFile = File(...),
    save: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a Money Manager Excel export to auto-generate an import profile.

    Analyses note→category frequencies, account names, and skip patterns from
    your historical data and returns a ready-to-use config.
    If save=true (default), also persists it as your active profile.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")

    svc = ImportProfileService(db, current_user.id)
    config = svc.generate_from_file(content)

    if not config["note_rules"] and not config["account_mappings"]:
        raise HTTPException(
            status_code=422,
            detail="Could not extract any rules from the file. "
                   "Make sure it is a Money Manager Excel export with Note, Category, and Account columns.",
        )

    if save:
        config = svc.save_profile(config)

    return {
        "saved": save,
        "rules_extracted": len(config.get("note_rules", [])),
        "accounts_mapped": len(config.get("account_mappings", {})),
        "categories_mapped": len(config.get("category_mappings", {})),
        "config": config,
    }
