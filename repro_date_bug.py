
import sys
import os
from datetime import datetime
import pandas as pd

# Add current directory to path
sys.path.append(os.getcwd())

from services.importers.base_importer import BaseImporter

class MockImporter(BaseImporter):
    def parse(self, content, filename=None): pass
    def can_handle(self, content, filename=None): return True

def test_date_parsing():
    importer = MockImporter("Mock", ["csv"])
    
    # Test cases
    test_cases = [
        ("01/05/2025", datetime(2025, 5, 1)), # Should be May 1st, not Jan 5th
        ("21/09/2025 10:05:46", datetime(2025, 9, 21, 10, 5, 46)),
        ("2025-02-14", datetime(2025, 2, 14)),
    ]
    
    all_passed = True
    for input_val, expected in test_cases:
        actual = importer.parse_date(input_val)
        if actual != expected:
            print(f"FAILED: Input '{input_val}' -> Expected {expected}, got {actual}")
            all_passed = False
        else:
            print(f"PASSED: Input '{input_val}' -> {actual}")
            
    if all_passed:
        print("\nAll date parsing tests passed!")
    else:
        sys.exit(1)

if __name__ == "__main__":
    test_date_parsing()
