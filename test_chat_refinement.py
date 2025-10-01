"""
Test the chat refinement flow to see what the LLM returns when user says 'diet cola'
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

# Load API keys
try:
    import toml
    with open('.streamlit/secrets.toml', 'r') as f:
        secrets = toml.load(f)
    GEMINI_API_KEY = secrets['GEMINI_API_KEY']
    TAVILY_API_KEY = secrets['TAVILY_API_KEY']
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

# Create a mock vision estimate (McDonald's meal with regular cola)
vision_estimate = VisionEstimate(
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
            options=["cola", "diet cola", "sprite", "fanta", "other"],
            default="cola",
            impact_score=0.8
        )
    ]
)

print("=" * 80)
print("MOCK VISION ESTIMATE:")
print("=" * 80)
print(f"Dish: {vision_estimate.dish}")
print(f"\nIngredients:")
for ing in vision_estimate.ingredients:
    print(f"  - {ing.name}: {ing.amount}g")
print(f"\nCritical Questions:")
for q in vision_estimate.critical_questions:
    print(f"  - {q.text}")
    print(f"    Options: {', '.join(q.options)}")

print("\n" + "=" * 80)
print("SIMULATING USER TYPING 'diet cola' AND PRESSING ENTER")
print("=" * 80)

# Create chat session
chat_session = model.start_chat()

# Simulate user refinement
user_input = "diet cola"
context = vision_estimate.model_dump_json()

print(f"\nCalling qa_manager.refine() with user_input: '{user_input}'")
print("-" * 80)

refinement, tool_calls = qa_manager.refine(
    context=context,
    user_input=user_input,
    chat_session=chat_session,
    available_tools=available_tools
)

print("\n" + "=" * 80)
print("REFINEMENT RESULT:")
print("=" * 80)

if refinement:
    print(f"✅ Refinement returned successfully")
    print(f"\nUpdated Ingredients ({len(refinement.updated_ingredients)}):")
    for ing in refinement.updated_ingredients:
        print(f"  - {ing.name}: {ing.amount}g (source: {ing.source})")

    print(f"\nUpdated Assumptions ({len(refinement.updated_assumptions)}):")
    for assumption in refinement.updated_assumptions:
        print(f"  - {assumption.key}: {assumption.value} (confidence: {assumption.confidence:.1%})")
else:
    print(f"❌ Refinement returned None - parsing failed!")

print("\n" + "=" * 80)
print("WHAT SHOULD HAPPEN NEXT:")
print("=" * 80)
print("When generate_final_calculation() is called:")
print("1. Original ingredients: cheeseburger, fries, medium soft drink")
print("2. Apply refinement above")
print("3. Should replace 'medium soft drink' with 'diet cola'")
print("4. USDA lookup for 'diet cola' → ~0 calories")
print("=" * 80)
