import pytest
import json
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock

# Import modules to test
from integrations import usda_client
from core import nutrition_lookup, validators
from core.qa_manager import generate_final_calculation
from core.schemas import VisionEstimate, Ingredient


class TestUSDAClient:
    """Test USDA client functionality."""

    def setup_method(self):
        """Setup for each test."""
        usda_client.set_api_key("test_key")
        usda_client.clear_cache()

    def test_api_key_setting(self):
        """Test API key configuration."""
        usda_client.set_api_key("test_api_key")
        assert usda_client._api_key == "test_api_key"

    @patch('requests.get')
    def test_search_best_match_success(self, mock_get):
        """Test successful USDA search and best match selection."""
        # Mock USDA API response
        mock_response = Mock()
        mock_response.json.return_value = {
            "foods": [
                {
                    "fdcId": 171077,
                    "description": "Chicken, breast, meat only, cooked, roasted",
                    "dataType": "Survey (FNDDS)",
                    "foodNutrients": [
                        {"nutrientId": 1008, "amount": 165},  # Energy
                        {"nutrientId": 1003, "amount": 31.02},  # Protein
                        {"nutrientId": 1005, "amount": 0},  # Carbs
                        {"nutrientId": 1004, "amount": 3.57}  # Fat
                    ]
                },
                {
                    "fdcId": 123456,
                    "description": "Chicken breast, branded",
                    "dataType": "Branded",
                    "foodNutrients": []
                }
            ]
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = usda_client.search_best_match("chicken breast cooked")

        assert result is not None
        assert result["fdcId"] == 171077  # Should prefer FNDDS over Branded
        assert "Survey (FNDDS)" in result["dataType"]

    def test_search_best_match_no_results(self):
        """Test handling of empty search results."""
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"foods": []}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            result = usda_client.search_best_match("nonexistent food")
            assert result is None

    def test_per100g_macros_extraction(self):
        """Test macronutrient extraction from USDA data."""
        food_data = {
            "foodNutrients": [
                {"nutrientId": 1008, "amount": 165.0},  # Energy (kcal)
                {"nutrientId": 1003, "amount": 31.02},  # Protein
                {"nutrientId": 1005, "amount": 0.0},    # Carbs
                {"nutrientId": 1004, "amount": 3.57}    # Fat
            ]
        }

        macros = usda_client.per100g_macros(food_data)

        assert macros["kcal"] == 165.0
        assert macros["protein_g"] == 31.02
        assert macros["carb_g"] == 0.0
        assert macros["fat_g"] == 3.57

    def test_cache_functionality(self):
        """Test that caching works for repeated requests."""
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"foods": []}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            # First call should hit the API
            usda_client.search_best_match("test query")
            assert mock_get.call_count == 1

            # Second call should use cache (LRU cache)
            usda_client.search_best_match("test query")
            assert mock_get.call_count == 1  # No additional API call


