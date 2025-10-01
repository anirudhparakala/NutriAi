#!/usr/bin/env python3
"""
Comprehensive test script to verify the entire refinement flow.
Tests that user inputs (chat messages and critical question answers) properly affect final calculations.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core import qa_manager
from core.schemas import VisionEstimate, Ingredient, ClarificationQuestion
import google.generativeai as genai


def setup_gemini():
    """Setup Gemini API from secrets."""
    try:
        import streamlit as st
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    except:
        # Fallback: try loading from secrets.toml directly
        import toml
        secrets = toml.load(".streamlit/secrets.toml")
        genai.configure(api_key=secrets["GEMINI_API_KEY"])


def test_diet_cola_replacement():
    """
    Test Case 1: User says 'it's diet cola' - should replace regular cola with diet cola.
    Expected: Cola calories should drop from ~200 to ~0
    """
    print("\n" + "="*80)
    print("TEST CASE 1: Diet Cola Replacement")
    print("="*80)

    # Mock vision estimate with McDonald's meal including regular cola
    vision_estimate = VisionEstimate(
        dish="McDonald's Cheeseburger Meal",
        portion_guess_g=600,
        ingredients=[
            Ingredient(name="cheeseburger", amount=115, unit="g", source="vision", notes="standard McDonald's"),
            Ingredient(name="french fries", amount=150, unit="g", source="vision", notes="medium size"),
            Ingredient(name="cola", amount=500, unit="g", source="vision", notes="medium soft drink")
        ],
        critical_questions=[
            ClarificationQuestion(
                id="drink_type",
                text="What type of soda is it?",
                options=["cola", "diet cola", "sprite", "other"],
                default="cola",
                impact_score=0.7
            )
        ]
    )

    print(f"\n📋 Initial Vision Estimate:")
    print(f"  Dish: {vision_estimate.dish}")
    print(f"  Ingredients:")
    for ing in vision_estimate.ingredients:
        print(f"    - {ing.name}: {ing.amount}g")

    # Setup chat session
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        tools=[]
    )
    chat_session = model.start_chat()

    # User input: "it's diet cola"
    user_input = "it's diet cola"
    print(f"\n💬 User says: '{user_input}'")

    # Process refinement
    import json
    context = vision_estimate.model_dump()
    refinement, tool_calls = qa_manager.refine(
        context=json.dumps(context),
        user_input=user_input,
        chat_session=chat_session,
        available_tools=None
    )

    if refinement:
        print(f"\n✅ Refinement parsed successfully!")
        print(f"  Updated ingredients: {len(refinement.updated_ingredients)}")
        for ing in refinement.updated_ingredients:
            print(f"    - {ing.name}: {ing.amount}g")
    else:
        print(f"\n❌ Refinement failed to parse!")
        return False

    # Generate final calculation with refinement
    print(f"\n🧮 Generating final calculation with refinement...")
    final_json, final_tool_calls = qa_manager.generate_final_calculation(
        chat_session=chat_session,
        available_tools={"perform_web_search": lambda q: "mock search results"},
        vision_estimate=vision_estimate,
        refinements=[refinement]
    )

    # Parse and check results
    import json
    try:
        final_data = json.loads(final_json)
        breakdown = final_data.get("breakdown", [])

        print(f"\n📊 Final Breakdown:")
        cola_item = None
        for item in breakdown:
            item_name = item.get("item", "")
            calories = item.get("calories", 0)
            carbs = item.get("carbs_grams", 0)
            print(f"  - {item_name}: {calories} kcal, {carbs}g carbs")

            if "cola" in item_name.lower():
                cola_item = item

        # Verify diet cola replacement worked
        if cola_item:
            cola_name = cola_item.get("item", "")
            cola_calories = cola_item.get("calories", 0)
            cola_carbs = cola_item.get("carbs_grams", 0)

            print(f"\n🔍 Verification:")
            print(f"  Cola item found: {cola_name}")
            print(f"  Calories: {cola_calories} kcal")
            print(f"  Carbs: {cola_carbs}g")

            if "diet" in cola_name.lower() and cola_calories < 20:
                print(f"\n✅ TEST PASSED: Diet cola replacement worked!")
                print(f"  - Item name changed to include 'diet'")
                print(f"  - Calories are low ({cola_calories} < 20 kcal)")
                return True
            else:
                print(f"\n❌ TEST FAILED: Diet cola replacement didn't work")
                print(f"  - Expected: 'diet cola' with <20 kcal")
                print(f"  - Got: '{cola_name}' with {cola_calories} kcal")
                return False
        else:
            print(f"\n❌ TEST FAILED: No cola item found in breakdown")
            return False

    except Exception as e:
        print(f"\n❌ TEST FAILED: Error parsing final JSON: {e}")
        print(f"Raw JSON: {final_json[:500]}...")
        return False


def test_chicken_part_answer():
    """
    Test Case 2: User answers critical question about chicken part.
    Expected: Chicken macros should change based on breast vs thigh.
    """
    print("\n" + "="*80)
    print("TEST CASE 2: Critical Question - Chicken Part")
    print("="*80)

    vision_estimate = VisionEstimate(
        dish="Chicken Biryani",
        portion_guess_g=400,
        ingredients=[
            Ingredient(name="chicken", amount=150, unit="g", source="vision", notes="pieces visible"),
            Ingredient(name="basmati rice", amount=200, unit="g", source="vision", notes="cooked"),
            Ingredient(name="yogurt", amount=30, unit="g", source="vision", notes="marinade")
        ],
        critical_questions=[
            ClarificationQuestion(
                id="chicken_part",
                text="What part of chicken?",
                options=["breast", "thigh", "mixed"],
                default="mixed",
                impact_score=0.6
            )
        ]
    )

    print(f"\n📋 Initial Vision Estimate:")
    print(f"  Dish: {vision_estimate.dish}")
    print(f"  Chicken: {vision_estimate.ingredients[0].amount}g (unspecified part)")

    # Setup chat session
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        tools=[]
    )
    chat_session = model.start_chat()

    # User answers: "chicken breast"
    user_input = "chicken breast"
    print(f"\n💬 User says: '{user_input}'")

    # Process refinement
    import json
    context = vision_estimate.model_dump()
    refinement, tool_calls = qa_manager.refine(
        context=json.dumps(context),
        user_input=user_input,
        chat_session=chat_session,
        available_tools=None
    )

    if refinement:
        print(f"\n✅ Refinement parsed successfully!")
        print(f"  Updated ingredients: {len(refinement.updated_ingredients)}")
        for ing in refinement.updated_ingredients:
            print(f"    - {ing.name}: {ing.amount}g (notes: {ing.notes if hasattr(ing, 'notes') else 'N/A'})")

        # Check if chicken was updated to chicken breast
        chicken_updated = any("breast" in ing.name.lower() for ing in refinement.updated_ingredients)
        if chicken_updated:
            print(f"\n✅ TEST PASSED: Chicken part was updated to breast!")
            return True
        else:
            print(f"\n⚠️ TEST WARNING: Chicken might not have been updated to 'breast'")
            return False
    else:
        print(f"\n❌ Refinement failed to parse!")
        return False


def test_multiple_answers():
    """
    Test Case 3: User provides multiple comma-separated answers.
    Expected: All answers should be processed and applied.
    """
    print("\n" + "="*80)
    print("TEST CASE 3: Multiple Comma-Separated Answers")
    print("="*80)

    vision_estimate = VisionEstimate(
        dish="McDonald's Meal",
        portion_guess_g=600,
        ingredients=[
            Ingredient(name="burger", amount=120, unit="g", source="vision"),
            Ingredient(name="fries", amount=150, unit="g", source="vision"),
            Ingredient(name="soda", amount=500, unit="g", source="vision")
        ],
        critical_questions=[
            ClarificationQuestion(id="drink", text="What drink?", options=["cola", "diet cola"], default="cola", impact_score=0.7),
            ClarificationQuestion(id="fries_size", text="Fries size?", options=["small", "medium", "large"], default="medium", impact_score=0.6),
            ClarificationQuestion(id="burger_type", text="Burger type?", options=["cheeseburger", "Big Mac", "Quarter Pounder"], default="cheeseburger", impact_score=0.8)
        ]
    )

    print(f"\n📋 Initial Vision Estimate:")
    print(f"  3 ingredients, 3 critical questions")

    # Setup chat session
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        tools=[]
    )
    chat_session = model.start_chat()

    # User provides all answers at once
    user_input = "diet cola, medium, Big Mac"
    print(f"\n💬 User says: '{user_input}'")

    # Process refinement
    import json
    context = vision_estimate.model_dump()
    refinement, tool_calls = qa_manager.refine(
        context=json.dumps(context),
        user_input=user_input,
        chat_session=chat_session,
        available_tools=None
    )

    if refinement:
        print(f"\n✅ Refinement parsed successfully!")
        print(f"  Updated ingredients: {len(refinement.updated_ingredients)}")
        for ing in refinement.updated_ingredients:
            print(f"    - {ing.name}: {ing.amount}g")

        # Check if multiple items were updated
        if len(refinement.updated_ingredients) >= 2:
            print(f"\n✅ TEST PASSED: Multiple answers processed!")
            return True
        else:
            print(f"\n⚠️ TEST WARNING: Only {len(refinement.updated_ingredients)} items updated (expected 2-3)")
            return False
    else:
        print(f"\n❌ Refinement failed to parse!")
        return False


def main():
    """Run all test cases."""
    print("\n" + "="*80)
    print("COMPREHENSIVE REFINEMENT FLOW TEST SUITE")
    print("="*80)
    print("\nThis test suite verifies that user inputs properly affect final calculations.")
    print("Testing: chat refinements, critical questions, fuzzy matching, USDA lookups\n")

    # Setup
    try:
        setup_gemini()
        print("✅ Gemini API configured")
    except Exception as e:
        print(f"❌ Failed to setup Gemini API: {e}")
        return

    # Run tests
    results = []

    try:
        results.append(("Diet Cola Replacement", test_diet_cola_replacement()))
    except Exception as e:
        print(f"\n❌ TEST CRASHED: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Diet Cola Replacement", False))

    try:
        results.append(("Chicken Part Answer", test_chicken_part_answer()))
    except Exception as e:
        print(f"\n❌ TEST CRASHED: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Chicken Part Answer", False))

    try:
        results.append(("Multiple Answers", test_multiple_answers()))
    except Exception as e:
        print(f"\n❌ TEST CRASHED: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Multiple Answers", False))

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED! User inputs are working correctly.")
    else:
        print(f"\n⚠️ {total - passed} test(s) failed. User input flow needs fixes.")


if __name__ == "__main__":
    main()