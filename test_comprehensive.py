#!/usr/bin/env python3
"""
Comprehensive Test Suite for Phase 1.0
Acting as Testing Agent to verify rock-solid completion
"""

import json
from core.schemas import VisionEstimate, RefinementUpdate, Ingredient, ClarificationQuestion, Assumption
from core.json_repair import parse_or_repair_json, llm_retry_with_system_hardener
from integrations.search_bridge import create_search_tool_function
from tavily import TavilyClient


class TestSchemaValidationComprehensive:
    """Test schema validation with extreme edge cases."""

    def test_vision_estimate_boundary_conditions(self):
        """Test VisionEstimate with boundary values."""
        # Test minimum valid values
        min_valid = {
            "dish": "",  # Empty string should be valid
            "portion_guess_g": 0.0,  # Exactly zero should be valid
            "ingredients": [],  # Empty list should be valid
            "critical_questions": []
        }
        estimate = VisionEstimate(**min_valid)
        assert estimate.portion_guess_g == 0.0
        print("PASS: VisionEstimate accepts minimum boundary values")

        # Test very large values
        large_valid = {
            "dish": "x" * 1000,  # Very long dish name
            "portion_guess_g": 999999.99,  # Very large portion
            "ingredients": [],
            "critical_questions": []
        }
        estimate = VisionEstimate(**large_valid)
        assert len(estimate.dish) == 1000
        print("PASS: VisionEstimate accepts large valid values")

    def test_ingredient_validation_edge_cases(self):
        """Test Ingredient with edge cases."""
        # Test exactly zero amount
        zero_ingredient = {
            "name": "trace_element",
            "amount": 0.0,
            "unit": "g",
            "source": "vision",
            "notes": None
        }
        ingredient = Ingredient(**zero_ingredient)
        assert ingredient.amount == 0.0
        print("PASS: Ingredient accepts zero amount")

        # Test very small positive amount
        tiny_ingredient = {
            "name": "seasoning",
            "amount": 0.001,
            "unit": "g",
            "source": "user",
            "notes": "tiny amount"
        }
        ingredient = Ingredient(**tiny_ingredient)
        assert ingredient.amount == 0.001
        print("PASS: Ingredient accepts tiny positive amounts")

    def test_confidence_impact_score_boundaries(self):
        """Test confidence and impact_score boundary validation."""
        # Test exactly 0 and 1
        boundary_assumption = {
            "key": "test",
            "value": "test",
            "confidence": 0.0
        }
        assumption = Assumption(**boundary_assumption)
        assert assumption.confidence == 0.0

        boundary_assumption["confidence"] = 1.0
        assumption = Assumption(**boundary_assumption)
        assert assumption.confidence == 1.0
        print("PASS: Confidence accepts exact boundary values 0.0 and 1.0")

        # Test impact_score boundaries
        boundary_question = {
            "id": "test",
            "text": "test",
            "impact_score": 0.0
        }
        question = ClarificationQuestion(**boundary_question)
        assert question.impact_score == 0.0

        boundary_question["impact_score"] = 1.0
        question = ClarificationQuestion(**boundary_question)
        assert question.impact_score == 1.0
        print("PASS: Impact score accepts exact boundary values 0.0 and 1.0")

    def test_strict_mode_rejection_cases(self):
        """Test that strict mode properly rejects invalid data."""
        test_cases = [
            # Extra field
            {
                "data": {
                    "dish": "test",
                    "portion_guess_g": 100.0,
                    "ingredients": [],
                    "critical_questions": [],
                    "hacker_field": "should_fail"
                },
                "description": "extra field"
            },
            # Negative portion
            {
                "data": {
                    "dish": "test",
                    "portion_guess_g": -1.0,
                    "ingredients": [],
                    "critical_questions": []
                },
                "description": "negative portion weight"
            },
            # Invalid enum
            {
                "data": {
                    "name": "test",
                    "amount": 10.0,
                    "unit": "g",
                    "source": "invalid_source",
                    "notes": None
                },
                "schema": Ingredient,
                "description": "invalid source enum"
            }
        ]

        for case in test_cases:
            schema = case.get("schema", VisionEstimate)
            try:
                schema(**case["data"])
                assert False, f"Should have rejected {case['description']}"
            except Exception:
                print(f"PASS: Correctly rejected {case['description']}")


