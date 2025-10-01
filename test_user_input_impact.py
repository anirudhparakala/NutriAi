"""
Test to verify that user inputs (diet vs regular, medium vs large) actually affect final calorie calculations.
This will prove whether the refinement → USDA lookup → final result pipeline works end-to-end.
"""

import google.generativeai as genai
from tavily import TavilyClient
import json
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core import qa_manager
from core.schemas import VisionEstimate, Ingredient, ClarificationQuestion
from integrations.search_bridge import create_search_tool_function
from integrations import usda_client

# Load API keys
try:
    import toml
    with open('.streamlit/secrets.toml', 'r', encoding='utf-8') as f:
        secrets = toml.load(f)
    GEMINI_API_KEY = secrets['GEMINI_API_KEY']
    TAVILY_API_KEY = secrets['TAVILY_API_KEY']
    USDA_API_KEY = secrets.get('USDA_API_KEY')

    if USDA_API_KEY:
        usda_client.set_api_key(USDA_API_KEY)
except Exception as e:
    print(f"Error loading secrets: {e}")
    sys.exit(1)

# Configure
genai.configure(api_key=GEMINI_API_KEY)
tavily = TavilyClient(api_key=TAVILY_API_KEY)

# Setup tools
search_function = create_search_tool_function(tavily)
available_tools = {"perform_web_search": search_function}

my_search_tool = genai.protos.Tool(
    function_declarations=[
        genai.protos.FunctionDeclaration(
            name='perform_web_search',
            description="Performs a web search using the Tavily API",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    'query': genai.protos.Schema(type=genai.protos.Type.STRING)
                },
                required=['query']
            )
        )
    ]
)

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash-lite",
    tools=[my_search_tool]
)


def run_test_scenario(scenario_name, vision_estimate, user_input, expected_behavior):
    """
    Run a single test scenario and return the final calorie count.

    Args:
        scenario_name: Name of the test scenario
        vision_estimate: Mock VisionEstimate object
        user_input: User's chat input (e.g., "diet cola")
        expected_behavior: Description of what should happen

    Returns:
        Final total calories from the breakdown
    """
    print("\n" + "=" * 100)
    print(f"TEST SCENARIO: {scenario_name}")
    print("=" * 100)

    print(f"\nInitial Vision Estimate:")
    for ing in vision_estimate.ingredients:
        print(f"  - {ing.name}: {ing.amount}g")

    print(f"\nUser Input: '{user_input}'")
    # Encode to ASCII to avoid Windows console issues
    safe_behavior = expected_behavior.encode('ascii', 'replace').decode('ascii')
    print(f"Expected Behavior: {safe_behavior}")

    # Step 1: Get refinement from user input
    print("\n" + "-" * 100)
    print("STEP 1: Processing User Refinement")
    print("-" * 100)

    chat_session = model.start_chat()
    context = vision_estimate.model_dump_json()

    refinement, tool_calls = qa_manager.refine(
        context=context,
        user_input=user_input,
        chat_session=chat_session,
        available_tools=available_tools
    )

    if refinement:
        print(f"\nRefinement successful! Updated ingredients:")
        for ing in refinement.updated_ingredients:
            print(f"  - {ing.name}: {ing.amount}g")
    else:
        print(f"\nERROR: Refinement failed!")
        return None

    # Step 2: Generate final calculation
    print("\n" + "-" * 100)
    print("STEP 2: Generating Final Calculation with USDA Lookups")
    print("-" * 100)

    refinements = [refinement]

    final_json, final_tool_calls = qa_manager.generate_final_calculation(
        chat_session,
        available_tools,
        vision_estimate=vision_estimate,
        refinements=refinements
    )

    # Parse the final JSON
    final_data = json.loads(final_json)
    breakdown = final_data.get('breakdown', [])

    print(f"\nFinal Breakdown:")
    total_calories = 0
    for item in breakdown:
        item_name = item.get('item', 'Unknown')
        calories = item.get('calories', 0)
        protein = item.get('protein_grams', 0)
        carbs = item.get('carbs_grams', 0)
        fat = item.get('fat_grams', 0)

        print(f"  - {item_name}: {calories} kcal (P:{protein}g C:{carbs}g F:{fat}g)")
        total_calories += calories

    print(f"\n>>> TOTAL CALORIES: {total_calories} kcal <<<")

    return total_calories


# ============================================================================
# TEST 1: Diet Cola vs Regular Cola
# ============================================================================

print("\n")
print("#" * 100)
print("# TEST SET 1: DIET COLA VS REGULAR COLA")
print("#" * 100)

