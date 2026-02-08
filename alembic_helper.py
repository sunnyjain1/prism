import os
import sys
from sqlalchemy import create_engine, inspect
from alembic.config import Config
from alembic import command
from core.config import settings

def auto_stamp():
    # Use the same database URL as the application
    url = os.getenv("DATABASE_URL", settings.SQLALCHEMY_DATABASE_URL)
    engine = create_engine(url)
    inspector = inspect(engine)
    
    # Check if 'users' table exists (signifies database is already initialized)
    tables = inspector.get_table_names()
    
    # Check if 'alembic_version' exists
    has_alembic = 'alembic_version' in tables
    has_users = 'users' in tables
    
    if has_users and not has_alembic:
        print("Existing database detected without migration history. Stamping with 'a283feea8927'...")
        alembic_cfg = Config("alembic.ini")
        # Ensure we set the correct URL in config if needed
        alembic_cfg.set_main_option("sqlalchemy.url", url)
        command.stamp(alembic_cfg, "a283feea8927")
        print("Database successfully stamped.")
    elif not has_users:
        print("Fresh database detected. Ready for full migration.")
    else:
        print("Migration history already present.")

if __name__ == "__main__":
    try:
        auto_stamp()
    except Exception as e:
        print(f"Warning: Auto-stamp helper failed: {e}")
        # We don't exit with error here to allow 'alembic upgrade' to try anyway
