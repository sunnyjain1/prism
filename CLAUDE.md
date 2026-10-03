# prism/ — Backend

FastAPI application (Python 3.11+). See root `CLAUDE.md` for overall architecture.

## Stack

| Concern | Library |
|---|---|
| Framework | FastAPI 0.128 (async) |
| ORM | SQLAlchemy 2.x (async session not used — sync sessions via `get_db`) |
| Migrations | Alembic 1.14 |
| Auth | python-jose (JWT HS256), passlib/bcrypt |
| Encryption | cryptography (Fernet) |
| Rate limiting | slowapi (starlette-based, per-IP) |
| Scheduler | APScheduler 3.x (BackgroundScheduler) |
| Background jobs | ThreadPoolExecutor via `services/job_queue.py` |
| PDF parsing | pdfplumber |
| Excel/CSV | pandas, openpyxl, xlrd |
| Search | Meilisearch (optional); SQL ILIKE fallback |
| Caching | Redis (optional); in-memory dict fallback |
| Error tracking | Sentry SDK |
| Email | smtplib (SMTP) |
| Google APIs | google-auth, google-api-python-client, google-auth-oauthlib |

## Directory Layout

```
prism/
├── main.py                  # FastAPI app factory, lifespan, middleware, router registration
├── models.py                # SQLAlchemy models (all financial entities)
├── user_models.py           # User + RefreshToken models (separated to avoid circular imports)
├── schemas.py               # Pydantic request/response schemas
├── database.py              # SQLAlchemy engine + SessionLocal + Base
├── auth_utils.py            # JWT encode/decode, password hashing
├── api/                     # Route handlers (one file per resource)
├── services/                # Business logic (one class per domain)
├── repositories/            # Data access layer (UserRepository, AccountRepository, etc.)
├── core/
│   ├── config.py            # Settings (reads env vars)
│   ├── dependencies.py      # FastAPI `Depends` factories (get_db, get_current_user)
│   ├── encryption.py        # Fernet encrypt/decrypt helpers
│   ├── exceptions.py        # Global exception handlers
│   ├── logging.py           # Structured logging setup
│   ├── middleware.py        # RequestContextMiddleware, RequestLoggingMiddleware
│   ├── metrics.py           # APIMetrics (request counters)
│   ├── rate_limit.py        # slowapi limiter instance
│   └── sentry.py            # Sentry init
├── alembic/                 # Migration scripts
│   └── versions/            # Migration files (never edit existing ones)
└── tests/                   # pytest test suite
```

## Layered Architecture

```
api/<resource>.py   →   services/<Domain>Service   →   repositories/<Domain>Repository
                                                              │
                                                         SQLAlchemy Session (models.py)
```

- **API layer**: input validation via Pydantic, auth via `Depends(get_current_user)`, calls service methods
- **Service layer**: business logic, orchestration, cache reads/writes, notification triggers
- **Repository layer**: SQL queries, paginated list helpers; `BaseRepository` has common CRUD
- Never put business logic in API handlers or repository methods

## Language & Code Style

- Python 3.11+. Use type hints on all function signatures.
- Return Pydantic schemas from API handlers — never return raw SQLAlchemy models directly.
- Async route handlers are fine but the DB session (`SessionLocal`) is synchronous. Do not mix asyncio with SQLAlchemy sync sessions.
- Use `Optional[X]` for nullable fields, not `X | None` (project uses the older form consistently).
- No linter config file present; follow PEP 8, keep lines ≤ 100 chars.
- Do not add `print()` statements; use `logging.getLogger(__name__)`.
- New routes must be registered in `main.py` with both `/api/v1/` and `/api/` prefixes.

## Environment Variables