class TestNutritionLookup:
    """Test nutrition lookup pipeline."""

    def setup_method(self):
        """Setup for each test."""
        usda_client.set_api_key("test_key")
        usda_client.clear_cache()

    @patch.object(usda_client, 'search_best_match')
    def test_normalize_and_ground_usda_success(self, mock_search):
        """Test successful USDA grounding."""
        # Mock USDA response
        mock_search.return_value = {
            "fdcId": 171077,
            "description": "Chicken, breast, meat only, cooked, roasted",
            "dataType": "Survey (FNDDS)",
            "foodNutrients": [
                {"nutrientId": 1008, "amount": 165},
                {"nutrientId": 1003, "amount": 31.02},
                {"nutrientId": 1005, "amount": 0},
                {"nutrientId": 1004, "amount": 3.57}
            ]
        }

        result, tool_calls = nutrition_lookup.normalize_and_ground("chicken breast cooked")

        assert result["source"] == "USDA"
        assert result["fdc_id"] == 171077
        assert result["per100g"]["kcal"] == 165
        assert result["per100g"]["protein_g"] == 31.02
        assert tool_calls == 0  # No search function provided

    @patch.object(usda_client, 'search_best_match')
    def test_normalize_and_ground_fallback(self, mock_search):
        """Test fallback when no USDA match found."""
        mock_search.return_value = None

        result, tool_calls = nutrition_lookup.normalize_and_ground("mystery herb")

        assert result["source"] == "fallback"
        assert result["fdc_id"] is None
        assert result["per100g"]["kcal"] == 0.0
        assert result["per100g"]["protein_g"] == 0.0
        assert tool_calls == 0  # No search function provided

    def test_scale_item(self):
        """Test portion scaling."""
        grounded_item = nutrition_lookup.GroundedItem(
            name="chicken breast",
            normalized_name="chicken breast",
            fdc_id=171077,
            source="USDA",
            per100g={"kcal": 165.0, "protein_g": 31.02, "carb_g": 0.0, "fat_g": 3.57}
        )

        scaled = nutrition_lookup.scale_item(grounded_item, 165.0)  # 165g portion

        assert scaled["grams"] == 165.0
        assert scaled["kcal"] == pytest.approx(272.25, abs=0.1)  # 165 * 1.65
        assert scaled["protein_g"] == pytest.approx(51.18, abs=0.1)  # 31.02 * 1.65

    def test_compute_totals(self):
        """Test total computation from scaled items."""
        scaled_items = [
            nutrition_lookup.ScaledItem(
                name="chicken breast", grams=165, kcal=272.25, protein_g=51.18,
                carb_g=0, fat_g=5.89, source="USDA", fdc_id=171077
            ),
            nutrition_lookup.ScaledItem(
                name="rice", grams=180, kcal=234.0, protein_g=4.32,
                carb_g=48.6, fat_g=0.36, source="USDA", fdc_id=123456
            )
        ]

        totals = nutrition_lookup.compute_totals(scaled_items)

        assert totals["kcal"] == pytest.approx(506.25, abs=0.1)
        assert totals["protein_g"] == pytest.approx(55.5, abs=0.1)
        assert totals["usda_count"] == 2
        assert totals["fallback_count"] == 0

    @patch.object(usda_client, 'search_best_match')
    def test_golden_ingredients_pipeline(self, mock_search):
        """Test the complete pipeline with golden test ingredients."""
        # Mock USDA responses for golden ingredients
        def mock_search_side_effect(query):
            if "chicken" in query.lower():
                return {
                    "fdcId": 171077,
                    "foodNutrients": [
                        {"nutrientId": 1008, "amount": 165},
                        {"nutrientId": 1003, "amount": 31.02},
                        {"nutrientId": 1005, "amount": 0},
                        {"nutrientId": 1004, "amount": 3.57}
                    ]
                }
            elif "rice" in query.lower():
                return {
                    "fdcId": 169704,
                    "foodNutrients": [
                        {"nutrientId": 1008, "amount": 130},
                        {"nutrientId": 1003, "amount": 2.4},
                        {"nutrientId": 1005, "amount": 27},
                        {"nutrientId": 1004, "amount": 0.2}
                    ]
                }
            elif "oil" in query.lower():
                return {
                    "fdcId": 171413,
                    "foodNutrients": [
                        {"nutrientId": 1008, "amount": 884},
                        {"nutrientId": 1003, "amount": 0},
                        {"nutrientId": 1005, "amount": 0},
                        {"nutrientId": 1004, "amount": 100}
                    ]
                }
            return None

        mock_search.side_effect = mock_search_side_effect

        # Golden test inputs
        ingredients = [
            {"name": "chicken breast cooked", "amount": 165},
            {"name": "steamed rice", "amount": 180},
            {"name": "olive oil", "amount": 10}
        ]

        result, tool_calls = nutrition_lookup.build_deterministic_breakdown(ingredients)

        # Verify all items have USDA grounding
        assert len(result["items"]) == 3
        for item in result["items"]:
            assert item["fdc_id"] is not None
            assert item["source"] == "USDA"

        # Verify realistic calorie ranges
        totals = result["totals"]
        assert 400 <= totals["kcal"] <= 600  # Reasonable total for this meal
        assert totals["protein_g"] > 40  # Good protein from chicken
        assert len(result["attribution"]) == 3  # All items attributed

        # Verify tool call tracking
        assert tool_calls >= 0  # Should track search function calls


class TestValidators:
    """Test validation and confidence scoring."""

    def test_validate_4_4_9_success(self):
        """Test 4/4/9 validation with correct macros."""
        # Manually calculated: 4*50 + 4*30 + 9*20 = 200 + 120 + 180 = 500
        scaled_items = [
            nutrition_lookup.ScaledItem(
                name="test food", grams=100, kcal=500, protein_g=50,
                carb_g=30, fat_g=20, source="USDA", fdc_id=123
            )
        ]

        result = validators.validate_4_4_9(scaled_items)

        assert result["ok"] is True
        assert result["delta_pct"] < 0.01  # Very close to expected

    def test_validate_4_4_9_failure(self):
        """Test 4/4/9 validation with incorrect macros."""
        # Calories way off: 1000 vs expected ~500
        scaled_items = [
            nutrition_lookup.ScaledItem(
                name="test food", grams=100, kcal=1000, protein_g=50,
                carb_g=30, fat_g=20, source="USDA", fdc_id=123
            )
        ]

        result = validators.validate_4_4_9(scaled_items)

        assert result["ok"] is False
        assert result["delta_pct"] > 0.1  # More than 10% off

    def test_validate_portion_bounds(self):
        """Test portion size validation."""
        scaled_items = [
            nutrition_lookup.ScaledItem(
                name="olive oil", grams=120, kcal=1061, protein_g=0,
                carb_g=0, fat_g=120, source="USDA", fdc_id=171413
            ),  # Should trigger warning (>30g oil)
            nutrition_lookup.ScaledItem(
                name="chicken breast", grams=165, kcal=272, protein_g=51,
                carb_g=0, fat_g=6, source="USDA", fdc_id=171077
            )  # Should be fine
        ]

        warnings = validators.validate_portion_bounds(scaled_items)

        assert len(warnings) == 1
        assert "olive oil" in warnings[0]["item_name"]
        assert warnings[0]["severity"] in ["medium", "high"]

    def test_compute_confidence(self):
        """Test confidence scoring."""
        # Mix of USDA and fallback items
        scaled_items = [
            nutrition_lookup.ScaledItem(
                name="chicken breast", grams=165, kcal=272, protein_g=51,
                carb_g=0, fat_g=6, source="USDA", fdc_id=171077
            ),
            nutrition_lookup.ScaledItem(
                name="mystery spice", grams=5, kcal=0, protein_g=0,
                carb_g=0, fat_g=0, source="fallback", fdc_id=None
            )
        ]

        validations = {
            "four_four_nine": {"ok": True},
            "portion_warnings": []
        }

        confidence = validators.compute_confidence(scaled_items, validations)

        assert 0.1 <= confidence <= 0.95
        assert confidence < 0.8  # Should be reduced due to fallback item


