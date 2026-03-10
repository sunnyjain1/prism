from prism.services.bulk_upload_service import BulkUploadService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

# Use an in-memory database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def verify_registry():
    db = SessionLocal()
    service = BulkUploadService(db)
    
    print("Registered Importers:")
    for key, importer in service.importers.items():
        print(f" - {key}: {importer.name}")
        
    expected_importers = ["chase", "amex", "citi", "capital_one", "hdfc_bank", "money_manager"]
    for expected in expected_importers:
        found = any(expected in key for key in service.importers.keys())
        print(f"Check '{expected}': {'Found' if found else 'Missing'}")

if __name__ == "__main__":
    verify_registry()
