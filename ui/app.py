import streamlit as st
import google.generativeai as genai
from tavily import TavilyClient
import json
from PIL import Image
import io
import logging
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import new modular components
from core import vision_estimator, qa_manager
from core.schemas import VisionEstimate
from core.json_repair import parse_or_repair_json, validate_macro_sanity
from integrations.search_bridge import create_search_tool_function
from integrations import db, usda_client
from pydantic import BaseModel
from typing import Optional

# Set up logging
logger = logging.getLogger(__name__)

# --- Page Configuration ---
st.set_page_config(
    page_title="Intelligent AI Calorie Estimator",
    page_icon="🧠",
    layout="centered",
    initial_sidebar_state="auto"
)

# --- API Configuration ---
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    TAVILY_API_KEY = st.secrets["TAVILY_API_KEY"]
    genai.configure(api_key=GEMINI_API_KEY)
    tavily = TavilyClient(api_key=TAVILY_API_KEY)

    # Required USDA API key for Phase 2 features
    USDA_API_KEY = st.secrets.get("USDA_API_KEY")
    if USDA_API_KEY:
        usda_client.set_api_key(USDA_API_KEY)
    else:
        st.error("USDA API key not found. Phase 2 nutrition lookup requires USDA_API_KEY in your secrets.toml file.", icon="⚠️")
        st.stop()

except (FileNotFoundError, KeyError):
    st.error("API keys not found in secrets. Please check your .streamlit/secrets.toml file.", icon="⚠️")
    st.stop()


# --- Tool Setup ---
search_function = create_search_tool_function(tavily)


# --- Model and Tool Initialization ---
my_search_tool = genai.protos.Tool(
    function_declarations=[
        genai.protos.FunctionDeclaration(
            name='perform_web_search',
            description="Performs a web search using the Tavily API to find nutritional information for specific food items, especially branded or restaurant items. Use this to find calorie counts, macronutrient breakdowns (protein, carbs, fat), and average weights or serving sizes. For example: 'calories in Burger King Whopper' or 'average weight of a Walmart Great Value chicken breast'.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    'query': genai.protos.Schema(type=genai.protos.Type.STRING,
                                                 description="The precise search query string.")
                },
                required=['query']
            )
        )
    ]
)

available_tools = {
    "perform_web_search": search_function,
}

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash-lite",
    tools=[my_search_tool]
)


def load_css():
    st.markdown("""<style>/* Your custom CSS can go here */</style>""", unsafe_allow_html=True)


def parse_weight_overrides(weight_text: str) -> list[dict]:
    """
    Parse user input like 'chicken 165g, rice 180g, olive oil 10g' into structured updates.

    Args:
        weight_text: Comma-separated list of ingredient weights

    Returns:
        List of ingredient updates with name and amount
    """
    import re

    updates = []
    # Split by comma and process each item
    items = [item.strip() for item in weight_text.split(',')]

    for item in items:
        # Look for pattern: ingredient_name number(g|grams)
        match = re.search(r'(.+?)\s+(\d+(?:\.\d+)?)\s*g(?:rams)?', item, re.IGNORECASE)
        if match:
            ingredient_name = match.group(1).strip()
            amount = float(match.group(2))
            updates.append({
                "name": ingredient_name,
                "amount": amount
            })

    return updates


def display_vision_estimate(estimate: VisionEstimate) -> str:
    """
    Converts a VisionEstimate to a user-friendly display format.
    Returns a string similar to the original LLM output for consistency.
    """
    display_text = f"I can see this is **{estimate.dish}**.\n\n"
    display_text += f"Based on visual analysis, I estimate the total portion weighs approximately **{estimate.portion_guess_g}g**.\n\n"

    display_text += "**Ingredients I can identify:**\n"
    for ingredient in estimate.ingredients:
        notes_text = f" ({ingredient.notes})" if ingredient.notes else ""
        display_text += f"- {ingredient.name}: ~{ingredient.amount}g{notes_text}\n"

    if estimate.critical_questions:
        display_text += "\n**I have a few questions to improve accuracy:**\n"
        for question in estimate.critical_questions:
            display_text += f"- {question.text}\n"
            if question.options:
                display_text += f"  Options: {', '.join(question.options)}\n"

    return display_text


