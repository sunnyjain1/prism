import os

class Settings:
    PROJECT_NAME: str = "Prism API"
    SQLALCHEMY_DATABASE_URL: str = os.environ.get(
        "DATABASE_URL",
        "sqlite:///./prism.db" # Defaulting back to SQLite for stability/portability
    )
    if SQLALCHEMY_DATABASE_URL.startswith("postgresql"):
        # Heuristic: If we are in local dev and Postgres seems missing, fallback
        # However, for now, let's just make SQLite the default if not explicitly set
        pass
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "b304c4f03932e67a7392c64b5478bfc180f68254")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # CORS
    raw_origins = os.environ.get(
        "ALLOWED_ORIGINS", 
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:3000"
    ).split(",")
    ALLOWED_ORIGINS: list[str] = [o.strip().rstrip('/') for o in raw_origins if o.strip()]
    
    # Auth
    GOOGLE_CLIENT_ID: str = os.environ.get(
        "GOOGLE_CLIENT_ID", 
        "252443340779-4u7edgsne2m72dkjjggs4gedqmvi95d0.apps.googleusercontent.com"
    )
    ALLOW_MOCK_AUTH: bool = os.environ.get("ALLOW_MOCK_AUTH", "true").lower() == "true"
    MOCK_TOKEN: str = "dev-token-prism"
    
    # Gmail API (for auto-sync)
    GOOGLE_CLIENT_SECRET: str = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GMAIL_REDIRECT_URI: str = os.environ.get(
        "GMAIL_REDIRECT_URI",
        "http://localhost:5173/accounts"
    )
    GMAIL_SCOPES: list[str] = ["https://www.googleapis.com/auth/gmail.readonly"]

settings = Settings()
