"""
Sync API endpoints for Gmail OAuth, account sync configuration, and manual triggers.
"""
from datetime import datetime, timedelta, timezone
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from core.dependencies import get_db, get_current_user
from core.config import settings
from user_models import User
from repositories.sync_repository import SyncRepository
from services.sync_orchestrator import SyncOrchestrator
from services.bulk_upload_service import BulkUploadService
import schemas

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync", tags=["sync"])


def _create_gmail_oauth_state(user_id: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.GMAIL_OAUTH_STATE_EXPIRE_MINUTES
    )
    return jwt.encode(
        {"sub": user_id, "purpose": "gmail-oauth", "exp": expires_at},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def _validate_gmail_oauth_state(state: str, expected_user_id: str) -> None:
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from exc

    if payload.get("purpose") != "gmail-oauth" or payload.get("sub") != expected_user_id:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")


# ─── Gmail OAuth ──────────────────────────────────────────────

@router.get("/gmail/auth-url", response_model=schemas.AuthUrlResponse)
def get_gmail_auth_url(current_user: User = Depends(get_current_user)):
    """Get the Google OAuth consent URL for Gmail access."""
    from google_auth_oauthlib.flow import Flow

    if not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_CLIENT_SECRET not configured. Set it in environment variables."
        )

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GMAIL_REDIRECT_URI]
            }
        },
        scopes=settings.GMAIL_SCOPES
    )
    flow.redirect_uri = settings.GMAIL_REDIRECT_URI

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        # Sign the user id so the callback can detect tampering/replay across users.
        state=_create_gmail_oauth_state(current_user.id)
    )

    return {"auth_url": auth_url, "state": state}


