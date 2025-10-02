"""
Test that the LLM can handle ambiguous answers like "regular" when critical questions provide context.
"""

import google.generativeai as genai
from tavily import TavilyClient
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

# Mock vision estimate with critical questions
vision_estimate = VisionEstimate(
    dish="McDonald's Cheeseburger Meal",
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

print("=" * 100)
print("TEST: Ambiguous answer 'regular, medium' should be interpreted as 'regular cola, medium fries'")
print("=" * 100)
print("\nCritical Questions:")
for q in vision_estimate.critical_questions:
    print(f"  - {q.text}")
    print(f"    Options: {', '.join(q.options)}")

print("\nUser input: 'regular, medium'")
print("\nExpected behavior:")
print("  - 'regular' should map to question 1 (drink) -> 'cola' or 'regular cola'")
print("  - 'medium' should map to question 2 (fries) -> 'medium fries'")
print("  - Result: soft drink should become 'cola' (not stay as 'soft drink')")

print("\n" + "-" * 100)
print("Processing refinement...")
print("-" * 100)

chat_session = model.start_chat()
context = vision_estimate.model_dump_json()

refinement, tool_calls = qa_manager.refine(
    context=context,
    user_input="regular, medium",
    chat_session=chat_session,
    available_tools=available_tools
)

print("\n" + "=" * 100)
print("RESULT:")
print("=" * 100)

if refinement and refinement.updated_ingredients:
    print(f"\n[SUCCESS] LLM returned {len(refinement.updated_ingredients)} ingredients:")
    for ing in refinement.updated_ingredients:
        print(f"  - {ing.name}: {ing.amount}g")

    # Check if soft drink was correctly replaced with cola
    drink_names = [ing.name.lower() for ing in refinement.updated_ingredients]

    if "cola" in drink_names or "regular cola" in drink_names:
        print("\n[PASS] Drink correctly identified as 'cola' or 'regular cola'")
    elif "soft drink" in drink_names:
        print("\n[FAIL] Drink still named 'soft drink' - ambiguous 'regular' not interpreted correctly")
    else:
        print(f"\n[UNKNOWN] Unexpected drink name: {drink_names}")
else:
    print("\n[FAIL] Refinement failed or returned no ingredients")

print("\n" + "=" * 100)
