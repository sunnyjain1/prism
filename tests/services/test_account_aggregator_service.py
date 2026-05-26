from services.account_aggregator_service import AccountAggregatorService


class TestAccountAggregatorService:
    def setup_method(self):
        self.service = AccountAggregatorService()
        self.service._consent_store.clear()

    def test_get_fi_types(self):
        types = self.service.get_supported_fi_types()
        assert len(types) == 8
        assert types[0]["type"] == "DEPOSIT"

    def test_initiate_consent(self):
        result = self.service.initiate_consent("user1", "9876543210", ["DEPOSIT", "CREDIT_SCORE"])
        assert result["success"] is True
        assert "consent_id" in result
        assert result["status"] == "pending"

    def test_check_consent_status(self):
        init = self.service.initiate_consent("user1", "9876543210", ["DEPOSIT"])
        status = self.service.check_consent_status(init["consent_id"])
        assert status["success"] is True
        assert status["status"].value == "pending"

    def test_simulate_approval(self):
        init = self.service.initiate_consent("user1", "9876543210", ["DEPOSIT"])
        self.service.simulate_consent_approval(init["consent_id"])
        status = self.service.check_consent_status(init["consent_id"])
        assert status["status"].value == "approved"

    def test_fetch_data_without_approval(self):
        init = self.service.initiate_consent("user1", "9876543210", ["DEPOSIT"])
        result = self.service.fetch_financial_data("user1", init["consent_id"], "DEPOSIT")
        assert result["success"] is False

    def test_fetch_data_after_approval(self):
        init = self.service.initiate_consent("user1", "9876543210", ["DEPOSIT"])
        self.service.simulate_consent_approval(init["consent_id"])
        result = self.service.fetch_financial_data("user1", init["consent_id"], "DEPOSIT")
        assert result["success"] is True
        assert result["status"] == "pending_integration"

    def test_revoke_consent(self):
        init = self.service.initiate_consent("user1", "9876543210", ["DEPOSIT"])
        self.service.revoke_consent(init["consent_id"])
        status = self.service.check_consent_status(init["consent_id"])
        assert status["status"].value == "revoked"