@router.post("/gmail/callback", response_model=schemas.GmailOAuthCallbackResponse)
def gmail_oauth_callback(
    payload: schemas.GmailOAuthCallback,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Exchange the OAuth authorization code for tokens.
    Called by the frontend after Google redirects back with the code.
    """
    from google_auth_oauthlib.flow import Flow

    _validate_gmail_oauth_state(payload.state, current_user.id)

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GMAIL_REDIRECT_URI]
            }
        },
        scopes=settings.GMAIL_SCOPES
    )
    flow.redirect_uri = settings.GMAIL_REDIRECT_URI

    # Google often returns more scopes than requested (e.g. profile, email)
    # This prevents oauthlib from raising a Warning/Exception for the scope mismatch
    import os
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

    try:
        flow.fetch_token(code=payload.code)
    except Exception as e:
        logger.error(f"Gmail OAuth token exchange failed: {e}")
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {e}")

    credentials = flow.credentials

    if not credentials.refresh_token:
        raise HTTPException(
            status_code=400,
            detail="No refresh token received. Try revoking app access in Google Account settings and reconnecting."
        )

    # Get user's email from the ID token or userinfo
    gmail_email = None
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        userinfo = id_token.verify_oauth2_token(
            credentials.id_token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )
        gmail_email = userinfo.get("email")
    except Exception:
        pass  # Email is optional metadata

    # Store encrypted refresh token
    sync_repo = SyncRepository(db)
    sync_repo.save_gmail_token(
        user_id=current_user.id,
        refresh_token=credentials.refresh_token,
        gmail_email=gmail_email,
        scopes=",".join(settings.GMAIL_SCOPES)
    )

    logger.info(f"Gmail connected for user {current_user.id} ({gmail_email})")
    return {"message": "Gmail connected", "email": gmail_email}


@router.get("/gmail/status", response_model=schemas.GmailConnectionStatus)
def get_gmail_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check if Gmail is connected for the current user."""
    sync_repo = SyncRepository(db)
    token = sync_repo.get_gmail_token(current_user.id)

    if token and token.is_valid:
        return schemas.GmailConnectionStatus(
            is_connected=True,
            gmail_email=token.gmail_email
        )
    return schemas.GmailConnectionStatus(is_connected=False)


@router.delete("/gmail/disconnect", response_model=schemas.MessageResponse)
def disconnect_gmail(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Disconnect Gmail (revoke and delete stored tokens)."""
    sync_repo = SyncRepository(db)
    deleted = sync_repo.delete_gmail_token(current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Gmail not connected")
    return {"message": "Gmail disconnected successfully"}


# ─── Sync Config CRUD ────────────────────────────────────────

@router.post("/accounts/{account_id}/config", response_model=schemas.SyncConfigOut)
def create_or_update_sync_config(
    account_id: str,
    config_in: schemas.SyncConfigCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create or update sync config for an account."""
    # Validate importer key
    bulk_service = BulkUploadService(db)
    if config_in.importer_key not in bulk_service.importers:
        available = list(bulk_service.importers.keys())
        raise HTTPException(
            status_code=400,
            detail=f"Invalid importer_key '{config_in.importer_key}'. Available: {available}"
        )

    sync_repo = SyncRepository(db)
    existing = sync_repo.get_sync_config(account_id, current_user.id)

    if existing:
        updated = sync_repo.update_sync_config(
            existing,
            gmail_search_query=config_in.gmail_search_query,
            importer_key=config_in.importer_key,
            sync_interval_days=config_in.sync_interval_days,
            attachment_filename_pattern=config_in.attachment_filename_pattern,
            is_enabled=config_in.is_enabled,
            pdf_password=config_in.pdf_password
        )
        # Map has_pdf_password
        updated.has_pdf_password = bool(updated.encrypted_pdf_password)
        return updated

    created = sync_repo.create_sync_config(
        account_id=account_id,
        owner_id=current_user.id,
        gmail_search_query=config_in.gmail_search_query,
        importer_key=config_in.importer_key,
        sync_interval_days=config_in.sync_interval_days,
        attachment_filename_pattern=config_in.attachment_filename_pattern,
        is_enabled=config_in.is_enabled,
        pdf_password=config_in.pdf_password,
        sync_start_date=config_in.sync_start_date
    )
    created.has_pdf_password = bool(created.encrypted_pdf_password)
    return created


@router.get("/accounts/{account_id}/config", response_model=schemas.SyncConfigOut)
def get_sync_config(
    account_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get sync config for an account."""
    sync_repo = SyncRepository(db)
    config = sync_repo.get_sync_config(account_id, current_user.id)
    if not config:
        raise HTTPException(status_code=404, detail="Sync config not found for this account")
    config.has_pdf_password = bool(config.encrypted_pdf_password)
    return config


@router.patch("/accounts/{account_id}/config", response_model=schemas.SyncConfigOut)
def update_sync_config(
    account_id: str,
    config_in: schemas.SyncConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Partially update sync config for an account."""
    sync_repo = SyncRepository(db)
    config = sync_repo.get_sync_config(account_id, current_user.id)
    if not config:
        raise HTTPException(status_code=404, detail="Sync config not found for this account")

    update_data = config_in.model_dump(exclude_unset=True)

    # Validate importer key if being changed
    if "importer_key" in update_data:
        bulk_service = BulkUploadService(db)
        if update_data["importer_key"] not in bulk_service.importers:
            raise HTTPException(status_code=400, detail=f"Invalid importer_key")

    updated = sync_repo.update_sync_config(config, **update_data)
    updated.has_pdf_password = bool(updated.encrypted_pdf_password)
    return updated


@router.delete("/accounts/{account_id}/config", response_model=schemas.MessageResponse)
def delete_sync_config(
    account_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete sync config for an account."""
    sync_repo = SyncRepository(db)
    deleted = sync_repo.delete_sync_config(account_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sync config not found")
    return {"message": "Sync config deleted"}


# ─── Sync Trigger & Status ───────────────────────────────────

def _run_sync_in_background(account_id: str, owner_id: str):
    """Background task: run sync with its own DB session."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        sync_repo = SyncRepository(db)
        config = sync_repo.get_sync_config(account_id, owner_id)
        if config:
            orchestrator = SyncOrchestrator(db)
            orchestrator.sync_account(config)
    except Exception as e:
        logger.exception(f"Background sync failed for account {account_id}: {e}")
    finally:
        db.close()


@router.post("/accounts/{account_id}/trigger", response_model=schemas.SyncTriggerResponse)
def trigger_sync(
    account_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Manually trigger a sync for an account.

    The sync runs in the background so the endpoint returns immediately.
    Use GET /api/v1/sync/accounts/status to poll for the result.
    This is especially useful for historical syncs that may take a long time
    when the account has a ``sync_start_date`` set to fetch years of old data.
    """
    sync_repo = SyncRepository(db)
    config = sync_repo.get_sync_config(account_id, current_user.id)
    if not config:
        raise HTTPException(status_code=404, detail="Sync config not found for this account")

    # Check Gmail is connected
    token = sync_repo.get_gmail_token(current_user.id)
    if not token or not token.is_valid:
        raise HTTPException(status_code=400, detail="Gmail not connected. Please connect Gmail first.")

    # Prevent starting a new sync if one is already running
    from models import SyncStatus
    if config.last_sync_status == SyncStatus.syncing.value:
        raise HTTPException(status_code=409, detail="A sync is already in progress for this account.")

    background_tasks.add_task(_run_sync_in_background, account_id, current_user.id)
    return {
        "message": "Sync started in background",
        "account_id": account_id,
        "status": "queued"
    }


@router.get("/accounts/status", response_model=list[schemas.SyncConfigOut])
def get_all_sync_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get sync status for all configured accounts."""
    sync_repo = SyncRepository(db)
    configs = sync_repo.get_all_sync_configs_for_user(current_user.id)
    out = []
    for c in configs:
        c.has_pdf_password = bool(c.encrypted_pdf_password)
        out.append(schemas.SyncConfigOut.model_validate(c))
    return out


@router.get("/importers", response_model=dict[str, dict[str, object]])
def get_available_importers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of available importers for sync config."""
    bulk_service = BulkUploadService(db)
    return bulk_service.get_supported_formats()
