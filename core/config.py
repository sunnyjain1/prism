import os

from core.env import load_local_env

load_local_env()


class Settings:
    DEFAULT_SECRET_KEY_PLACEHOLDER = "change-me-in-production"
    DEVELOPMENT_SECRET_KEY = "prism-development-secret-key"
    LEGACY_INSECURE_SECRET_KEY = "b304c4f03932e67a7392c64b5478bfc180f68254"

    def __init__(self) -> None:
        self.PROJECT_NAME: str = "Prism API"
        self.APP_VERSION: str = os.environ.get("APP_VERSION", "1.0.0")
        self.ENVIRONMENT: str = (os.environ.get("ENVIRONMENT", "development") or "development").strip().lower()
        self.DEBUG: bool = self._get_bool("DEBUG", default=self.ENVIRONMENT == "development")

        self.SQLALCHEMY_DATABASE_URL: str = os.environ.get(
            "DATABASE_URL",
            "sqlite:///./prism.db"  # Defaulting back to SQLite for stability/portability
        )
        if self.SQLALCHEMY_DATABASE_URL.startswith("postgresql"):
            # Heuristic: If we are in local dev and Postgres seems missing, fallback
            # However, for now, let's just make SQLite the default if not explicitly set
            pass

        secret_key = os.environ.get("SECRET_KEY")
        if self.ENVIRONMENT == "development" and not secret_key:
            # Keep local imports working without silently reusing a production-safe default.
            self.SECRET_KEY: str = self.DEVELOPMENT_SECRET_KEY
        else:
            self.SECRET_KEY = secret_key or ""

        self.ALGORITHM: str = "HS256"
        self.ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
        self.REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

        # CORS
        raw_origins = os.environ.get(
            "ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:3000"
        ).split(",")
        self.ALLOWED_ORIGINS: list[str] = [o.strip().rstrip('/') for o in raw_origins if o.strip()]

        # Auth
        self.GOOGLE_CLIENT_ID: str = os.environ.get(
            "GOOGLE_CLIENT_ID",
            "252443340779-4u7edgsne2m72dkjjggs4gedqmvi95d0.apps.googleusercontent.com"
        )
        allow_mock_auth = self._get_bool("ALLOW_MOCK_AUTH", default=False)
        # Mock auth must be explicitly enabled and is never allowed in production.
        self.ALLOW_MOCK_AUTH: bool = allow_mock_auth and self.ENVIRONMENT != "production"
        self.MOCK_TOKEN: str = os.environ.get("MOCK_TOKEN", "dev-token-prism")

        # Gmail API (for auto-sync)
        self.GOOGLE_CLIENT_SECRET: str = os.environ.get("GOOGLE_CLIENT_SECRET", "")
        self.GMAIL_REDIRECT_URI: str = os.environ.get(
            "GMAIL_REDIRECT_URI",
            "http://localhost:5173"
        )
        self.GMAIL_SCOPES: list[str] = ["https://www.googleapis.com/auth/gmail.readonly"]
        self.GMAIL_OAUTH_STATE_EXPIRE_MINUTES: int = int(
            os.environ.get("GMAIL_OAUTH_STATE_EXPIRE_MINUTES", "10")
        )

        self.AUTH_RATE_LIMITS: dict[str, str] = {
            "login": os.environ.get("AUTH_LOGIN_RATE_LIMIT", "100/minute"),
            "register": os.environ.get("AUTH_REGISTER_RATE_LIMIT", "50/minute"),
            "google": os.environ.get("AUTH_GOOGLE_RATE_LIMIT", "100/minute"),
        }

        self.MEILISEARCH_URL: str = os.getenv("MEILISEARCH_URL", "http://localhost:7700")
        self.MEILISEARCH_API_KEY: str = os.getenv("MEILISEARCH_API_KEY", "")
        self.SEARCH_ENABLED: bool = os.getenv("SEARCH_ENABLED", "false").lower() == "true"
        self.REDIS_URL: str = os.getenv("REDIS_URL", "")
        self.CACHE_TTL_DASHBOARD: int = int(os.getenv("CACHE_TTL_DASHBOARD", "300"))
        self.CACHE_TTL_SUMMARY: int = int(os.getenv("CACHE_TTL_SUMMARY", "600"))
        self.SENTRY_DSN: str = os.getenv("SENTRY_DSN", "").strip()

        self.validate()

    @staticmethod
    def _get_bool(name: str, default: bool = False) -> bool:
        value = os.environ.get(name)
        if value is None:
            return default
        return value.strip().lower() == "true"

    def validate(self) -> None:
        invalid_secret_keys = {
            "",
            self.DEFAULT_SECRET_KEY_PLACEHOLDER,
            self.LEGACY_INSECURE_SECRET_KEY,
        }
        if self.ENVIRONMENT != "development":
            invalid_secret_keys.add(self.DEVELOPMENT_SECRET_KEY)

        if self.SECRET_KEY in invalid_secret_keys:
            raise ValueError(
                "SECRET_KEY must be set to a non-default value. "
                "Only ENVIRONMENT=development may omit SECRET_KEY to use the local development fallback."
            )


settings = Settings()
