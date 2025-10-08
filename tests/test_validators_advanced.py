"""
Unit tests for advanced validators (combo sanity, density, penalties).

Tests P2-E1 combo sanity caps with beverage density normalization.
"""
import pytest
import json
from unittest.mock import patch

from core.validators import (
    validate_combo_sanity_caps,
    BEVERAGE_DENSITY,
    compute_confidence,
    run_all_validations
)


class TestComboSanityCaps:
    """Test combo sanity validation (P2-E1)."""

    def test_diet_beverage_high_calories(self):
        """Test detection of diet beverage with implausible calories."""
        scaled_items = [{
            "name": "Diet Cola",
            "grams": 500,  # 500ml
            "kcal": 200,   # Should be <50 for 500ml diet drink
            "protein_g": 0,
            "carb_g": 0,
            "fat_g": 0,
            "source": "USDA",
            "fdc_id": 12345
        }]

        warnings = validate_combo_sanity_caps(scaled_items, "test dish")

        assert len(warnings) > 0
        assert warnings[0]["category"] == "diet_beverage_kcal"
        assert warnings[0]["severity"] == "high"

    def test_diet_beverage_correct_calories(self):
        """Test diet beverage with correct low calories passes."""
        scaled_items = [{
            "name": "Diet Cola",
            "grams": 500,  # 500ml
            "kcal": 5,     # Correct for diet
            "protein_g": 0,
            "carb_g": 0,
            "fat_g": 0,
            "source": "USDA",
            "fdc_id": 12345
        }]

        warnings = validate_combo_sanity_caps(scaled_items, "test dish")

        assert len(warnings) == 0

    def test_leafy_greens_high_protein(self):
        """Test detection of leafy greens with implausible protein."""
        scaled_items = [{
            "name": "Spinach",
            "grams": 100,
            "kcal": 50,
            "protein_g": 15,  # Too high for spinach
            "carb_g": 5,
            "fat_g": 0.5,
            "source": "USDA",
            "fdc_id": 67890
        }]

        warnings = validate_combo_sanity_caps(scaled_items, "salad")

        assert len(warnings) > 0
        assert warnings[0]["category"] == "leafy_protein"

    def test_lean_protein_high_fat(self):
        """Test detection of lean protein with excessive fat."""
        scaled_items = [{
            "name": "Chicken breast",
            "grams": 150,
            "kcal": 300,
            "protein_g": 30,
            "carb_g": 0,
            "fat_g": 40,  # 26% fat - too high for chicken breast
            "source": "USDA",
            "fdc_id": 11111
        }]

        warnings = validate_combo_sanity_caps(scaled_items, "grilled chicken")

        assert len(warnings) > 0
        assert warnings[0]["category"] == "lean_protein_fat"

    def test_skim_milk_high_fat(self):
        """Test detection of skim milk with excessive fat."""
        scaled_items = [{
            "name": "Skim milk",
            "grams": 250,
            "kcal": 100,
            "protein_g": 8,
            "carb_g": 12,
            "fat_g": 5,  # 2% fat - too high for skim
            "source": "USDA",
            "fdc_id": 22222
        }]

        warnings = validate_combo_sanity_caps(scaled_items, "milk")

        assert len(warnings) > 0
        assert warnings[0]["category"] == "skim_milk_fat"

    def test_water_with_calories(self):
        """Test detection of water with non-zero calories."""
        scaled_items = [{
            "name": "water",
            "grams": 500,
            "kcal": 50,  # Water should be 0
            "protein_g": 0,
            "carb_g": 0,
            "fat_g": 0,
            "source": "USDA",
            "fdc_id": 33333
        }]

        warnings = validate_combo_sanity_caps(scaled_items, "water")

        assert len(warnings) > 0
        assert warnings[0]["category"] == "water_kcal"

    def test_multiple_violations(self):
        """Test detection of multiple combo sanity violations."""
        scaled_items = [
            {
                "name": "Diet soda",
                "grams": 500,
                "kcal": 200,  # Too high
                "protein_g": 0,
                "carb_g": 0,
                "fat_g": 0,
                "source": "USDA",
                "fdc_id": 1
            },
            {
                "name": "water",
                "grams": 250,
                "kcal": 25,  # Should be 0
                "protein_g": 0,
                "carb_g": 0,
                "fat_g": 0,
                "source": "USDA",
                "fdc_id": 2
            }
        ]

        warnings = validate_combo_sanity_caps(scaled_items, "beverages")

        assert len(warnings) == 2

    def test_metrics_emission(self, capsys):
        """Test that combo sanity warnings emit metrics."""
        scaled_items = [{
            "name": "Diet Cola",
            "grams": 500,
            "kcal": 200,
            "protein_g": 0,
            "carb_g": 0,
            "fat_g": 0,
            "source": "USDA",
            "fdc_id": 12345
        }]

        validate_combo_sanity_caps(scaled_items, "test dish")

        captured = capsys.readouterr()
        assert "METRICS:" in captured.out
        assert "combo_sanity_fail" in captured.out