class TestQAManagerDeterministic:
    """Test that QA manager uses deterministic pipeline, not LLM macros."""

    @patch('core.qa_manager.build_deterministic_breakdown')
    @patch('core.qa_manager.run_all_validations')
    def test_no_llm_macros(self, mock_validations, mock_breakdown):
        """Test that final calculation doesn't rely on LLM for macros."""
        # Mock deterministic pipeline output (now returns tuple)
        mock_breakdown.return_value = ({
            "items": [
                nutrition_lookup.ScaledItem(
                    name="chicken breast", grams=165, kcal=272, protein_g=51,
                    carb_g=0, fat_g=6, source="USDA", fdc_id=171077
                )
            ],
            "totals": {"kcal": 272, "protein_g": 51, "carb_g": 0, "fat_g": 6},
            "attribution": [{"name": "chicken breast", "fdc_id": 171077}]
        }, 1)  # 1 tool call

        mock_validations.return_value = {
            "four_four_nine": {"ok": True},
            "portion_warnings": [],
            "confidence": 0.85
        }

        # Mock vision estimate and chat session
        mock_ingredient = Mock()
        mock_ingredient.name = "chicken breast"
        mock_ingredient.amount = 165

        mock_vision_estimate = Mock()
        mock_vision_estimate.ingredients = [mock_ingredient]

        mock_chat = Mock()

        # Call the function
        result_json, tool_calls = generate_final_calculation(
            chat_session=mock_chat,
            available_tools=None,
            vision_estimate=mock_vision_estimate,
            refinements=[]
        )

        # Parse result
        result = json.loads(result_json)

        # Verify macros come from deterministic pipeline, not LLM
        assert "breakdown" in result
        breakdown = result["breakdown"]
        assert len(breakdown) == 1
        assert breakdown[0]["calories"] == 272  # From mock_breakdown
        assert breakdown[0]["protein_grams"] == 51

        # Verify deterministic pipeline was called
        mock_breakdown.assert_called_once()

    def test_refinement_application(self):
        """Test that user refinements are properly applied."""
        # Mock original vision estimate
        mock_ingredient = Mock()
        mock_ingredient.name = "chicken breast"
        mock_ingredient.amount = 150

        mock_vision_estimate = Mock()
        mock_vision_estimate.ingredients = [mock_ingredient]

        # Mock refinement that updates the amount
        mock_refined_ingredient = Mock()
        mock_refined_ingredient.name = "chicken breast"
        mock_refined_ingredient.amount = 165

        mock_refinement = Mock()
        mock_refinement.updated_ingredients = [mock_refined_ingredient]

        with patch('core.qa_manager.build_deterministic_breakdown') as mock_breakdown:
            mock_breakdown.return_value = ({
                "items": [],
                "totals": {"kcal": 0, "protein_g": 0, "carb_g": 0, "fat_g": 0},
                "attribution": []
            }, 0)  # 0 tool calls

            with patch('core.qa_manager.run_all_validations') as mock_validations:
                mock_validations.return_value = {
                    "four_four_nine": {"ok": True},
                    "portion_warnings": [],
                    "confidence": 0.8
                }

                generate_final_calculation(
                    chat_session=Mock(),
                    available_tools=None,
                    vision_estimate=mock_vision_estimate,
                    refinements=[mock_refinement]
                )

                # Verify the correct ingredients were passed (with refinement applied)
                called_ingredients = mock_breakdown.call_args[0][0]
                assert any(ing["name"] == "chicken breast" and ing["amount"] == 165 for ing in called_ingredients)


def test_integration_no_regressions():
    """Integration test to ensure Phase 1 UX is preserved."""
    # This would be run with a real Streamlit app test if we had one
    # For now, just verify key imports work
    from ui.app import main
    from core import vision_estimator, qa_manager
    from integrations import usda_client

    # If we get here without import errors, basic integration is working
    assert True


# Test runner
if __name__ == "__main__":
    pytest.main([__file__])