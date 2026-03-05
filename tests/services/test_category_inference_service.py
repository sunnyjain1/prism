"""
Tests for CategoryInferenceService.
"""
import sys
import os
import pytest

# Add prism directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from services.category_inference_service import CategoryInferenceService
from schemas import TransactionType


@pytest.fixture
def service():
    return CategoryInferenceService()


# ── Expense category inference ───────────────────────────────────────────

class TestExpenseInference:
    def test_food_swiggy(self, service):
        result = service.infer_category("UPI - Swiggy", TransactionType.expense)
        assert result == "Food & Dining"

    def test_food_zomato(self, service):
        result = service.infer_category("UPI - Zomato Online Order", TransactionType.expense)
        assert result == "Food & Dining"

    def test_food_restaurant(self, service):
        result = service.infer_category("Bill Payment - Restaurant XYZ", TransactionType.expense)
        assert result == "Food & Dining"

    def test_food_blinkit(self, service):
        result = service.infer_category("UPI - Blinkit Grocery", TransactionType.expense)
        assert result == "Food & Dining"

    def test_grocery_dmart(self, service):
        result = service.infer_category("UPI - DMart Store", TransactionType.expense)
        assert result == "Groceries"

    def test_transportation_uber(self, service):
        result = service.infer_category("UPI - Uber India", TransactionType.expense)
        assert result == "Transportation"

    def test_transportation_fuel(self, service):
        result = service.infer_category("UPI - Indian Oil Petrol Pump", TransactionType.expense)
        assert result == "Transportation"

    def test_transportation_metro(self, service):
        result = service.infer_category("Metro Recharge", TransactionType.expense)
        assert result == "Transportation"

    def test_shopping_amazon(self, service):
        result = service.infer_category("UPI - Amazon Pay", TransactionType.expense)
        assert result == "Shopping"

    def test_shopping_flipkart(self, service):
        result = service.infer_category("NEFT - Flipkart Internet Pvt Ltd", TransactionType.expense)
        assert result == "Shopping"

    def test_entertainment_netflix(self, service):
        result = service.infer_category("ACH Debit - Netflix", TransactionType.expense)
        assert result == "Entertainment"

    def test_entertainment_spotify(self, service):
        result = service.infer_category("UPI - Spotify India", TransactionType.expense)
        assert result == "Entertainment"

    def test_utilities_electricity(self, service):
        result = service.infer_category("Bill Payment - Electricity Board", TransactionType.expense)
        assert result == "Utilities"

    def test_utilities_jio(self, service):
        result = service.infer_category("UPI - Jio Recharge", TransactionType.expense)
        assert result == "Utilities"

    def test_housing_rent(self, service):
        result = service.infer_category("NEFT - Monthly Rent Payment", TransactionType.expense)
        assert result == "Housing"

    def test_healthcare_apollo(self, service):
        result = service.infer_category("UPI - Apollo Pharmacy", TransactionType.expense)
        assert result == "Healthcare"

    def test_insurance_lic(self, service):
        result = service.infer_category("ACH Debit - LIC Premium", TransactionType.expense)
        assert result == "Insurance"

    def test_loan_emi(self, service):
        result = service.infer_category("ACH Debit - EMI HDFC Ltd", TransactionType.expense)
        assert result == "Loan & EMI"

    def test_education_udemy(self, service):
        result = service.infer_category("UPI - Udemy Course", TransactionType.expense)
        assert result == "Education"

    def test_fitness_gym(self, service):
        result = service.infer_category("UPI - Gym Membership", TransactionType.expense)
        assert result == "Fitness"

    def test_subscriptions_cred(self, service):
        result = service.infer_category("UPI - CRED Club", TransactionType.expense)
        assert result == "Subscriptions"

    def test_investments_zerodha(self, service):
        result = service.infer_category("UPI - Zerodha Broking", TransactionType.expense)
        assert result == "Investments"


# ── Income category inference ────────────────────────────────────────────

class TestIncomeInference:
    def test_salary(self, service):
        result = service.infer_category("ACH Credit - Monthly Salary", TransactionType.income)
        assert result == "Salary"

    def test_interest(self, service):
        result = service.infer_category("Interest Credit", TransactionType.income)
        assert result == "Investments"

    def test_dividend(self, service):
        result = service.infer_category("Dividend Payout", TransactionType.income)
        assert result == "Investments"

    def test_refund(self, service):
        result = service.infer_category("Amazon Refund", TransactionType.income)
        assert result == "Refunds"

    def test_cashback(self, service):
        result = service.infer_category("UPI Cashback", TransactionType.income)
        assert result == "Refunds"

    def test_freelance(self, service):
        result = service.infer_category("Client Payment - Consulting", TransactionType.income)
        assert result == "Freelance"


# ── Edge cases ───────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_description(self, service):
        result = service.infer_category("", TransactionType.expense)
        assert result is None

    def test_none_description(self, service):
        result = service.infer_category(None, TransactionType.expense)
        assert result is None

    def test_unknown_description(self, service):
        result = service.infer_category("NEFT - XYZABC123 Random", TransactionType.expense)
        assert result is None

    def test_transfer_type_skipped(self, service):
        """Transfers should never be categorized."""
        result = service.infer_category("UPI - Swiggy", TransactionType.transfer)
        assert result is None

    def test_case_insensitive(self, service):
        result = service.infer_category("UPI - SWIGGY ORDER", TransactionType.expense)
        assert result == "Food & Dining"

    def test_income_keyword_not_matched_for_expense(self, service):
        """Income-only keywords should not match when tx_type is expense."""
        result = service.infer_category("Salary advance", TransactionType.expense)
        assert result is None

    def test_expense_keyword_not_matched_for_income(self, service):
        """Expense-only keywords should not match when tx_type is income."""
        result = service.infer_category("UPI - Uber trip", TransactionType.income)
        assert result is None


# ── get_category_color ───────────────────────────────────────────────────

class TestGetCategoryColor:
    def test_known_category_returns_color(self, service):
        color = service.get_category_color("Food & Dining")
        assert color == "#ef4444"

    def test_unknown_category_returns_none(self, service):
        color = service.get_category_color("Nonexistent Category")
        assert color is None

    def test_case_insensitive_color_lookup(self, service):
        color = service.get_category_color("food & dining")
        assert color == "#ef4444"
