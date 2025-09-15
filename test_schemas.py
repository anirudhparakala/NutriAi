#!/usr/bin/env python3
"""
Simple unit tests for Phase 1.0 schema validation.
"""

import json
from core.schemas import VisionEstimate, RefinementUpdate, Ingredient, ClarificationQuestion
from core.json_repair import parse_or_repair_json


def test_vision_estimate_schema():
    """Test VisionEstimate schema validation - happy path."""
    test_data = {
        "dish": "grilled chicken salad",
        "portion_guess_g": 350.0,
        "ingredients": [
            {
                "name": "chicken breast",
                "amount": 120.0,
                "unit": "g",
                "source": "vision",
                "notes": "grilled, no visible skin"
            }
        ],
        "critical_questions": [
            {
                "id": "dressing_type",
                "text": "What type of dressing?",
                "options": ["ranch", "caesar", "vinaigrette"],
                "default": "ranch",
                "impact_score": 0.7
            }
        ]
    }

    # Test direct validation
    estimate = VisionEstimate(**test_data)
    assert estimate.dish == "grilled chicken salad"
    assert len(estimate.ingredients) == 1
    assert estimate.ingredients[0].source == "vision"
    print("PASS: VisionEstimate schema validation passed")


def test_refinement_update_schema():
    """Test RefinementUpdate schema validation - happy path."""
    test_data = {
        "updated_ingredients": [
            {
                "name": "olive oil",
                "amount": 15.0,
                "unit": "g",
                "source": "user",
                "notes": "confirmed by user"
            }
        ],
        "updated_assumptions": [
            {
                "key": "oil_type",
                "value": "olive oil",
                "confidence": 1.0
            }
        ]
    }

    # Test direct validation
    update = RefinementUpdate(**test_data)
    assert len(update.updated_ingredients) == 1
    assert update.updated_assumptions[0].confidence == 1.0
    print("PASS: RefinementUpdate schema validation passed")


def test_json_repair():
    """Test JSON repair functionality."""
    # Test with markdown code blocks
    json_with_markdown = '''```json
    {
        "dish": "test dish",
        "portion_guess_g": 100,
        "ingredients": [],
        "critical_questions": []
    }
    ```'''

    parsed, errors = parse_or_repair_json(json_with_markdown, VisionEstimate)
    assert parsed is not None, f"Parsing failed: {errors}"
    assert parsed.dish == "test dish"
    print("PASS: JSON repair functionality passed")


def test_schema_failure_cases():
    """Test schema validation failure cases."""
    # Missing required field
    invalid_data = {
        "dish": "test",
        # Missing portion_guess_g, ingredients, critical_questions
    }

    try:
        VisionEstimate(**invalid_data)
        assert False, "Should have failed validation"
    except Exception as e:
        print(f"PASS: Schema correctly rejected invalid data: {type(e).__name__}")

    # Invalid source type
    invalid_ingredient = {
        "name": "test",
        "amount": 100,
        "unit": "g",
        "source": "invalid_source",  # Not in allowed literals
        "notes": None
    }

    try:
        Ingredient(**invalid_ingredient)
        assert False, "Should have failed validation"
    except Exception as e:
        print(f"PASS: Schema correctly rejected invalid source: {type(e).__name__}")


def test_strict_validation_cases():
    """Test new strict validation cases from colleague feedback."""

    # Test 1: Extra fields should be rejected (extra='forbid')
    data_with_extra_field = {
        "dish": "test dish",
        "portion_guess_g": 100.0,
        "ingredients": [],
        "critical_questions": [],
        "unexpected_field": "should_fail"  # Extra field
    }

    try:
        VisionEstimate(**data_with_extra_field)
        assert False, "Should have failed validation due to extra field"
    except Exception as e:
        print(f"PASS: Schema correctly rejected extra fields: {type(e).__name__}")

    # Test 2: Negative amount should be rejected
    negative_amount_ingredient = {
        "name": "test",
        "amount": -10.0,  # Should fail ge=0 constraint
        "unit": "g",
        "source": "vision",
        "notes": None
    }

    try:
        Ingredient(**negative_amount_ingredient)
        assert False, "Should have failed validation due to negative amount"
    except Exception as e:
        print(f"PASS: Schema correctly rejected negative amount: {type(e).__name__}")

    # Test 3: Out-of-range confidence should be rejected
    invalid_confidence_assumption = {
        "key": "test",
        "value": "test",
        "confidence": 1.5  # Should fail le=1 constraint
    }

    try:
        Assumption(**invalid_confidence_assumption)
        assert False, "Should have failed validation due to confidence > 1"
    except Exception as e:
        print(f"PASS: Schema correctly rejected confidence > 1: {type(e).__name__}")

    # Test 4: Out-of-range impact_score should be rejected
    invalid_impact_question = {
        "id": "test",
        "text": "test question",
        "impact_score": -0.1  # Should fail ge=0 constraint
    }

    try:
        ClarificationQuestion(**invalid_impact_question)
        assert False, "Should have failed validation due to negative impact_score"
    except Exception as e:
        print(f"PASS: Schema correctly rejected negative impact_score: {type(e).__name__}")

    # Test 5: Negative portion_guess_g should be rejected
    negative_portion_data = {
        "dish": "test",
        "portion_guess_g": -50.0,  # Should fail ge=0 constraint
        "ingredients": [],
        "critical_questions": []
    }

    try:
        VisionEstimate(**negative_portion_data)
        assert False, "Should have failed validation due to negative portion_guess_g"
    except Exception as e:
        print(f"PASS: Schema correctly rejected negative portion weight: {type(e).__name__}")


if __name__ == "__main__":
    print("Running Phase 1.0 schema validation tests...")
    test_vision_estimate_schema()
    test_refinement_update_schema()
    test_json_repair()
    test_schema_failure_cases()
    test_strict_validation_cases()
    print("PASS: All tests passed!")