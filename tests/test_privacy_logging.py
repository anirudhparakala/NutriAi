"""
Unit tests for privacy logging (LOG_LEVEL=prod).

Tests sanitization of user data, metrics redaction, and mode switching.
"""
import pytest
import os
from unittest.mock import patch

from config.privacy import (
    is_production,
    sanitize_user_text,
    sanitize_metrics,
    log_with_privacy
)


class TestProductionDetection:
    """Test production mode detection."""

    @patch.dict('os.environ', {'LOG_LEVEL': 'dev'})
    def test_dev_mode_detected(self):
        """Test dev mode is detected."""
        # Need to reload module to pick up env change
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        assert not config.privacy.is_production()

    @patch.dict('os.environ', {'LOG_LEVEL': 'prod'})
    def test_prod_mode_detected(self):
        """Test prod mode is detected."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        assert config.privacy.is_production()

    @patch.dict('os.environ', {'LOG_LEVEL': 'PROD'})
    def test_case_insensitive(self):
        """Test LOG_LEVEL is case-insensitive."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        assert config.privacy.is_production()


class TestUserTextSanitization:
    """Test user text sanitization."""

    @patch.dict('os.environ', {'LOG_LEVEL': 'dev'})
    def test_dev_mode_no_sanitization(self):
        """Test no sanitization in dev mode."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        text = "Chicken breast with rice"
        result = config.privacy.sanitize_user_text(text)
        assert result == text

    @patch.dict('os.environ', {'LOG_LEVEL': 'prod'})
    def test_prod_mode_redacts_long_text(self):
        """Test long text is redacted in prod mode."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        text = "A very long user input that contains sensitive information about their meal choices"
        result = config.privacy.sanitize_user_text(text, max_length=20)

        assert "[REDACTED" in result
        assert len(result) < len(text)

    @patch.dict('os.environ', {'LOG_LEVEL': 'prod'})
    def test_prod_mode_short_text_truncated(self):
        """Test short text is truncated in prod mode."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        text = "Chicken"
        result = config.privacy.sanitize_user_text(text, max_length=50)

        # Should be truncated but not fully redacted
        assert len(result) <= 50 + 3  # +3 for "..."


class TestMetricsSanitization:
    """Test metrics sanitization."""

    @patch.dict('os.environ', {'LOG_LEVEL': 'dev'})
    def test_dev_mode_metrics_unchanged(self):
        """Test metrics unchanged in dev mode."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        metrics = {
            "event": "usda_match",
            "query": "chicken breast",
            "fdc_id": 123456,
            "score": 0.95
        }

        result = config.privacy.sanitize_metrics(metrics)
        assert result == metrics

    @patch.dict('os.environ', {'LOG_LEVEL': 'prod'})
    def test_prod_mode_redacts_sensitive_fields(self):
        """Test sensitive fields are redacted in prod mode."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        metrics = {
            "event": "usda_match",
            "query": "chicken breast",
            "description": "Chicken, breast, grilled",
            "ingredient": "chicken",
            "fdc_id": 123456,
            "score": 0.95
        }

        result = config.privacy.sanitize_metrics(metrics)

        # Metadata preserved
        assert result["event"] == "usda_match"
        assert result["fdc_id"] == 123456
        assert result["score"] == 0.95

        # User data redacted
        assert result["query"] == "[REDACTED]"
        assert result["description"] == "[REDACTED]"
        assert result["ingredient"] == "[REDACTED]"

    @patch.dict('os.environ', {'LOG_LEVEL': 'prod'})
    def test_prod_mode_redacts_dish_names(self):
        """Test dish names are redacted."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        metrics = {
            "event": "combo_sanity_fail",
            "dish": "McDonald's Big Mac Meal",
            "category": "diet_beverage_kcal"
        }

        result = config.privacy.sanitize_metrics(metrics)

        assert result["dish"] == "[REDACTED]"
        assert result["category"] == "diet_beverage_kcal"

    @patch.dict('os.environ', {'LOG_LEVEL': 'prod'})
    def test_prod_mode_preserves_counts_and_rates(self):
        """Test counts and rates are preserved."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        metrics = {
            "event": "portion_resolver",
            "tiers": {
                "user_vision": 2,
                "brand_size": 1,
                "usda_portions": 3,
                "category_heuristic": 1
            },
            "tier_rates_pct": {
                "category_heuristic": 14.3
            }
        }

        result = config.privacy.sanitize_metrics(metrics)

        # All counts and rates should be preserved
        assert result["tiers"] == metrics["tiers"]
        assert result["tier_rates_pct"] == metrics["tier_rates_pct"]


class TestLogWithPrivacy:
    """Test privacy-aware logging function."""

    @patch.dict('os.environ', {'LOG_LEVEL': 'dev'})
    def test_dev_mode_logs_full_data(self, capsys):
        """Test dev mode logs complete data."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        user_data = {
            "query": "chicken breast",
            "fdc_id": 123456
        }

        config.privacy.log_with_privacy("Test message", user_data)

        captured = capsys.readouterr()
        assert "chicken breast" in captured.out
        assert "123456" in captured.out

    @patch.dict('os.environ', {'LOG_LEVEL': 'prod'})
    def test_prod_mode_sanitizes_data(self, capsys):
        """Test prod mode sanitizes user data."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        user_data = {
            "query": "chicken breast",
            "description": "Grilled chicken",
            "fdc_id": 123456
        }

        config.privacy.log_with_privacy("Test message", user_data)

        captured = capsys.readouterr()
        # Should redact query and description
        assert "[REDACTED]" in captured.out
        # Should preserve fdc_id
        assert "123456" in captured.out

    def test_log_without_user_data(self, capsys):
        """Test logging without user data works."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        config.privacy.log_with_privacy("Simple message")

        captured = capsys.readouterr()
        assert "Simple message" in captured.out


