
import sys
import os
import asyncio
from typing import Optional

# Add current directory to path
sys.path.append(os.getcwd())

from services.bulk_upload_service import BulkUploadService
from services.deduplication_service import DeduplicationService
from database import SessionLocal

async def verify_skip_duplicates_logic(file_path):
    db = SessionLocal()
    service = BulkUploadService(db)
    owner_id = "e8838f2d-78b8-4dea-b99e-8d8ba548e853"
    
    with open(file_path, 'rb') as f:
        content = f.read()
    
    class MockFile:
        def __init__(self, content, filename):
            self.content = content
            self.filename = filename
        async def read(self):
            return self.content
    
    # 1. Test with skip_duplicates=True (Should be 421)
    mock_file = MockFile(content, os.path.basename(file_path))
    result_skip = await service.process_upload(
        mock_file, 
        owner_id=owner_id, 
        skip_duplicates=True
    )
    print(f"Skip=True -> Imported: {result_skip['count']}, Dups: {result_skip['duplicates_skipped']}, Total Parsed: {result_skip['total_parsed']}")
    
    # Clean DB between runs
    from sqlalchemy import text
    db.execute(text("DELETE FROM transactions"))
    db.execute(text("DELETE FROM accounts"))
    db.execute(text("DELETE FROM categories"))
    db.commit()

    # 2. Test with skip_duplicates=False (Should be 438)
    mock_file = MockFile(content, os.path.basename(file_path))
    result_no_skip = await service.process_upload(
        mock_file, 
        owner_id=owner_id, 
        skip_duplicates=False
    )
    print(f"Skip=False -> Imported: {result_no_skip['count']}, Dups: {result_no_skip['duplicates_skipped']}, Total Parsed: {result_no_skip['total_parsed']}")
    
    db.close()

if __name__ == "__main__":
    file_path = os.path.expanduser("~/Downloads/01-01-25_31-12-25.xls")
    asyncio.run(verify_skip_duplicates_logic(file_path))
