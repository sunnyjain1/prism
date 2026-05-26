"""Tests for SMS parser engine with real Indian bank SMS formats."""
import pytest
from datetime import datetime
from services.sms_parser import (
    parse_sms, extract_amount, extract_balance, extract_account,
    detect_transaction_type, detect_bank, is_transactional_sms,
    normalize_merchant, compute_dedup_hash, extract_merchant,
)


class TestAmountExtraction:
    def test_rs_format(self):
        assert extract_amount("Rs.1500.00 debited") == 1500.00

    def test_inr_format(self):
        assert extract_amount("INR 2,500.50 credited") == 2500.50

    def test_rupee_symbol(self):
        assert extract_amount("₹3,000 paid to merchant") == 3000.0

    def test_comma_separated(self):
        assert extract_amount("Rs 1,25,000 debited from your account") == 125000.0

    def test_amount_debited_pattern(self):
        assert extract_amount("debited for Rs.450") == 450.0

    def test_no_amount(self):
        assert extract_amount("Your OTP is 123456") is None


class TestBalanceExtraction:
    def test_avl_bal(self):
        assert extract_balance("Avl Bal Rs.45,000.50") == 45000.50

    def test_available_balance(self):
        assert extract_balance("Available Balance INR 1,20,000") == 120000.0

    def test_ac_bal(self):
        assert extract_balance("A/c bal: Rs.8,500") == 8500.0


class TestAccountExtraction:
    def test_ac_ending(self):
        assert extract_account("A/c ending 4321") == "4321"

    def test_masked_xx(self):
        assert extract_account("Account XX1234 debited") == "1234"

    def test_card_ending(self):
        assert extract_account("card ending 5678") == "5678"

    def test_masked_stars(self):
        assert extract_account("Ac ***9876 credited") == "9876"


class TestTransactionTypeDetection:
    def test_debited(self):
        assert detect_transaction_type("Rs.500 debited from your a/c") == "debit"

    def test_credited(self):
        assert detect_transaction_type("Rs.10,000 credited to your account") == "credit"

    def test_upi(self):
        assert detect_transaction_type("UPI payment of Rs.200 sent") == "upi"

    def test_atm(self):
        assert detect_transaction_type("ATM withdrawal Rs.5000") == "atm"

    def test_refund(self):
        assert detect_transaction_type("Refund of Rs.300 credited") == "refund"

    def test_failed(self):
        assert detect_transaction_type("Transaction failed for Rs.1000") == "failed"


class TestBankDetection:
    def test_hdfc_sender(self):
        assert detect_bank("HDFCBK", "") == "HDFC"

    def test_sbi_sender(self):
        assert detect_bank("SBIINB", "") == "SBI"

    def test_icici_sender(self):
        assert detect_bank("ICICIB", "") == "ICICI"

    def test_paytm_sender(self):
        assert detect_bank("Paytm", "") == "Paytm"


class TestMerchantExtraction:
    def test_to_merchant(self):
        result = extract_merchant("Rs.200 paid to Swiggy on 15-Jan")
        assert result == "Swiggy"

    def test_at_merchant(self):
        result = extract_merchant("Purchase at Amazon India Ref No 12345")
        assert result == "Amazon India"

    def test_upi_vpa(self):
        result = extract_merchant("VPA merchant@ybl on UPI")
        assert result is not None


class TestFullParsing:
    def test_hdfc_debit(self):
        sms = "HDFC Bank: Rs.1,500.00 debited from a/c **1234 on 15-01-25. Available bal Rs.45,000.50. Txn Ref No: 123456789"
        result = parse_sms("HDFCBK", sms)
        assert result.is_transactional
        assert result.amount == 1500.0
        assert result.transaction_type == "debit"
        assert result.bank_name == "HDFC"
        assert result.masked_account == "1234"
        assert result.available_balance == 45000.50
        assert result.confidence >= 0.7

    def test_sbi_credit(self):
        sms = "SBI: Rs.25,000 credited to your A/c XX5678 on 01Jan25. Avl Bal Rs.1,20,000. Ref No: SAL2025"
        result = parse_sms("SBIINB", sms)
        assert result.is_transactional
        assert result.amount == 25000.0
        assert result.transaction_type == "credit"
        assert result.bank_name == "SBI"
        assert result.masked_account == "5678"

    def test_upi_payment(self):
        sms = "Rs.200 sent to merchant@upi via UPI from A/c XX4321. UPI Ref: 501234567890. Bal: Rs.8,500"
        result = parse_sms("GPAY", sms)
        assert result.is_transactional
        assert result.amount == 200.0
        assert result.bank_name == "Google Pay"

    def test_credit_card_spend(self):
        sms = "Your ICICI Bank Credit Card XX9876 has been used for Rs.3,450 at AMAZON on 15-Jan-25. Avl Limit: Rs.1,50,000"
        result = parse_sms("ICICIB", sms)
        assert result.is_transactional
        assert result.amount == 3450.0
        assert result.bank_name == "ICICI"
        assert result.card_type == "credit_card"

    def test_otp_not_transactional(self):
        sms = "Your OTP for transaction is 123456. Do not share with anyone."
        result = parse_sms("HDFCBK", sms)
        assert not result.is_transactional

    def test_promo_not_transactional(self):
        sms = "Dear Customer, get pre-approved loan of Rs.5,00,000. Apply now!"
        result = parse_sms("SBIINB", sms)
        assert not result.is_transactional

    def test_atm_withdrawal(self):
        sms = "Rs.10,000 withdrawn from ATM. A/c XX2345 debited. Avl Bal: Rs.35,000. Ref: ATM123"
        result = parse_sms("HDFCBK", sms)
        assert result.is_transactional
        assert result.amount == 10000.0
        assert result.transaction_type == "atm"


class TestMerchantNormalization:
    def test_remove_pvt_ltd(self):
        assert normalize_merchant("Zomato Pvt Ltd") == "Zomato"

    def test_title_case(self):
        assert normalize_merchant("AMAZON INDIA") == "Amazon India"

    def test_none_input(self):
        assert normalize_merchant(None) is None

    def test_short_name(self):
        assert normalize_merchant("A") is None


class TestDeduplication:
    def test_same_inputs_same_hash(self):
        ts = datetime(2025, 1, 15, 10, 30)
        h1 = compute_dedup_hash("user1", 1500.0, ts, "REF123")
        h2 = compute_dedup_hash("user1", 1500.0, ts, "REF123")
        assert h1 == h2

    def test_different_amount_different_hash(self):
        ts = datetime(2025, 1, 15, 10, 30)
        h1 = compute_dedup_hash("user1", 1500.0, ts, "REF123")
        h2 = compute_dedup_hash("user1", 2000.0, ts, "REF123")
        assert h1 != h2

    def test_different_user_different_hash(self):
        ts = datetime(2025, 1, 15, 10, 30)
        h1 = compute_dedup_hash("user1", 1500.0, ts, "REF123")
        h2 = compute_dedup_hash("user2", 1500.0, ts, "REF123")
        assert h1 != h2


class TestNonTransactional:
    def test_kyc_message(self):
        assert not is_transactional_sms("HDFCBK", "Update your KYC details immediately.")

    def test_otp_message(self):
        assert not is_transactional_sms("SBIINB", "OTP for login is 345678. Valid for 5 mins.")

    def test_no_amount(self):
        assert not is_transactional_sms("HDFCBK", "Your account has been debited successfully.")