class TestFieldClassification:
    """Test correct classification of sensitive vs. metadata fields."""

    @patch.dict('os.environ', {'LOG_LEVEL': 'prod'})
    def test_sensitive_fields_list(self):
        """Test comprehensive list of sensitive fields."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        sensitive_fields = ["text", "query", "description", "dish", "ingredient_name", "item", "ingredient"]

        for field in sensitive_fields:
            metrics = {
                "event": "test",
                field: "sensitive data",
                "fdc_id": 123
            }
            result = config.privacy.sanitize_metrics(metrics)
            assert result[field] == "[REDACTED]", f"Field '{field}' should be redacted"

    @patch.dict('os.environ', {'LOG_LEVEL': 'prod'})
    def test_metadata_fields_preserved(self):
        """Test metadata fields are preserved."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        metadata_fields = {
            "event": "test_event",
            "fdc_id": 123456,
            "score": 0.95,
            "candidates": 3,
            "selected_fdc_id": 789,
            "backend": "redis",
            "hit": True,
            "tier": "brand_size"
        }

        result = config.privacy.sanitize_metrics(metadata_fields)

        # All metadata should be preserved
        for key, value in metadata_fields.items():
            assert result[key] == value


class TestProductionDeployment:
    """Test production deployment scenarios."""

    @patch.dict('os.environ', {'LOG_LEVEL': 'prod'})
    def test_no_pii_in_standard_metrics(self):
        """Test standard metrics don't leak PII in prod."""
        import importlib
        import config.privacy
        importlib.reload(config.privacy)

        # Simulate a real metrics payload
        metrics = {
            "event": "usda_tiebreak",
            "invoked": True,
            "query": "user's personal meal description",
            "candidates": 3,
            "fdc_id": 123456
        }

        result = config.privacy.sanitize_metrics(metrics)

        # No user text should be visible
        assert "user's personal meal description" not in str(result)
        assert result["query"] == "[REDACTED]"
        # Metadata still usable for analytics
        assert result["candidates"] == 3
        assert result["fdc_id"] == 123456
