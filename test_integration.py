#!/usr/bin/env python3
"""
Integration test to verify the refactored components work with real functionality.
"""

import json
from core.schemas import VisionEstimate, RefinementUpdate
from core.json_repair import parse_or_repair_json


def test_vision_estimate_with_real_json():
    """Test with realistic JSON that might come from Gemini."""
    # This is similar to what Gemini might actually return
    realistic_json = '''
    {
        "dish": "grilled chicken breast with roasted vegetables",
        "portion_guess_g": 425.0,
        "ingredients": [
            {
                "name": "chicken breast",
                "amount": 180.0,
                "unit": "g",
                "source": "vision",
                "notes": "grilled, appears boneless and skinless"
            },
            {
                "name": "broccoli",
                "amount": 100.0,
                "unit": "g",
                "source": "vision",
                "notes": "roasted"
            },
            {
                "name": "bell peppers",
                "amount": 80.0,
                "unit": "g",
                "source": "vision",
                "notes": "mixed colors, roasted"
            },
            {
                "name": "olive oil",
                "amount": 15.0,
                "unit": "g",
                "source": "vision",
                "notes": "estimated cooking oil"
            }
        ],
        "critical_questions": [
            {
                "id": "cooking_method",
                "text": "How was the chicken prepared?",
                "options": ["grilled", "baked", "pan-fried"],
                "default": "grilled",
                "impact_score": 0.6
            },
            {
                "id": "oil_amount",
                "text": "How much oil was used in cooking?",
                "options": ["minimal", "moderate", "generous"],
                "default": "moderate",
                "impact_score": 0.8
            }
        ]
    }
    '''

    # Test parsing
    parsed, errors = parse_or_repair_json(realistic_json, VisionEstimate)

    if parsed is None:
        print(f"FAIL: Could not parse realistic JSON: {errors}")
        return False

    # Verify the parsed data
    assert parsed.dish == "grilled chicken breast with roasted vegetables"
    assert len(parsed.ingredients) == 4
    assert len(parsed.critical_questions) == 2
    assert parsed.ingredients[0].name == "chicken breast"
    assert parsed.critical_questions[0].impact_score == 0.6

    print("PASS: Realistic vision estimate JSON parsed successfully")
    return True


def test_refinement_with_real_json():
    """Test refinement with realistic user update JSON."""
    realistic_refinement = '''
    {
        "updated_ingredients": [
            {
                "name": "chicken breast",
                "amount": 200.0,
                "unit": "g",
                "source": "user",
                "notes": "user confirmed it was a large portion"
            },
            {
                "name": "butter",
                "amount": 10.0,
                "unit": "g",
                "source": "user",
                "notes": "user mentioned they used butter, not oil"
            }
        ],
        "updated_assumptions": [
            {
                "key": "cooking_fat",
                "value": "butter",
                "confidence": 1.0
            },
            {
                "key": "portion_size",
                "value": "large",
                "confidence": 0.9
            }
        ]
    }
    '''

    parsed, errors = parse_or_repair_json(realistic_refinement, RefinementUpdate)

    if parsed is None:
        print(f"FAIL: Could not parse refinement JSON: {errors}")
        return False

    # Verify the parsed data
    assert len(parsed.updated_ingredients) == 2
    assert len(parsed.updated_assumptions) == 2
    assert parsed.updated_ingredients[1].name == "butter"
    assert parsed.updated_assumptions[0].confidence == 1.0

    print("PASS: Realistic refinement JSON parsed successfully")
    return True


def test_json_repair_with_common_llm_issues():
    """Test JSON repair with common issues that Gemini might produce."""

    # Test 1: JSON with markdown
    json_with_markdown = '''```json
    {
        "dish": "pasta with tomato sauce",
        "portion_guess_g": 300,
        "ingredients": [
            {
                "name": "spaghetti",
                "amount": 100,
                "unit": "g",
                "source": "vision",
                "notes": null
            }
        ],
        "critical_questions": []
    }
    ```'''

    parsed, errors = parse_or_repair_json(json_with_markdown, VisionEstimate)
    if parsed is None:
        print(f"FAIL: Could not repair markdown JSON: {errors}")
        return False

    # Test 2: JSON with trailing comma
    json_with_trailing_comma = '''{
        "dish": "test dish",
        "portion_guess_g": 100,
        "ingredients": [],
        "critical_questions": [],
    }'''

    parsed, errors = parse_or_repair_json(json_with_trailing_comma, VisionEstimate)
    if parsed is None:
        print(f"FAIL: Could not repair trailing comma JSON: {errors}")
        return False

    print("PASS: JSON repair handles common LLM issues")
    return True


def test_prompt_loading():
    """Test that prompt files can be loaded."""
    try:
        with open("config/llm_prompts/vision_estimator_prompt.txt", "r", encoding="utf-8") as f:
            vision_prompt = f.read()

        with open("config/llm_prompts/qa_manager_prompt.txt", "r", encoding="utf-8") as f:
            qa_prompt = f.read()

        # Basic checks
        assert "JSON" in vision_prompt
        assert "VisionEstimate" in vision_prompt or "vision" in vision_prompt.lower()
        assert "JSON" in qa_prompt
        assert "RefinementUpdate" in qa_prompt or "refinement" in qa_prompt.lower()

        print("PASS: Prompt files loaded successfully")
        return True
    except Exception as e:
        print(f"FAIL: Could not load prompt files: {e}")
        return False


if __name__ == "__main__":
    print("Running integration tests for Phase 1.0...")

    tests = [
        test_vision_estimate_with_real_json,
        test_refinement_with_real_json,
        test_json_repair_with_common_llm_issues,
        test_prompt_loading
    ]

    passed = 0
    for test in tests:
        if test():
            passed += 1

    print(f"\nResults: {passed}/{len(tests)} tests passed")

    if passed == len(tests):
        print("PASS: All integration tests passed! The refactored code should work with real Streamlit.")
        print("INFO: To test with real images: streamlit run app.py")
    else:
        print("FAIL: Some tests failed - need to fix issues before real testing")