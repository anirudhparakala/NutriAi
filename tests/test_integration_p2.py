"""
Integration tests for P2 features.

Tests interaction between multiple components:
- Vision -> Cache -> QA pipeline
- USDA -> Tiebreaker -> Sanity gates
- Multilingual -> Canonicalization -> USDA matching
"""
import pytest
import json
import tempfile
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from core.vision_estimator import estimate, filter_critical_questions
from core.qa_manager import generate_final_calculation
from core.normalize import canonicalize_name
from integrations import usda_client
from core.schemas import VisionEstimate, Ingredient, ClarificationQuestion


class TestVisionCachingIntegration:
    """Test vision output caching with idempotency."""

    @patch('core.vision_estimator.run_with_tools')
    def test_vision_cache_hit_returns_cached_result(self, mock_run_tools):
        """Test that cached vision output is reused."""
        # Create a simple test image (1x1 PNG)
        from PIL import Image
        import io
        img = Image.new('RGB', (1, 1), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        test_image = img_bytes.getvalue()

        # Mock LLM response
        response_json = json.dumps({
            "dish": "Test Meal",
            "portion_guess_g": 500,
            "ingredients": [
                {"name": "chicken", "amount": 150, "unit": "g", "source": "vision", "portion_label": None, "notes": None}
            ],
            "critical_questions": []
        })
        mock_run_tools.return_value = (response_json, 0)

        # Mock model
        mock_model = MagicMock()

        # First call - should hit LLM
        result1, calls1 = estimate(test_image, mock_model)
        assert result1 is not None
        assert calls1 == 0  # Counts tool calls during LLM invocation

        # Second call with same image - should hit cache
        result2, calls2 = estimate(test_image, mock_model)
        assert result2 is not None
        assert calls2 == 0  # Cache hit, 0 tool calls
        assert result1.dish == result2.dish

        # run_with_tools should only be called once (first time)
        assert mock_run_tools.call_count == 1


class TestQuestionFilteringIntegration:
    """Test question budget and impact gating."""

    def test_filter_applies_calorie_threshold(self):
        """Test filtering based on calorie impact threshold."""
        questions = [
            {"id": "q1", "text": "High impact?", "impact_score": 0.5, "options": ["a", "b"], "default": "a"},
            {"id": "q2", "text": "Low impact?", "impact_score": 0.05, "options": ["a", "b"], "default": "a"},
            {"id": "q3", "text": "Medium impact?", "impact_score": 0.3, "options": ["a", "b"], "default": "a"}
        ]

        # Small meal (200g) - only high impact questions should pass
        result = filter_critical_questions(questions, portion_guess_g=200, max_questions=2)

        # 200g * 2 kcal/g = 400 kcal estimated
        # q1: 0.5 * 400 = 200 kcal impact (>= 120 threshold) ✓
        # q2: 0.05 * 400 = 20 kcal impact (< 120 threshold) ✗
        # q3: 0.3 * 400 = 120 kcal impact (>= 120 threshold) ✓

        assert len(result) <= 2
        # Should include q1 and q3 (highest impact)
        question_ids = [q["id"] for q in result]
        assert "q1" in question_ids

    def test_filter_respects_max_questions_budget(self):
        """Test max 2 questions budget is enforced."""
        questions = [
            {"id": f"q{i}", "text": f"Question {i}", "impact_score": 0.6, "options": ["a", "b"], "default": "a"}
            for i in range(5)
        ]

        result = filter_critical_questions(questions, portion_guess_g=500, max_questions=2)

        assert len(result) <= 2


class TestMultilingualUSDAIntegration:
    """Test multilingual canonicalization before USDA search."""

    @patch('requests.get')
    def test_spanish_name_translated_before_usda_search(self, mock_get):
        """Test Spanish food name is translated before USDA query."""
        # Setup USDA mock response for "chicken"
        mock_response = Mock()
        mock_response.json.return_value = {
            "foods": [{
                "fdcId": 123456,
                "description": "Chicken, breast, cooked",
                "dataType": "Survey (FNDDS)",
                "foodNutrients": [
                    {"nutrientId": 1008, "amount": 165},
                    {"nutrientId": 1003, "amount": 31},
                    {"nutrientId": 1005, "amount": 0},
                    {"nutrientId": 1004, "amount": 3.6}
                ]
            }]
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        usda_client.set_api_key("test_key")

        # Input Spanish name
        spanish_name = "pollo"

        # Canonicalize (should translate to "chicken")
        canonical = canonicalize_name(spanish_name)
        assert "chicken" in canonical

        # Search USDA with canonical name
        result = usda_client.search_best_match(canonical)

        # Should find chicken in USDA
        assert result is not None
        assert result["fdcId"] == 123456


class TestTiebreakerSanityIntegration:
    """Test tiebreaker abstain when sanity gate conflicts."""

    @patch('requests.get')
    def test_tiebreaker_abstains_on_sanity_conflict(self, mock_get):
        """Test tiebreaker returns ambiguous when top-2 have sanity conflict."""
        # Mock USDA response with two candidates:
        # 1. "Diet Cola" with HIGH calories (fails sanity)
        # 2. "Diet Cola, zero calorie" with LOW calories (passes sanity)
        mock_response = Mock()
        mock_response.json.return_value = {
            "foods": [
                {
                    "fdcId": 111111,
                    "description": "Diet Cola",
                    "dataType": "Survey (FNDDS)",
                    "foodNutrients": [
                        {"nutrientId": 1008, "amount": 50},  # HIGH calories (fails sanity)
                        {"nutrientId": 1003, "amount": 0},
                        {"nutrientId": 1005, "amount": 12},
                        {"nutrientId": 1004, "amount": 0}
                    ]
                },
                {
                    "fdcId": 222222,
                    "description": "Diet Cola, zero calorie",
                    "dataType": "Survey (FNDDS)",
                    "foodNutrients": [
                        {"nutrientId": 1008, "amount": 2},   # LOW calories (passes sanity)
                        {"nutrientId": 1003, "amount": 0},
                        {"nutrientId": 1005, "amount": 0},
                        {"nutrientId": 1004, "amount": 0}
                    ]
                }
            ]
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        usda_client.set_api_key("test_key")
        result = usda_client.search_best_match("diet cola")

        # Should detect sanity conflict and return ambiguous
        assert result.get("_ambiguous") is True
        assert result.get("_reason") == "sanity_gate_conflict"


class TestEndToEndPipeline:
    """Test complete pipeline from vision to final calculation."""

    @patch('core.vision_estimator.run_with_tools')
    @patch('core.vision_estimator.get_image_part')
    @patch('requests.get')
    def test_full_pipeline_with_question_filtering(self, mock_usda, mock_image, mock_llm):
        """Test complete flow: vision -> filter questions -> QA -> USDA -> validation."""
        # Mock image
        mock_image.return_value = MagicMock()

        # Mock vision LLM response with multiple questions
        mock_vision_response = MagicMock()
        mock_vision_response.text = json.dumps({
            "dish": "Fast food combo",
            "portion_guess_g": 800,
            "ingredients": [
                {"name": "burger", "amount": None, "unit": "g", "source": "estimation", "portion_label": "single", "notes": "McDonald's"},
                {"name": "fries", "amount": None, "unit": "g", "source": "estimation", "portion_label": "medium", "notes": "McDonald's"},
                {"name": "soda", "amount": None, "unit": "g", "source": "estimation", "portion_label": "medium", "notes": None}
            ],
            "critical_questions": [
                {"id": "q1", "text": "Fries size?", "impact_score": 0.8, "options": ["small", "medium", "large"], "default": "medium"},
                {"id": "q2", "text": "Drink type?", "impact_score": 0.7, "options": ["regular", "diet"], "default": "regular"},
                {"id": "q3", "text": "Cheese?", "impact_score": 0.4, "options": ["yes", "no"], "default": "yes"},
                {"id": "q4", "text": "Sauce?", "impact_score": 0.2, "options": ["ketchup", "mayo"], "default": "ketchup"}
            ]
        })
        mock_llm.return_value = (mock_vision_response, 0)

        # Mock USDA responses
        def usda_mock_response(*args, **kwargs):
            url = args[0] if args else kwargs.get('url', '')

            # Generic response
            response = Mock()
            response.status_code = 200
            response.json.return_value = {
                "foods": [{
                    "fdcId": 999999,
                    "description": "Generic food",
                    "dataType": "Survey (FNDDS)",
                    "foodNutrients": [
                        {"nutrientId": 1008, "amount": 200},
                        {"nutrientId": 1003, "amount": 10},
                        {"nutrientId": 1005, "amount": 30},
                        {"nutrientId": 1004, "amount": 5}
                    ]
                }]
            }
            return response

        mock_usda.side_effect = usda_mock_response

        # Step 1: Vision estimation
        mock_model = MagicMock()
        test_image = b"test_image_bytes"

        vision_result, tool_calls = estimate(test_image, mock_model)

        # Should have filtered questions (max 2)
        assert vision_result is not None
        assert len(vision_result.critical_questions) <= 2

        # Should prioritize by impact (q1 and q2 should be kept)
        question_ids = [q.id for q in vision_result.critical_questions]
        assert "q1" in question_ids
        assert "q2" in question_ids


class TestDensityFallbackIntegration:
    """Test beverage density fallback in combo sanity checks."""

    def test_unknown_beverage_uses_default_density(self, capsys):
        """Test unknown beverage type falls back to 1.0 g/mL."""
        from core.validators import validate_combo_sanity_caps

        scaled_items = [{
            "name": "Diet mystery drink",  # Not in BEVERAGE_DENSITY table
            "grams": 500,
            "kcal": 200,
            "protein_g": 0,
            "carb_g": 0,
            "fat_g": 0,
            "source": "USDA",
            "fdc_id": 99999
        }]

        warnings = validate_combo_sanity_caps(scaled_items, "unknown beverage")

        # Should detect high calories
        assert len(warnings) > 0

        # Should log default density usage
        captured = capsys.readouterr()
        assert "default density" in captured.out
        assert "1.00 g/mL" in captured.out

        # Warning should include density_source
        if warnings:
            assert warnings[0]["density_source"] == "default"


class TestRedisFallbackIntegration:
    """Test Redis auto-fallback to LocalFileCache."""

    @patch.dict('os.environ', {'CACHE_BACKEND': 'redis'})
    @patch('redis.Redis')
    def test_redis_unavailable_falls_back_to_local(self, mock_redis, capsys):
        """Test graceful fallback when Redis is unavailable."""
        # Reset cache backend
        import core.cache_interface
        core.cache_interface._cache_backend = None

        # Simulate Redis connection failure
        mock_redis.side_effect = ConnectionError("Redis connection refused")

        from core.cache_interface import get_cache_backend, LocalFileCache

        backend = get_cache_backend()

        # Should fallback to LocalFileCache
        assert isinstance(backend, LocalFileCache)

        # Should log fallback event
        captured = capsys.readouterr()
        assert "cache_fallback" in captured.out
        assert '"from": "redis"' in captured.out


class TestExplainabilityPersistence:
    """Test top-3 USDA candidates persistence."""

    @patch('requests.get')
    def test_top3_candidates_attached_to_results(self, mock_get):
        """Test that top-3 candidates are included in USDA results."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "foods": [
                {
                    "fdcId": i,
                    "description": f"Chicken option {i}",
                    "dataType": "Survey (FNDDS)",
                    "foodNutrients": [
                        {"nutrientId": 1008, "amount": 165},
                        {"nutrientId": 1003, "amount": 31},
                        {"nutrientId": 1005, "amount": 0},
                        {"nutrientId": 1004, "amount": 3.6}
                    ]
                }
                for i in range(5)  # Return 5 candidates
            ]
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        usda_client.set_api_key("test_key")
        result = usda_client.search_best_match("chicken")

        # Should include _top3 metadata
        assert "_top3" in result
        assert len(result["_top3"]) == 3

        # Each candidate should have score and description
        for candidate in result["_top3"]:
            assert "fdcId" in candidate
            assert "description" in candidate
            assert "score" in candidate