vision_estimate_drink = VisionEstimate(
    dish="McDonald's Cheeseburger Meal",
    portion_guess_g=625,
    ingredients=[
        Ingredient(name="cheeseburger", amount=115, unit="g", source="vision"),
        Ingredient(name="medium french fries", amount=110, unit="g", source="vision"),
        Ingredient(name="medium soft drink", amount=400, unit="g", source="vision", notes="appears to be cola")
    ],
    critical_questions=[
        ClarificationQuestion(
            id="drink_type",
            text="What type of drink is it?",
            options=["cola", "diet cola", "sprite", "fanta"],
            default="cola",
            impact_score=0.8
        )
    ]
)

# Test 1A: Diet Cola
calories_diet = run_test_scenario(
    scenario_name="1A: User says 'diet cola'",
    vision_estimate=vision_estimate_drink,
    user_input="diet cola",
    expected_behavior="Should replace 'medium soft drink' with 'diet cola' - USDA lookup - about 0 calories for drink"
)

# Test 1B: Regular Cola
calories_regular = run_test_scenario(
    scenario_name="1B: User says 'regular cola'",
    vision_estimate=vision_estimate_drink,
    user_input="regular cola",
    expected_behavior="Should replace 'medium soft drink' with 'cola' - USDA lookup - about 140-180 calories for drink"
)

print("\n" + "=" * 100)
print("TEST SET 1 RESULTS:")
print("=" * 100)
print(f"Diet Cola Total:    {calories_diet} kcal")
print(f"Regular Cola Total: {calories_regular} kcal")

if calories_diet is not None and calories_regular is not None:
    diff = calories_regular - calories_diet
    print(f"Difference:         {diff} kcal")

    if diff > 100:
        print(f"[PASS] Diet cola has {diff} fewer calories than regular (user input DOES affect output!)")
    else:
        print(f"[FAIL] Diet and regular cola have similar calories (user input NOT affecting output!)")
else:
    print(f"[ERROR] One or both tests failed")


# ============================================================================
# TEST 2: Medium Fries vs Large Fries
# ============================================================================

print("\n\n")
print("#" * 100)
print("# TEST SET 2: MEDIUM FRIES VS LARGE FRIES")
print("#" * 100)

vision_estimate_fries = VisionEstimate(
    dish="McDonald's French Fries",
    portion_guess_g=120,
    ingredients=[
        Ingredient(name="french fries", amount=120, unit="g", source="vision")
    ],
    critical_questions=[
        ClarificationQuestion(
            id="fry_size",
            text="What size are the fries?",
            options=["small", "medium", "large"],
            default="medium",
            impact_score=0.9
        )
    ]
)

# Test 2A: Medium Fries
calories_medium = run_test_scenario(
    scenario_name="2A: User says 'medium fries'",
    vision_estimate=vision_estimate_fries,
    user_input="medium fries",
    expected_behavior="Should update to medium portion (about 110g) - USDA lookup"
)

# Test 2B: Large Fries
calories_large = run_test_scenario(
    scenario_name="2B: User says 'large fries'",
    vision_estimate=vision_estimate_fries,
    user_input="large fries",
    expected_behavior="Should update to large portion (about 150g) - USDA lookup"
)

print("\n" + "=" * 100)
print("TEST SET 2 RESULTS:")
print("=" * 100)
print(f"Medium Fries Total: {calories_medium} kcal")
print(f"Large Fries Total:  {calories_large} kcal")

if calories_medium is not None and calories_large is not None:
    diff = calories_large - calories_medium
    print(f"Difference:         {diff} kcal")

    if diff > 50:
        print(f"[PASS] Large fries has {diff} more calories than medium (user input DOES affect output!)")
    else:
        print(f"[FAIL] Medium and large fries have similar calories (user input NOT affecting output!)")
else:
    print(f"[ERROR] One or both tests failed")


# ============================================================================
# FINAL SUMMARY
# ============================================================================

print("\n\n")
print("#" * 100)
print("# FINAL SUMMARY")
print("#" * 100)

test1_pass = calories_diet is not None and calories_regular is not None and (calories_regular - calories_diet) > 100
test2_pass = calories_medium is not None and calories_large is not None and (calories_large - calories_medium) > 50

print(f"\nTest 1 (Diet vs Regular Cola): {'[PASS]' if test1_pass else '[FAIL]'}")
print(f"Test 2 (Medium vs Large Fries): {'[PASS]' if test2_pass else '[FAIL]'}")

if test1_pass and test2_pass:
    print("\n*** ALL TESTS PASSED! User input correctly affects final calorie calculations! ***")
else:
    print("\n*** SOME TESTS FAILED! User input may not be properly affecting the final results. ***")

print("\n" + "#" * 100)