| Variable | Default | Required in prod |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./prism.db` | Yes (PostgreSQL URL) |
| `SECRET_KEY` | — | Yes (app refuses to start if missing/default) |
| `PII_ENCRYPTION_KEY` | derived from `SECRET_KEY` | Recommended (distinct key for PII-at-rest encryption) |
| `ENVIRONMENT` | `development` | — |
| `ALLOW_MOCK_AUTH` | `false` | Never set true in prod |
| `GOOGLE_CLIENT_ID` | pre-set | Yes |
| `GOOGLE_CLIENT_SECRET` | `""` | For Gmail sync |
| `GMAIL_REDIRECT_URI` | `http://localhost:5173` | Set to prod URL |
| `REDIS_URL` | `""` | Optional |
| `MEILISEARCH_URL` | `http://localhost:7700` | Optional |
| `SEARCH_ENABLED` | `false` | Optional |
| `SENTRY_DSN` | `""` | Optional |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | — |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | — |
| `CACHE_TTL_DASHBOARD` | `300` | — |
| `AA_PROVIDER` | `setu` | — (selects AA impl: `setu`/`anumati`) |
| `AA_FIU_ID` | `""` | Yes (live FIU id) |
| `SETU_AA_BASE_URL` | `https://fiu-sandbox.setu.co` | Set to prod URL |
| `SETU_AA_CLIENT_ID` / `SETU_AA_CLIENT_SECRET` / `SETU_AA_PRODUCT_INSTANCE_ID` | `""` | Yes (for AA) |
| `AA_REDIRECT_URL` | `http://localhost:5173/aa/callback` | Set to app deep link / prod URL |
| `AA_WEBHOOK_SECRET` | `""` | For AA data-ready webhook |
| `AA_CONSENT_EXPIRY_DAYS` | `365` | — |
| `AA_FETCH_FROM_MONTHS` | `12` | — |
| `AA_SANDBOX_MODE` | `true` (non-prod) | Poll consent vs webhook |

## Running Locally

```bash
cd prism
source venv/bin/activate
uvicorn main:app --reload --port 8000
# API docs at http://localhost:8000/docs
```

## Database Migrations

```bash
cd prism
source venv/bin/activate

# Generate migration after model changes
alembic revision --autogenerate -m "describe what changed"

# Apply migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

Never edit existing migration files. Always generate a new migration for schema changes.

## Testing

Framework: **pytest** with SQLite in-memory-equivalent test DB (`sqlite:///./test.db`).

```bash
cd prism
source venv/bin/activate
pytest tests/ -v
pytest tests/test_auth_refresh.py -v   # single file
```

**Key fixtures in `tests/conftest.py`:**
- `client` — module-scoped `TestClient`, good for stateless endpoint tests
- `api_client` — function-scoped, wraps a real DB transaction that rolls back after each test; overrides `get_db` dependency; job queue runs synchronously (no threading)
- `cache_store` — monkeypatches `CacheService` with an in-memory dict
- `db_session` — raw SQLAlchemy session with rollback isolation

**Rules for writing tests:**
- Use `api_client` for any test that writes to the DB (full isolation via rollback)
- Use `client` for read-only endpoint smoke tests
- Use `cache_store` when testing cache invalidation
- Do not mock the DB — tests hit a real SQLite DB (learned from past incidents where mocked tests passed but prod migrations failed)
- Test file names: `test_<feature>_api.py` for HTTP-level tests, `test_<feature>.py` for unit tests
- Always register a user and log in before testing protected endpoints:
  ```python
  api_client.post("/auth/register", json={...})
  r = api_client.post("/auth/login", json={...})
  token = r.json()["access_token"]
  headers = {"Authorization": f"Bearer {token}"}
  ```

## Key Patterns

**Dependency injection:**
```python
from core.dependencies import get_current_user, get_db
router = APIRouter()

@router.get("/items")
def list_items(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    ...
```

**Pagination response:**
```python
# All list endpoints return PaginatedResponse[T] from schemas.py
return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)
```

**Cache invalidation pattern:**
```python
cache.delete_pattern(f"budget_progress:{user_id}*")
```

**Soft delete filter:**
```python
db.query(Account).filter(Account.owner_id == user_id, Account.is_deleted.is_(False))
```