class TestBeverageDensity:
    """Test beverage density handling."""

    def test_density_table_completeness(self):
        """Test that density table has common beverages."""
        assert "water" in BEVERAGE_DENSITY
        assert "cola" in BEVERAGE_DENSITY
        assert "milk" in BEVERAGE_DENSITY
        assert "default" in BEVERAGE_DENSITY

    def test_default_density_is_one(self):
        """Test that default density is 1.0 g/mL."""
        assert BEVERAGE_DENSITY["default"] == 1.0

    def test_density_fallback_logging(self, capsys):
        """Test that unknown beverage types log default density usage."""
        scaled_items = [{
            "name": "Diet mystery beverage",  # Not in density table
            "grams": 500,
            "kcal": 200,
            "protein_g": 0,
            "carb_g": 0,
            "fat_g": 0,
            "source": "USDA",
            "fdc_id": 99999
        }]

        warnings = validate_combo_sanity_caps(scaled_items, "unknown drink")

        if warnings:
            # Check that density_source is logged
            assert "density_source" in warnings[0]
            assert warnings[0]["density_source"] == "default"


class TestPenaltyCalibration:
    """Test confidence penalty calibration."""

    def test_penalty_capped_at_max(self):
        """Test that combo sanity penalty is capped at 0.3."""
        # Create many violations (would exceed 0.3 without cap)
        scaled_items = [
            {
                "name": f"Diet soda {i}",
                "grams": 500,
                "kcal": 200,
                "protein_g": 0,
                "carb_g": 0,
                "fat_g": 0,
                "source": "USDA",
                "fdc_id": i
            }
            for i in range(5)  # 5 violations = 0.5 raw penalty
        ]

        validations = {
            "four_four_nine": {"ok": True},
            "portion_warnings": [],
            "combo_sanity_warnings": validate_combo_sanity_caps(scaled_items, "test")
        }

        confidence = compute_confidence(scaled_items, validations)

        # Base 0.8 - capped 0.3 penalty = 0.5 minimum
        assert confidence >= 0.5
        assert confidence <= 0.8

    def test_no_penalty_without_warnings(self):
        """Test no penalty when there are no combo sanity warnings."""
        scaled_items = [{
            "name": "Chicken breast",
            "grams": 150,
            "kcal": 248,
            "protein_g": 31,
            "carb_g": 0,
            "fat_g": 3.6,
            "source": "USDA",
            "fdc_id": 12345
        }]

        validations = {
            "four_four_nine": {"ok": True},
            "portion_warnings": [],
            "combo_sanity_warnings": []
        }

        confidence = compute_confidence(scaled_items, validations)

        assert confidence == 0.8  # Base confidence, no penalties


class TestRunAllValidationsIntegration:
    """Test run_all_validations with combo sanity."""

    def test_validation_includes_combo_sanity(self):
        """Test that run_all_validations includes combo sanity checks."""
        scaled_items = [{
            "name": "Diet Cola",
            "grams": 500,
            "kcal": 200,
            "protein_g": 0,
            "carb_g": 0,
            "fat_g": 0,
            "source": "USDA",
            "fdc_id": 12345
        }]

        results = run_all_validations(scaled_items, dish="combo meal")

        assert "combo_sanity_warnings" in results
        assert len(results["combo_sanity_warnings"]) > 0
        assert results["summary"]["combo_sanity_warnings_count"] > 0

    def test_confidence_affected_by_combo_sanity(self):
        """Test that combo sanity warnings reduce confidence."""
        # Good item
        good_items = [{
            "name": "Chicken breast",
            "grams": 150,
            "kcal": 248,
            "protein_g": 31,
            "carb_g": 0,
            "fat_g": 3.6,
            "source": "USDA",
            "fdc_id": 12345
        }]

        # Bad item with combo sanity violation
        bad_items = [{
            "name": "Diet Cola",
            "grams": 500,
            "kcal": 200,
            "protein_g": 0,
            "carb_g": 0,
            "fat_g": 0,
            "source": "USDA",
            "fdc_id": 67890
        }]

        good_results = run_all_validations(good_items, dish="good meal")
        bad_results = run_all_validations(bad_items, dish="bad meal")

        assert good_results["confidence"] > bad_results["confidence"]
