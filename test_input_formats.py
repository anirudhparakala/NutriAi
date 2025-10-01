"""
Test different user input formats to see if the LLM can handle:
- Short answers: "diet cola"
- Keywords only: "diet, medium"
- Comma-separated: "diet cola, medium fries"
- Full sentences: "it's a diet cola and medium fries"
- Typos: "diet sooda"
"""

import google.generativeai as genai
from tavily import TavilyClient
import json
import sys
import os

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


def test_input_format(test_name, user_input, vision_estimate):
    """
    Test a specific user input format and see what the LLM returns.
    """
    print("\n" + "=" * 100)
    print(f"TEST: {test_name}")
    print("=" * 100)
    print(f"User Input: '{user_input}'")
    print("-" * 100)

    chat_session = model.start_chat()
    context = vision_estimate.model_dump_json()

    try:
        refinement, tool_calls = qa_manager.refine(
            context=context,
            user_input=user_input,
            chat_session=chat_session,
            available_tools=available_tools
        )

        if refinement and refinement.updated_ingredients:
            print(f"\n[SUCCESS] LLM understood and returned {len(refinement.updated_ingredients)} ingredients:")
            for ing in refinement.updated_ingredients:
                print(f"  - {ing.name}: {ing.amount}g")
            return True
        else:
            print(f"\n[FAIL] LLM did not return valid ingredients")
            return False

    except Exception as e:
        print(f"\n[ERROR] Exception: {e}")
        return False


# Mock vision estimate with critical questions
vision_estimate = VisionEstimate(
    dish="McDonald's Meal",
    portion_guess_g=625,
    ingredients=[
        Ingredient(name="cheeseburger", amount=115, unit="g", source="vision"),
        Ingredient(name="french fries", amount=110, unit="g", source="vision"),
        Ingredient(name="soft drink", amount=400, unit="g", source="vision")
    ],
    critical_questions=[
        ClarificationQuestion(
            id="drink_type",
            text="What type of drink is it?",
            options=["cola", "diet cola", "sprite", "fanta"],
            default="cola",
            impact_score=0.8
        ),
        ClarificationQuestion(
            id="fry_size",
            text="What size are the fries?",
            options=["small", "medium", "large"],
            default="medium",
            impact_score=0.7
        )
    ]
)

print("#" * 100)
print("# TESTING DIFFERENT USER INPUT FORMATS")
print("#" * 100)
print("\nOriginal Vision Estimate:")
for ing in vision_estimate.ingredients:
    print(f"  - {ing.name}: {ing.amount}g")
print("\nCritical Questions:")
for q in vision_estimate.critical_questions:
    print(f"  - {q.text}")
    print(f"    Options: {', '.join(q.options)}")

# Test different input formats
results = {}

# Test 1: Two-word answer
results['two_word'] = test_input_format(
    "Two-word answer",
    "diet cola",
    vision_estimate
)

# Test 2: Comma-separated keywords (matching question order)
results['comma_keywords'] = test_input_format(
    "Comma-separated keywords",
    "diet cola, medium",
    vision_estimate
)

# Test 3: Just keywords (no separators)
results['keywords_only'] = test_input_format(
    "Keywords only",
    "diet medium",
    vision_estimate
)

# Test 4: Full sentence
results['full_sentence'] = test_input_format(
    "Full sentence",
    "it's a diet cola and medium fries",
    vision_estimate
)

# Test 5: Comma-separated full items
results['comma_full'] = test_input_format(
    "Comma-separated full items",
    "diet cola, medium fries",
    vision_estimate
)

# Test 6: Single word per question
results['single_words'] = test_input_format(
    "Single words",
    "diet, medium",
    vision_estimate
)

# Test 7: Typo in input
results['typo'] = test_input_format(
    "With typo",
    "diet sooda, medium",
    vision_estimate
)

# Test 8: Reversed order (fries first, drink second)
results['reversed_order'] = test_input_format(
    "Reversed order",
    "medium fries, diet cola",
    vision_estimate
)

# Test 9: One answer only (ignoring second question)
results['partial_answer'] = test_input_format(
    "Partial answer (only drink)",
    "diet cola",
    vision_estimate
)

# Test 10: Casual natural language
results['casual'] = test_input_format(
    "Casual natural language",
    "its diet and medium size",
    vision_estimate
)

# Summary
print("\n\n")
print("#" * 100)
print("# RESULTS SUMMARY")
print("#" * 100)

print("\nInput Format Success Rates:")
print("-" * 100)
for test_name, success in results.items():
    status = "[PASS]" if success else "[FAIL]"
    print(f"{status} {test_name}")

success_count = sum(1 for s in results.values() if s)
total_count = len(results)
success_rate = (success_count / total_count) * 100

print("\n" + "=" * 100)
print(f"OVERALL: {success_count}/{total_count} formats worked ({success_rate:.0f}% success rate)")
print("=" * 100)

if success_rate >= 80:
    print("\n*** LLM is VERY ROBUST - handles most input formats! ***")
elif success_rate >= 50:
    print("\n*** LLM is MODERATELY ROBUST - handles common formats ***")
else:
    print("\n*** LLM has LOW ROBUSTNESS - users need specific format ***")

print("\n" + "#" * 100)
