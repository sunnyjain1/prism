"""Tests for Notification Intelligence & Streaks services."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session

from services.notification_intelligence_service import NotificationIntelligenceService
from services.streaks_service import StreaksService


class TestNotificationIntelligence:
    def test_instantiation(self):
        db = MagicMock(spec=Session)
        service = NotificationIntelligenceService(db)
        assert service.db == db

    def test_generate_insights_returns_list(self):
        db = MagicMock(spec=Session)
        # Mock all queries to return empty
        db.query.return_value.filter.return_value.all.return_value = []
        db.query.return_value.filter.return_value.scalar.return_value = 0

        service = NotificationIntelligenceService(db)
        insights = service.generate_insights("test-user")
        assert isinstance(insights, list)

    def test_budget_threshold_detection(self):
        db = MagicMock(spec=Session)
        # Mock budget with 80% usage
        mock_budget = MagicMock()
        mock_budget.name = "Food"
        mock_budget.amount = 10000
        mock_budget.category_id = "cat-1"
        db.query.return_value.filter.return_value.all.return_value = [mock_budget]
        db.query.return_value.filter.return_value.scalar.return_value = 8500  # 85%

        service = NotificationIntelligenceService(db)
        insights = service._check_budget_thresholds("test-user")
        assert len(insights) == 1
        assert insights[0]["type"] == "budget_warning"
        assert "85%" in insights[0]["body"]

    def test_budget_exceeded(self):
        db = MagicMock(spec=Session)
        mock_budget = MagicMock()
        mock_budget.name = "Transport"
        mock_budget.amount = 5000
        mock_budget.category_id = "cat-2"
        db.query.return_value.filter.return_value.all.return_value = [mock_budget]
        db.query.return_value.filter.return_value.scalar.return_value = 6000  # 120%

        service = NotificationIntelligenceService(db)
        insights = service._check_budget_thresholds("test-user")
        assert len(insights) == 1
        assert insights[0]["type"] == "budget_exceeded"
        assert insights[0]["severity"] == "high"

    def test_weekly_summary_no_data(self):
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.scalar.return_value = 0

        service = NotificationIntelligenceService(db)
        insights = service._generate_weekly_summary("test-user")
        assert insights == []


class TestStreaksService:
    def test_instantiation(self):
        db = MagicMock(spec=Session)
        service = StreaksService(db)
        assert service.db == db

    def test_get_user_streaks_structure(self):
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.all.return_value = []
        db.query.return_value.filter.return_value.scalar.return_value = 0

        service = StreaksService(db)
        result = service.get_user_streaks("test-user")
        assert "logging_streak" in result
        assert "budget_streak" in result
        assert "achievements" in result
        assert "stats" in result

    def test_logging_streak_empty(self):
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.all.return_value = []

        service = StreaksService(db)
        result = service._get_logging_streak("test-user")
        assert result["current"] == 0
        assert result["longest"] == 0
        assert result["last_active"] is None

    def test_budget_streak_no_budgets(self):
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.all.return_value = []

        service = StreaksService(db)
        result = service._get_budget_streak("test-user")
        assert result["current_months"] == 0

    def test_engagement_stats(self):
        db = MagicMock(spec=Session)
        db.query.return_value.filter.return_value.scalar.return_value = 42

        service = StreaksService(db)
        result = service._get_engagement_stats("test-user")
        assert result["total_transactions"] == 42
