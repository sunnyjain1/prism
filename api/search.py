from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

import schemas
from api.jobs import serialize_job
from core.dependencies import get_current_user, get_db
from database import SessionLocal
from services.job_queue import job_queue
from services.nl_query_parser import NLQueryParser
from services.search_service import SearchService
from user_models import User

router = APIRouter(prefix="/search", tags=["search"])
HTTP_422_VALIDATION = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)
PARSER = NLQueryParser()


def _run_search_reindex(user_id: str, session_factory=None) -> dict[str, Any]:
    session_factory = session_factory or SessionLocal
    db = session_factory()
    try:
        search_service = SearchService(db)

        if not search_service.is_available():
            return {
                "message": "Search is disabled or unavailable; SQL fallback remains active",
                "indexed_count": 0,
                "backend": "sql",
            }

        try:
            indexed_count = search_service.reindex_all(user_id, db)
        except Exception:
            return {
                "message": "Search reindex failed; SQL fallback remains active",
                "indexed_count": 0,
                "backend": "sql",
            }

        return {
            "message": f"Reindexed {indexed_count} transactions",
            "indexed_count": indexed_count,
            "backend": "meilisearch",
        }
    finally:
        db.close()


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


def _parse_csv_ids(raw_value: Optional[str]) -> Optional[list[str]]:
    if not raw_value:
        return None
    values = [value.strip() for value in raw_value.split(",") if value.strip()]
    return values or None


def _validate_date_range(date_from: Optional[datetime], date_to: Optional[datetime]) -> None:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=HTTP_422_VALIDATION, detail="date_from must be before or equal to date_to")


def _build_filters(
    *,
    date_from: Optional[str],
    date_to: Optional[str],
    min_amount: Optional[float],
    max_amount: Optional[float],
    categories: Optional[str],
    accounts: Optional[str],
    transaction_type: Optional[schemas.TransactionType],
    limit: int,
    offset: int,
    sort_by: Optional[str],
) -> dict[str, Any]:
    filters = {
        "date_from": _parse_date(date_from, "date_from") if date_from else None,
        "date_to": _parse_date(date_to, "date_to", end_of_day=True) if date_to else None,
        "min_amount": min_amount,
        "max_amount": max_amount,
        "categories": _parse_csv_ids(categories),
        "accounts": _parse_csv_ids(accounts),
        "type": transaction_type.value if transaction_type else None,
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
    }
    _validate_date_range(filters["date_from"], filters["date_to"])
    return filters


def _merge_natural_filters(parsed_query: dict[str, Any], explicit_filters: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    merged_query = dict(parsed_query)
    service_filters = {
        "date_from": _parse_date(parsed_query["date_from"], "date_from") if parsed_query.get("date_from") else None,
        "date_to": _parse_date(parsed_query["date_to"], "date_to", end_of_day=True) if parsed_query.get("date_to") else None,
        "min_amount": parsed_query.get("min_amount"),
        "max_amount": parsed_query.get("max_amount"),
        "categories": parsed_query.get("categories") or None,
        "accounts": None,
        "type": parsed_query.get("type"),
        "limit": explicit_filters["limit"],
        "offset": explicit_filters["offset"],
        "sort_by": parsed_query.get("sort_by"),
    }

    for key, value in explicit_filters.items():
        if value is None:
            continue
        service_filters[key] = value

    merged_query.update(
        {
            "date_from": service_filters["date_from"].date().isoformat() if service_filters.get("date_from") else None,
            "date_to": service_filters["date_to"].date().isoformat() if service_filters.get("date_to") else None,
            "min_amount": service_filters.get("min_amount"),
            "max_amount": service_filters.get("max_amount"),
            "categories": service_filters.get("categories") or [],
            "type": service_filters.get("type"),
            "sort_by": service_filters.get("sort_by") or "date_desc",
            "parsed": parsed_query.get("parsed") or any(
                explicit_filters.get(key) is not None for key in ["date_from", "date_to", "min_amount", "max_amount", "categories", "accounts", "type", "sort_by"]
            ),
        }
    )

    _validate_date_range(service_filters.get("date_from"), service_filters.get("date_to"))
    search_term = merged_query.get("search") or (merged_query.get("original_query") if not merged_query.get("parsed") else "")
    return search_term, service_filters, merged_query


@router.get("", response_model=schemas.SearchResponse)
def search_transactions(
    q: str = Query(...),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    categories: Optional[str] = None,
    accounts: Optional[str] = None,
    transaction_type: Optional[schemas.TransactionType] = Query(default=None, alias="type"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: Optional[str] = Query(default=None, pattern="^(date|amount|created_at)_(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    search_service = SearchService(db)
    filters = _build_filters(
        date_from=date_from,
        date_to=date_to,
        min_amount=min_amount,
        max_amount=max_amount,
        categories=categories,
        accounts=accounts,
        transaction_type=transaction_type,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
    )
    return search_service.search(current_user.id, q, filters)


@router.get("/natural", response_model=schemas.NaturalSearchResponse)
def search_transactions_naturally(
    q: str = Query(...),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    categories: Optional[str] = None,
    accounts: Optional[str] = None,
    transaction_type: Optional[schemas.TransactionType] = Query(default=None, alias="type"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: Optional[str] = Query(default=None, pattern="^(date|amount|created_at)_(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    explicit_filters = _build_filters(
        date_from=date_from,
        date_to=date_to,
        min_amount=min_amount,
        max_amount=max_amount,
        categories=categories,
        accounts=accounts,
        transaction_type=transaction_type,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
    )
    parsed_query = PARSER.parse(q)
    search_term, service_filters, merged_query = _merge_natural_filters(parsed_query, explicit_filters)
    response = SearchService(db).search(current_user.id, search_term, service_filters)
    return {
        **response,
        "parsed_query": merged_query,
        "interpretation": PARSER.build_interpretation(merged_query),
    }


@router.post("/reindex", response_model=schemas.JobStatusResponse)
def reindex_search(
    current_user: User = Depends(get_current_user),
):
    job_id = job_queue.enqueue("reindex_search", _run_search_reindex, current_user.id, user_id=current_user.id)
    return serialize_job(job_queue.get_job(job_id))
