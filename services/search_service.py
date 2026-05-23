import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import asc, desc, or_
from sqlalchemy.orm import Session, joinedload

from core.config import settings
from models import Account, Category, Transaction

try:
    import meilisearch
    from meilisearch.errors import (
        MeilisearchApiError,
        MeilisearchCommunicationError,
        MeilisearchTimeoutError,
    )
except ImportError:  # pragma: no cover
    meilisearch = None
    MeilisearchApiError = MeilisearchCommunicationError = MeilisearchTimeoutError = Exception

logger = logging.getLogger(__name__)
_SEARCH_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="search-index")


class SearchService:
    SEARCHABLE_ATTRIBUTES = ["description", "merchant", "notes", "category_name", "account_name"]
    FILTERABLE_ATTRIBUTES = [
        "date",
        "amount",
        "type",
        "category_id",
        "account_id",
        "destination_account_id",
        "account_ids",
        "merchant",
    ]
    SORTABLE_ATTRIBUTES = ["date", "amount", "created_at"]
    _configured_indexes: set[str] = set()

    def __init__(self, db: Optional[Session] = None):
        self.db = db
        self.index_name = "transactions"
        self.client = None
        if settings.SEARCH_ENABLED and meilisearch is not None:
            self.client = meilisearch.Client(settings.MEILISEARCH_URL, settings.MEILISEARCH_API_KEY)

    @classmethod
    def queue_index_transaction(cls, user_id: str, transaction: dict[str, Any]) -> None:
        if not settings.SEARCH_ENABLED or meilisearch is None:
            return
        _SEARCH_EXECUTOR.submit(cls._safe_index_transaction, user_id, transaction)

    @classmethod
    def queue_delete_transaction(cls, user_id: str, transaction_id: str) -> None:
        if not settings.SEARCH_ENABLED or meilisearch is None:
            return
        _SEARCH_EXECUTOR.submit(cls._safe_delete_transaction, user_id, transaction_id)

    @classmethod
    def _safe_index_transaction(cls, user_id: str, transaction: dict[str, Any]) -> None:
        try:
            cls().index_transaction(user_id, transaction)
        except Exception as exc:  # pragma: no cover - defensive background protection
            logger.warning("Search indexing skipped for transaction %s: %s", transaction.get("id"), exc)

    @classmethod
    def _safe_delete_transaction(cls, user_id: str, transaction_id: str) -> None:
        try:
            cls().delete_transaction(user_id, transaction_id)
        except Exception as exc:  # pragma: no cover - defensive background protection
            logger.warning("Search delete skipped for transaction %s: %s", transaction_id, exc)

    @staticmethod
    def _serialize_datetime(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    @classmethod
    def build_document(cls, transaction: Transaction | dict[str, Any]) -> dict[str, Any]:
        if isinstance(transaction, dict):
            document = dict(transaction)
        else:
            document = {
                "id": transaction.id,
                "amount": float(transaction.amount),
                "type": transaction.type,
                "description": transaction.description,
                "merchant": transaction.merchant,
                "notes": transaction.notes,
                "date": cls._serialize_datetime(transaction.date),
                "timestamp": transaction.timestamp,
                "account_id": transaction.account_id,
                "account_name": transaction.account.name if transaction.account else None,
                "destination_account_id": transaction.destination_account_id,
                "category_id": transaction.category_id,
                "category_name": transaction.category.name if transaction.category else None,
                "created_at": cls._serialize_datetime(transaction.created_at),
                "updated_at": cls._serialize_datetime(transaction.updated_at),
            }

        transaction_type = document.get("type")
        if hasattr(transaction_type, "value"):
            transaction_type = transaction_type.value

        document["amount"] = float(document.get("amount", 0))
        document["type"] = str(transaction_type) if transaction_type is not None else ""
        document["date"] = cls._serialize_datetime(document.get("date"))
        document["created_at"] = cls._serialize_datetime(document.get("created_at"))
        document["updated_at"] = cls._serialize_datetime(document.get("updated_at"))
        document["account_ids"] = [
            account_id
            for account_id in [document.get("account_id"), document.get("destination_account_id")]
            if account_id
        ]
        return document

    def can_use_meilisearch(self) -> bool:
        return self.client is not None

    def is_available(self) -> bool:
        if not self.can_use_meilisearch():
            return False
        try:
            return bool(self.client.is_healthy())
        except (MeilisearchApiError, MeilisearchCommunicationError, MeilisearchTimeoutError):
            return False

    def get_index(self, user_id: str):
        if not self.can_use_meilisearch():
            raise RuntimeError("Meilisearch is not configured")

        index_name = f"{self.index_name}_{user_id}"
        index = self.client.index(index_name)

        try:
            self.client.get_index(index_name)
        except MeilisearchApiError as exc:
            if exc.code != "index_not_found":
                raise
            task = self.client.create_index(index_name, {"primaryKey": "id"})
            index.wait_for_task(task.task_uid, timeout_in_ms=10000)

        if index_name not in self._configured_indexes:
            tasks = [
                index.update_searchable_attributes(self.SEARCHABLE_ATTRIBUTES),
                index.update_filterable_attributes(self.FILTERABLE_ATTRIBUTES),
                index.update_sortable_attributes(self.SORTABLE_ATTRIBUTES),
            ]
            for task in tasks:
                index.wait_for_task(task.task_uid, timeout_in_ms=10000)
            self._configured_indexes.add(index_name)

        return index

    @staticmethod
    def _escape_filter_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _build_filter_expression(self, filters: Optional[dict[str, Any]]) -> Optional[str]:
        if not filters:
            return None

        expressions: list[str] = []

        date_from = filters.get("date_from")
        if date_from:
            expressions.append(f'date >= "{self._escape_filter_value(self._serialize_datetime(date_from) or "")}"')

        date_to = filters.get("date_to")
        if date_to:
            expressions.append(f'date <= "{self._escape_filter_value(self._serialize_datetime(date_to) or "")}"')

        min_amount = filters.get("min_amount")
        if min_amount is not None:
            expressions.append(f"amount >= {float(min_amount)}")

        max_amount = filters.get("max_amount")
        if max_amount is not None:
            expressions.append(f"amount <= {float(max_amount)}")

        categories = filters.get("categories") or []
        if categories:
            joined = ", ".join(f'"{self._escape_filter_value(category_id)}"' for category_id in categories)
            expressions.append(f"category_id IN [{joined}]")

        accounts = filters.get("accounts") or []
        if accounts:
            joined = ", ".join(f'"{self._escape_filter_value(account_id)}"' for account_id in accounts)
            expressions.append(f"account_ids IN [{joined}]")

        transaction_type = filters.get("type")
        if transaction_type:
            expressions.append(f'type = "{self._escape_filter_value(transaction_type)}"')

        return " AND ".join(expressions) if expressions else None

    @staticmethod
    def _get_total_from_result(result: dict[str, Any]) -> int:
        total = result.get("estimatedTotalHits")
        if total is None:
            total = result.get("totalHits")
        if total is None:
            total = len(result.get("hits", []))
        return int(total)

    @staticmethod
    def _coerce_datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    def _normalize_hit(self, hit: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": hit.get("id"),
            "amount": float(hit.get("amount", 0)),
            "type": hit.get("type"),
            "description": hit.get("description") or "",
            "merchant": hit.get("merchant"),
            "notes": hit.get("notes"),
            "date": hit.get("date"),
            "timestamp": hit.get("timestamp"),
            "account_id": hit.get("account_id"),
            "account_name": hit.get("account_name"),
            "destination_account_id": hit.get("destination_account_id"),
            "category_id": hit.get("category_id"),
            "category_name": hit.get("category_name"),
            "created_at": hit.get("created_at"),
            "updated_at": hit.get("updated_at"),
        }

    @staticmethod
    def _resolve_sort(filters: Optional[dict[str, Any]] = None) -> str:
        sort_by = (filters or {}).get("sort_by") or "date_desc"
        return sort_by if sort_by in {"date_desc", "date_asc", "amount_desc", "amount_asc", "created_at_desc", "created_at_asc"} else "date_desc"

    def _build_meilisearch_sort(self, filters: Optional[dict[str, Any]] = None) -> list[str]:
        sort_by = self._resolve_sort(filters)
        sort_field, direction = sort_by.rsplit("_", 1)
        return [f"{sort_field}:{direction}"]

    def _apply_sql_sort(self, db_query, filters: Optional[dict[str, Any]] = None):
        sort_by = self._resolve_sort(filters)
        column_map = {
            "date": Transaction.date,
            "amount": Transaction.amount,
            "created_at": Transaction.created_at,
        }
        sort_field, direction = sort_by.rsplit("_", 1)
        column = column_map.get(sort_field, Transaction.date)
        order_by_clause = asc(column) if direction == "asc" else desc(column)
        return db_query.order_by(order_by_clause)

    def _compute_aggregations(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        by_category: dict[str, int] = defaultdict(int)
        by_month: dict[str, float] = defaultdict(float)
        total_amount = 0.0

        for document in documents:
            amount = float(document.get("amount", 0))
            total_amount += amount

            category_name = document.get("category_name") or "Uncategorized"
            by_category[category_name] += 1

            transaction_date = self._coerce_datetime(document.get("date"))
            if transaction_date is not None:
                by_month[transaction_date.strftime("%Y-%m")] += amount

        count = len(documents)
        return {
            "total_amount": total_amount,
            "count": count,
            "by_category": dict(sorted(by_category.items())),
            "by_month": {key: value for key, value in sorted(by_month.items())},
            "average_amount": total_amount / count if count else 0.0,
        }

    def index_transaction(self, user_id: str, transaction: dict[str, Any]):
        if not self.can_use_meilisearch():
            return False
        index = self.get_index(user_id)
        index.add_documents([self.build_document(transaction)], primary_key="id")
        return True

    def index_transactions_bulk(self, user_id: str, transactions: list[dict[str, Any]]):
        if not self.can_use_meilisearch():
            return False
        documents = [self.build_document(transaction) for transaction in transactions]
        if not documents:
            return True
        index = self.get_index(user_id)
        index.add_documents(documents, primary_key="id")
        return True

    def _search_meilisearch(self, user_id: str, query: str, filters: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        index = self.get_index(user_id)
        limit = int((filters or {}).get("limit", 20))
        offset = int((filters or {}).get("offset", 0))
        filter_expression = self._build_filter_expression(filters)

        page_params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "sort": self._build_meilisearch_sort(filters),
        }
        if filter_expression:
            page_params["filter"] = filter_expression

        page_result = index.search(query or "", page_params)
        total = self._get_total_from_result(page_result)

        all_documents: list[dict[str, Any]] = []
        page_size = 1000
        current_offset = 0
        while current_offset < total:
            params: dict[str, Any] = {
                "limit": page_size,
                "offset": current_offset,
                "sort": self._build_meilisearch_sort(filters),
            }
            if filter_expression:
                params["filter"] = filter_expression
            batch_result = index.search(query or "", params)
            batch = batch_result.get("hits", [])
            if not batch:
                break
            all_documents.extend(batch)
            current_offset += len(batch)

        return {
            "hits": [self._normalize_hit(hit) for hit in page_result.get("hits", [])],
            "total": total,
            "query": query,
            "aggregations": self._compute_aggregations(all_documents),
        }

    def _build_sql_query(self, user_id: str, query: str, filters: Optional[dict[str, Any]] = None):
        if self.db is None:
            raise ValueError("A database session is required for SQL search fallback")

        filters = filters or {}
        db_query = (
            self.db.query(Transaction)
            .options(joinedload(Transaction.category), joinedload(Transaction.account))
            .outerjoin(Category, Transaction.category_id == Category.id)
            .outerjoin(Account, Transaction.account_id == Account.id)
            .filter(Transaction.owner_id == user_id)
        )

        if query:
            search_pattern = f"%{query}%"
            db_query = db_query.filter(
                or_(
                    Transaction.description.ilike(search_pattern),
                    Transaction.merchant.ilike(search_pattern),
                    Transaction.notes.ilike(search_pattern),
                    Category.name.ilike(search_pattern),
                    Account.name.ilike(search_pattern),
                )
            )

        date_from = filters.get("date_from")
        if date_from is not None:
            db_query = db_query.filter(Transaction.date >= date_from)

        date_to = filters.get("date_to")
        if date_to is not None:
            db_query = db_query.filter(Transaction.date <= date_to)

        min_amount = filters.get("min_amount")
        if min_amount is not None:
            db_query = db_query.filter(Transaction.amount >= float(min_amount))

        max_amount = filters.get("max_amount")
        if max_amount is not None:
            db_query = db_query.filter(Transaction.amount <= float(max_amount))

        categories = filters.get("categories") or []
        if categories:
            db_query = db_query.filter(Transaction.category_id.in_(categories))

        accounts = filters.get("accounts") or []
        if accounts:
            db_query = db_query.filter(
                or_(
                    Transaction.account_id.in_(accounts),
                    Transaction.destination_account_id.in_(accounts),
                )
            )

        transaction_type = filters.get("type")
        if transaction_type:
            db_query = db_query.filter(Transaction.type == transaction_type)

        return self._apply_sql_sort(db_query, filters)

    def _search_sql(self, user_id: str, query: str, filters: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        filters = filters or {}
        offset = int(filters.get("offset", 0))
        limit = int(filters.get("limit", 20))
        transactions = self._build_sql_query(user_id, query, filters).all()
        documents = [self.build_document(transaction) for transaction in transactions]
        paginated_documents = documents[offset:offset + limit]

        return {
            "hits": [self._normalize_hit(hit) for hit in paginated_documents],
            "total": len(documents),
            "query": query,
            "aggregations": self._compute_aggregations(documents),
        }

    def search(self, user_id: str, query: str, filters: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if self.can_use_meilisearch():
            try:
                return self._search_meilisearch(user_id, query, filters)
            except (MeilisearchApiError, MeilisearchCommunicationError, MeilisearchTimeoutError) as exc:
                logger.warning("Falling back to SQL search for user %s: %s", user_id, exc)

        return self._search_sql(user_id, query, filters)

    def delete_transaction(self, user_id: str, transaction_id: str):
        if not self.can_use_meilisearch():
            return False

        index_name = f"{self.index_name}_{user_id}"
        try:
            self.client.get_index(index_name)
        except MeilisearchApiError as exc:
            if exc.code == "index_not_found":
                return False
            raise

        self.client.index(index_name).delete_document(transaction_id)
        return True

    def reindex_all(self, user_id: str, db: Optional[Session] = None) -> int:
        if not self.can_use_meilisearch():
            return 0

        db = db or self.db
        if db is None:
            raise ValueError("A database session is required to reindex transactions")

        transactions = (
            db.query(Transaction)
            .options(joinedload(Transaction.category), joinedload(Transaction.account))
            .filter(Transaction.owner_id == user_id)
            .order_by(Transaction.date.desc())
            .all()
        )
        documents = [self.build_document(transaction) for transaction in transactions]
        index = self.get_index(user_id)

        delete_task = index.delete_all_documents()
        index.wait_for_task(delete_task.task_uid, timeout_in_ms=10000)
        if documents:
            add_task = index.add_documents(documents, primary_key="id")
            index.wait_for_task(add_task.task_uid, timeout_in_ms=10000)

        return len(documents)
