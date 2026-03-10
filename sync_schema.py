import sys
import os
from sqlalchemy import create_engine, inspect, text
from database import Base, SQLALCHEMY_DATABASE_URL
import models, user_models

def sync_schema():
    print(f"Connecting to database: {SQLALCHEMY_DATABASE_URL}")
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    inspector = inspect(engine)
    
    # 1. Ensure all tables exist
    Base.metadata.create_all(bind=engine)
    print("Checked/Created all tables.")
    
    # 2. Check for missing columns in existing tables
    # (SQLAlchemy create_all doesn't add columns to existing tables)
    
    tables_to_check = {
        'accounts': {
            'is_deleted': 'BOOLEAN NOT NULL DEFAULT 0',
            'deleted_at': 'DATETIME',
            'billing_cycle_day': 'INTEGER DEFAULT 1',
            'credit_limit': 'FLOAT'
        },
        'transactions': {
            'notes': 'VARCHAR'
        },
        'account_sync_configs': {
            'encrypted_pdf_password': 'VARCHAR'
        }
    }
    
    with engine.connect() as conn:
        for table_name, columns in tables_to_check.items():
            if table_name not in inspector.get_table_names():
                continue
                
            existing_columns = [c['name'] for c in inspector.get_columns(table_name)]
            
            for col_name, col_type in columns.items():
                if col_name not in existing_columns:
                    print(f"Adding missing column {col_name} to table {table_name}")
                    try:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
                    except Exception as e:
                        print(f"Error adding column {col_name}: {e}")
        
        # Special case: remove subject_match_pattern if it exists (Phase 5 cleanup)
        sync_cols = [c['name'] for c in inspector.get_columns('account_sync_configs')]
        if 'subject_match_pattern' in sync_cols:
            print("Cleanup: subject_match_pattern found in account_sync_configs. "
                  "SQLite doesn't support DROP COLUMN easily, so we will leave it for now or recommend a full migration.")
            # Actually SQLite 3.35.0+ supports it, but for compatibility we can just leave it.
            # Apps usually ignore extra columns.
            pass

    print("Schema synchronization complete.")

if __name__ == "__main__":
    # Add project root to sys.path
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    sync_schema()
