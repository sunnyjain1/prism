import os
import sys
from sqlalchemy import create_engine, inspect
from alembic.config import Config
from alembic import command
from core.config import settings

def auto_stamp():
    # Use the same database URL as the application
    url = os.getenv("DATABASE_URL", settings.SQLALCHEMY_DATABASE_URL)
    
    # Handle Render's older 'postgres://' prefix for SQLAlchemy 2.0
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
        
    print(f"Connecting to database: {url.split('@')[-1] if '@' in url else url.split('://')[0] + '://...'}")
    
    try:
        engine = create_engine(url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
    except Exception as e:
        print(f"Critical Error: Could not connect to database or inspect tables: {e}")
        return

    print(f"Detected tables: {', '.join(tables) if tables else 'None'}")
    
    # Check if 'alembic_version' exists
    has_alembic = 'alembic_version' in tables
    has_users = 'users' in tables
    
    if has_users and not has_alembic:
        print("Existing database detected without migration history. Stamping with 'a283feea8927'...")
        try:
            # Ensure we are in the right directory for alembic.ini
            config_path = os.path.join(os.path.dirname(__file__), "alembic.ini")
            alembic_cfg = Config(config_path)
            alembic_cfg.set_main_option("sqlalchemy.url", url)
            command.stamp(alembic_cfg, "a283feea8927")
            print("Database successfully stamped at version a283feea8927.")
        except Exception as e:
            print(f"Error during stamping: {e}")
    elif has_alembic:
        print("Migration history already present. Skipping stamp.")
    elif not has_users:
        print("No existing schema detected. Ready for full migration.")

if __name__ == "__main__":
    try:
        auto_stamp()
    except Exception as e:
        print(f"Warning: Auto-stamp helper failed: {e}")
        # We don't exit with error here to allow 'alembic upgrade' to try anyway