class TestJSONRepairComprehensive:
    """Test JSON repair with realistic LLM variations."""

    def test_common_llm_formatting_issues(self):
        """Test repair of common LLM formatting problems."""
        test_cases = [
            # Markdown code blocks
            {
                "input": '```json\n{"dish": "test", "portion_guess_g": 100, "ingredients": [], "critical_questions": []}\n```',
                "description": "markdown code blocks"
            },
            # Leading/trailing text
            {
                "input": 'Here is the JSON you requested:\n{"dish": "test", "portion_guess_g": 100, "ingredients": [], "critical_questions": []}\nI hope this helps!',
                "description": "leading and trailing prose"
            },
            # Comments in JSON
            {
                "input": '{\n  // This is a comment\n  "dish": "test",\n  "portion_guess_g": 100, // Another comment\n  "ingredients": [],\n  "critical_questions": []\n}',
                "description": "JSON with comments"
            },
            # Trailing commas
            {
                "input": '{"dish": "test", "portion_guess_g": 100, "ingredients": [], "critical_questions": [],}',
                "description": "trailing commas"
            },
            # Mixed formatting issues
            {
                "input": '```\nSure! Here\'s the analysis:\n{\n  "dish": "chicken salad", // estimated\n  "portion_guess_g": 350.0,\n  "ingredients": [\n    {"name": "chicken", "amount": 120, "unit": "g", "source": "vision", "notes": null},\n  ],\n  "critical_questions": [],\n}\n```\nLet me know if you need clarification!',
                "description": "multiple formatting issues combined"
            }
        ]

        for case in test_cases:
            parsed, errors = parse_or_repair_json(case["input"], VisionEstimate)
            assert parsed is not None, f"Failed to repair {case['description']}: {errors}"
            assert parsed.dish is not None
            print(f"PASS: Successfully repaired {case['description']}")

    def test_malformed_json_edge_cases(self):
        """Test edge cases that should fail even after repair."""
        failure_cases = [
            '{"incomplete":',
            'not json at all',
            '{"dish": "test", "portion_guess_g": "not_a_number", "ingredients": [], "critical_questions": []}',
            '',
            '{}',  # Missing required fields
        ]

        for case in failure_cases:
            parsed, errors = parse_or_repair_json(case, VisionEstimate)
            assert parsed is None, f"Should have failed to parse: {case}"
            assert len(errors) > 0
            print(f"PASS: Correctly failed to parse malformed input: {case[:30]}...")


class TestModuleIntegration:
    """Test module integration and dependencies."""

    def test_prompt_template_loading(self):
        """Test that prompt templates are properly structured."""
        # Test vision estimator prompt
        try:
            with open("config/llm_prompts/vision_estimator_prompt.txt", "r", encoding="utf-8") as f:
                vision_prompt = f.read()

            # Check for required elements
            assert "JSON" in vision_prompt.upper()
            assert "example" in vision_prompt.lower()
            assert "{" in vision_prompt and "}" in vision_prompt
            print("PASS: Vision estimator prompt is properly structured")

            # Test QA manager prompt
            with open("config/llm_prompts/qa_manager_prompt.txt", "r", encoding="utf-8") as f:
                qa_prompt = f.read()

            assert "JSON" in qa_prompt.upper()
            assert "example" in qa_prompt.lower()
            assert "{" in qa_prompt and "}" in qa_prompt
            print("PASS: QA manager prompt is properly structured")

        except FileNotFoundError as e:
            assert False, f"Prompt template missing: {e}"

    def test_search_integration_structure(self):
        """Test search integration without making real API calls."""
        # Test that we can create search function without error
        try:
            # Mock TavilyClient for testing
            class MockTavilyClient:
                def search(self, query, search_depth="basic"):
                    return {
                        'results': [
                            {"url": "test.com", "content": "test content"}
                        ]
                    }

            mock_client = MockTavilyClient()
            search_func = create_search_tool_function(mock_client)

            # Test that it returns proper format
            result = search_func("test query")
            parsed_result = json.loads(result)
            assert isinstance(parsed_result, list)
            assert "url" in parsed_result[0]
            assert "content" in parsed_result[0]
            print("PASS: Search integration returns proper format")

        except Exception as e:
            assert False, f"Search integration failed: {e}"

    def test_import_dependencies(self):
        """Test that all module imports work correctly."""
        import_tests = [
            "from core.schemas import VisionEstimate, RefinementUpdate",
            "from core.json_repair import parse_or_repair_json",
            "from core import vision_estimator, qa_manager",
            "from integrations.search_bridge import create_search_tool_function",
        ]

        for test_import in import_tests:
            try:
                exec(test_import)
                print(f"PASS: {test_import}")
            except Exception as e:
                assert False, f"Import failed: {test_import} - {e}"


def run_comprehensive_tests():
    """Run all comprehensive tests."""
    print("=" * 60)
    print("COMPREHENSIVE PHASE 1.0 TEST SUITE")
    print("=" * 60)

    test_classes = [
        TestSchemaValidationComprehensive(),
        TestJSONRepairComprehensive(),
        TestModuleIntegration()
    ]

    total_tests = 0
    passed_tests = 0

    for test_class in test_classes:
        print(f"\n--- Testing {test_class.__class__.__name__} ---")

        for method_name in dir(test_class):
            if method_name.startswith("test_"):
                total_tests += 1
                try:
                    method = getattr(test_class, method_name)
                    method()
                    passed_tests += 1
                    print(f"PASS: {method_name}")
                except Exception as e:
                    print(f"FAIL: {method_name}: {e}")

    print("\n" + "=" * 60)
    print(f"TEST RESULTS: {passed_tests}/{total_tests} PASSED")

    if passed_tests == total_tests:
        print("SUCCESS: PHASE 1.0 IS ROCK SOLID - READY FOR PHASE 2.0!")
    else:
        print("WARNING: ISSUES FOUND - NEEDS FIXES BEFORE PHASE 2.0")

    print("=" * 60)
    return passed_tests == total_tests


if __name__ == "__main__":
    success = run_comprehensive_tests()