def main():
    load_css()
    st.title("Intelligent AI Calorie Estimator 🧠")

    # Initialize database for logging
    db.init()

    if "analysis_stage" not in st.session_state:
        st.session_state.analysis_stage = "upload"
    if "uploaded_image_data" not in st.session_state:
        st.session_state.uploaded_image_data = None
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "vision_estimate" not in st.session_state:
        st.session_state.vision_estimate = None

    if st.session_state.analysis_stage == "upload":
        st.info("Upload a food photo. The AI will act as your expert estimator.", icon="🧑‍🔬")
        uploaded_file = st.file_uploader("Upload an image of your meal...", type=["jpg", "jpeg", "png"])
        if uploaded_file:
            st.session_state.uploaded_image_data = uploaded_file.getvalue()
            st.session_state.analysis_stage = "analyzing"
            st.rerun()

    if st.session_state.analysis_stage == "analyzing":
        st.image(st.session_state.uploaded_image_data, caption="Your meal.", use_container_width=True)
        if st.button("🔍 Analyze Food"):
            with st.spinner("Performing expert analysis..."):
                # Use the new vision estimator with tool support
                estimate, vision_tool_calls = vision_estimator.estimate(st.session_state.uploaded_image_data, model, available_tools)

                if estimate is None:
                    st.error("Failed to analyze the image. Please try again.", icon="❌")
                    return

                # Track tool calls
                st.session_state.tool_calls_count = st.session_state.get("tool_calls_count", 0) + vision_tool_calls

                # Store the structured estimate
                st.session_state.vision_estimate = estimate

                # Convert structured estimate to conversational response for display
                display_response = display_vision_estimate(estimate)

                # Create a mock message for display consistency
                st.session_state.messages = [
                    type('MockMessage', (), {
                        'role': 'model',
                        'parts': [type('MockPart', (), {'text': display_response})()]
                    })()
                ]

                st.session_state.analysis_stage = "conversation"
                st.rerun()

    if st.session_state.analysis_stage == "conversation":
        st.subheader("Refine Details with the AI", divider='rainbow')

        # Display the initial vision estimate
        if st.session_state.messages:
            for message in st.session_state.messages:
                if hasattr(message, 'role') and message.role == "model":
                    with st.chat_message("assistant"):
                        st.markdown(message.parts[0].text)

        # Display critical questions with answer input
        if st.session_state.vision_estimate and st.session_state.vision_estimate.critical_questions:
            with st.expander("📋 Questions to improve accuracy", expanded=True):
                for i, question in enumerate(st.session_state.vision_estimate.critical_questions, 1):
                    st.markdown(f"**{i}. {question.text}**")
                    if question.options:
                        st.caption(f"Options: {', '.join(question.options)}")

        # Create or reuse chat session for conversation persistence
        if "conversation_chat" not in st.session_state:
            st.session_state.conversation_chat = model.start_chat()
        conversation_chat = st.session_state.conversation_chat

        # Main answer input - can be used either by pressing Enter OR clicking Calculate button
        st.markdown("### Answer Questions / Provide Details")

        # Initialize pending_answer in session state if needed
        if "pending_answer" not in st.session_state:
            st.session_state.pending_answer = ""

        answer_input = st.text_input(
            "Type your answers here (e.g., 'diet cola, medium' or 'diet, medium')",
            placeholder="Example: diet cola, medium fries",
            key="answer_input_box",
            help="You can answer critical questions above, or provide any clarifications. Formats like 'diet cola', 'diet, medium', or full sentences all work!"
        )

        # Process button for immediate refinement (optional - user can also just click Calculate)
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("💬 Submit Answer") and answer_input:
                with st.spinner("Processing your input..."):
                    # Process the answer immediately
                    context = st.session_state.vision_estimate.model_dump() if st.session_state.vision_estimate else {}
                    refinement, qa_tool_calls = qa_manager.refine(
                        context=json.dumps(context),
                        user_input=answer_input,
                        chat_session=conversation_chat,
                        available_tools=available_tools
                    )

                    # Track tool calls
                    st.session_state.tool_calls_count = st.session_state.get("tool_calls_count", 0) + qa_tool_calls

                    if refinement:
                        # Display the structured response
                        response_text = "✅ Thank you! I've updated my understanding:\n\n"

                        if refinement.updated_ingredients:
                            response_text += "**Updated ingredients:**\n"
                            for ingredient in refinement.updated_ingredients:
                                notes_text = f" ({ingredient.notes})" if ingredient.notes else ""
                                response_text += f"- {ingredient.name}: {ingredient.amount}g{notes_text}\n"

                        st.success(response_text)

                        # Store the refinement for final calculation
                        if "refinements" not in st.session_state:
                            st.session_state.refinements = []
                        st.session_state.refinements.append(refinement)

                        # Rerun to refresh (input will be cleared automatically)
                        st.rerun()
                    else:
                        st.warning("I'm having trouble understanding that. Please try rephrasing (e.g., 'diet cola, medium')")

        st.divider()

        # Show refinement status
        refinement_count = len(st.session_state.get('refinements', []))
        if refinement_count > 0:
            st.info(f"✅ {refinement_count} refinement(s) submitted", icon="✅")

        # Calculate button - NOW auto-processes any pending answer
        if st.button("🎯 Calculate Final Estimate", type="primary"):
            # FIRST: Check if there's any pending answer that hasn't been submitted
            if answer_input and answer_input.strip():
                with st.spinner("Processing your pending answer..."):
                    context = st.session_state.vision_estimate.model_dump() if st.session_state.vision_estimate else {}
                    refinement, qa_tool_calls = qa_manager.refine(
                        context=json.dumps(context),
                        user_input=answer_input,
                        chat_session=conversation_chat,
                        available_tools=available_tools
                    )

                    # Track tool calls
                    st.session_state.tool_calls_count = st.session_state.get("tool_calls_count", 0) + qa_tool_calls

                    if refinement:
                        # Store the refinement
                        if "refinements" not in st.session_state:
                            st.session_state.refinements = []
                        st.session_state.refinements.append(refinement)

            # THEN: Generate final calculation with all refinements
            with st.spinner("Calculating final nutrition breakdown..."):
                final_response, final_tool_calls = qa_manager.generate_final_calculation(
                    st.session_state.get('conversation_chat', conversation_chat),
                    available_tools,
                    vision_estimate=st.session_state.get('vision_estimate'),
                    refinements=st.session_state.get('refinements', [])
                )

                # Track tool calls
                st.session_state.tool_calls_count = st.session_state.get("tool_calls_count", 0) + final_tool_calls
                st.session_state.final_analysis = final_response
                st.session_state.analysis_stage = "results"
                st.rerun()

    if st.session_state.analysis_stage == "results":
        st.success("### Here is your detailed nutritional estimate:", icon="🎉")
        raw_text = st.session_state.get("final_analysis", "")
        try:
            # Use the same repair logic as the rest of the app
            # Full Pydantic model with all expected fields
            class AttributionItem(BaseModel):
                name: str
                fdc_id: int

            class ValidationResult(BaseModel):
                ok: bool = True
                delta_pct: Optional[float] = None
                expected: Optional[float] = None
                actual: Optional[float] = None
                tolerance: Optional[float] = None

            class Validations(BaseModel):
                four_four_nine: Optional[ValidationResult] = None
                portion_warnings: Optional[list[dict]] = None
                confidence: Optional[float] = None
                summary: Optional[dict] = None

            class FinalBreakdownModel(BaseModel):
                breakdown: list[dict]
                attribution: Optional[list[AttributionItem]] = []
                validations: Optional[Validations] = None

            parsed_data, errors = parse_or_repair_json(raw_text, FinalBreakdownModel)

            if parsed_data is None:
                raise ValueError(f"Could not parse final breakdown JSON: {errors}")

            data = parsed_data.model_dump()

            breakdown_list = data.get("breakdown", [])
            attribution_list = data.get("attribution", [])
            validations = data.get("validations", {})

            # Log validation issues (don't display to user to maintain trust)
            four_four_nine = validations.get("four_four_nine", {})
            portion_warnings = validations.get("portion_warnings", [])

            # Log 4/4/9 macro validation issues
            if not four_four_nine.get("ok", True):
                delta_pct = four_four_nine.get("delta_pct", 0)
                logger.warning(f"4/4/9 validation failed: calorie calculation off by {delta_pct:.1%} from expected macro ratios")

            # Log portion size warnings
            if portion_warnings:
                logger.warning(f"Portion size warnings detected: {len(portion_warnings)} warnings")
                for warning in portion_warnings:
                    logger.warning(f"Portion warning: {warning.get('message', 'Unknown portion warning')}")

            # Log legacy validation issues if new validation data is missing
            if not validations:
                is_valid, validation_errors = validate_macro_sanity(data)
                if not is_valid:
                    logger.warning(f"Legacy validation failed: {validation_errors}")
                    for error in validation_errors:
                        logger.warning(f"Legacy validation error: {error}")

            if not breakdown_list:
                st.warning("The AI was unable to provide a breakdown. Please try again.")

            # Create attribution lookup by name
            attribution_map = {attr.get("name", "").lower(): attr.get("fdc_id") for attr in attribution_list}

            total_calories, total_protein, total_carbs, total_fat = 0, 0, 0, 0
            display_data = []

            for item in breakdown_list:
                # Extract as floats (preserve precision until final rounding)
                calories = float(item.get("calories", 0) or 0.0)
                protein = float(item.get("protein_grams", 0) or 0.0)
                carbs = float(item.get("carbs_grams", 0) or 0.0)
                fat = float(item.get("fat_grams", 0) or 0.0)

                # Accumulate raw values
                total_calories += calories
                total_protein += protein
                total_carbs += carbs
                total_fat += fat

                # Check if this item has USDA grounding
                item_name = item.get("item", "N/A")
                fdc_id = attribution_map.get(item_name.lower())

                # Add USDA badge if grounded
                if fdc_id:
                    item_display = f"{item_name} 🏛️"  # USDA badge
                else:
                    item_display = item_name

                # Round only for display (nearest 1g policy)
                display_data.append({
                    "Item": item_display,
                    "Calories": f"{round(calories)} kcal",
                    "Protein": f"{round(protein)}g",
                    "Carbs": f"{round(carbs)}g",
                    "Fat": f"{round(fat)}g",
                })

            st.table(display_data)

            # Show USDA attribution info
            if attribution_list:
                with st.expander("📊 USDA Data Attribution"):
                    st.caption("Items marked with 🏛️ are grounded using USDA FoodData Central:")
                    for attr in attribution_list:
                        st.caption(f"• {attr.get('name', 'Unknown')}: FDC ID {attr.get('fdc_id', 'N/A')}")
                    st.caption("Learn more at [USDA FoodData Central](https://fdc.nal.usda.gov/)")
            st.subheader("Calculated Totals", divider='rainbow')
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Calories", f"{round(total_calories)} kcal")
            col2.metric("Total Protein", f"{round(total_protein)}g")
            col3.metric("Total Carbs", f"{round(total_carbs)}g")
            col4.metric("Total Fat", f"{round(total_fat)}g")

            # Log successful session to database
            if st.session_state.vision_estimate and not st.session_state.get("session_logged", False):
                try:
                    session_id = db.log_session(
                        estimate=st.session_state.vision_estimate,
                        refinements=st.session_state.get("refinements", []),
                        final_json=raw_text,
                        tool_calls_count=st.session_state.get("tool_calls_count", 0)
                    )
                    st.session_state.session_logged = True
                    st.caption(f"📊 Session logged (ID: {session_id}) for future improvements")
                except Exception as e:
                    print(f"Failed to log session: {e}")

        except (ValueError, json.JSONDecodeError) as e:
            st.error(f"Could not parse the final analysis. Error: {e}", icon="🤷")
            st.write("Raw AI response for debugging:")
            st.code(raw_text)

        if st.button("Start Over"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

if __name__ == "__main__":
    main()