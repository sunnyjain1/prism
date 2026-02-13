import sys
import os
import pandas as pd
from datetime import datetime

# Add prism directory to path
sys.path.append(os.path.abspath('prism'))

from services.importers.money_manager_importer import MoneyManagerImporter
from schemas import TransactionType

def test_mapping():
    importer = MoneyManagerImporter()
    
    # Mock row data based on sample file
    # Row 1: Expense
    row_expense = pd.Series({
        'Date': '15/12/2025',
        'Account': 'HDFC',
        'Category': 'Insurance',
        'Subcategory': 'nan',
        'Note': 'Lic policy premium',
        'Income/Expense': 'Expense',
        'Description': 'Should be notes',
        'Amount': 7788.0,
        'Currency': 'INR'
    })
    
    # Row 2: Income
    row_income = pd.Series({
        'Date': '16/12/2025',
        'Account': 'HDFC',
        'Category': 'Salary',
        'Subcategory': 'nan',
        'Note': 'Monthly Salary',
        'Income/Expense': 'Income',
        'Description': 'Employer name',
        'Amount': 50000.0,
        'Currency': 'INR'
    })
    
    # Row 3: Transfer
    row_transfer = pd.Series({
        'Date': '16/05/2025 20:20:40',
        'Account': 'HDFC',
        'Category': 'HDFC Rupay card',
        'Subcategory': 'nan',
        'Note': 'Card payment',
        'Income/Expense': 'Transfer-Out',
        'Description': 'ATM Transfer',
        'Amount': 12541.0,
        'Currency': 'INR'
    })
    
    column_mapping = {
        'date': 'Date',
        'amount': 'Amount',
        'type': 'Income/Expense',
        'description': 'Description',
        'account': 'Account',
        'category': 'Category',
        'subcategory': 'Subcategory',
        'note': 'Note',
        'currency': 'Currency'
    }
    
    # Test Expense
    tx_exp = importer._parse_single_transaction(row_expense, column_mapping, 1)
    assert tx_exp.type == TransactionType.expense
    assert tx_exp.description == 'Lic policy premium' # From 'Note'
    assert 'Should be notes' in tx_exp.notes # From 'Description'
    assert tx_exp._import_category == 'Insurance'
    
    # Test Income
    tx_inc = importer._parse_single_transaction(row_income, column_mapping, 2)
    assert tx_inc.type == TransactionType.income
    assert tx_inc.description == 'Monthly Salary'
    assert 'Employer name' in tx_inc.notes
    
    # Test Transfer
    tx_trans = importer._parse_single_transaction(row_transfer, column_mapping, 3)
    assert tx_trans.type == TransactionType.transfer
    assert tx_trans.description == 'Card payment'
    assert tx_trans._import_destination_account == 'HDFC Rupay card'
    assert not hasattr(tx_trans, '_import_category') or tx_trans._import_category is None
    
    print("All mapping tests passed!")

if __name__ == "__main__":
    test_mapping()
