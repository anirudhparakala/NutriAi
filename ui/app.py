import streamlit as st
import google.generativeai as genai
from tavily import TavilyClient
import json
from PIL import Image
import io

# Import new modular components
from core import vision_estimator, qa_manager
from core.schemas import VisionEstimate
from core.json_repair import parse_or_repair_json, validate_macro_sanity
from integrations.search_bridge import create_search_tool_function
from integrations import db, usda
from pydantic import BaseModel

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

    # Optional USDA API key for Phase 2 features
    USDA_API_KEY = st.secrets.get("USDA_API_KEY")
    if USDA_API_KEY:
        usda.set_api_key(USDA_API_KEY)
    else:
        st.warning("USDA API key not found. Phase 2 nutrition lookup features will be limited. Add USDA_API_KEY to your secrets.toml for enhanced functionality.", icon="💡")

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
    model_name="gemini-1.5-pro-latest",
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

        # Create or reuse chat session for conversation persistence
        if "conversation_chat" not in st.session_state:
            st.session_state.conversation_chat = model.start_chat()
        conversation_chat = st.session_state.conversation_chat

        if prompt := st.chat_input("Provide more details..."):
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.spinner("Processing your input..."):
                # Use structured QA manager instead of free-form chat
                context = st.session_state.vision_estimate.model_dump() if st.session_state.vision_estimate else {}
                refinement, qa_tool_calls = qa_manager.refine(
                    context=json.dumps(context),
                    user_input=prompt,
                    chat_session=conversation_chat,
                    available_tools=available_tools
                )

                # Track tool calls
                st.session_state.tool_calls_count = st.session_state.get("tool_calls_count", 0) + qa_tool_calls

                if refinement:
                    # Display the structured response
                    response_text = "Thank you for the clarification! I've updated my understanding:\n\n"

                    if refinement.updated_ingredients:
                        response_text += "**Updated ingredients:**\n"
                        for ingredient in refinement.updated_ingredients:
                            notes_text = f" ({ingredient.notes})" if ingredient.notes else ""
                            response_text += f"- {ingredient.name}: {ingredient.amount}g{notes_text}\n"
                        response_text += "\n"

                    if refinement.updated_assumptions:
                        response_text += "**Updated assumptions:**\n"
                        for assumption in refinement.updated_assumptions:
                            response_text += f"- {assumption.key}: {assumption.value} (confidence: {assumption.confidence:.1%})\n"

                    with st.chat_message("assistant"):
                        st.markdown(response_text)

                    # Store the refinement for final calculation
                    if "refinements" not in st.session_state:
                        st.session_state.refinements = []
                    st.session_state.refinements.append(refinement)
                else:
                    # Fallback if structured parsing failed
                    with st.chat_message("assistant"):
                        st.markdown("I understand your input, but I'm having trouble processing it in a structured way. Please try rephrasing your clarification.")

                # Conversation chat is already in session state

        # Add polite user override for known weights
        st.caption("💡 If you know exact grams for anything, type them (e.g., 'rice 180g, chicken 165g') and I'll recalc more accurately.")

        weight_override = st.text_area(
            "Optional: Provide exact weights (e.g., 'chicken 165g, rice 180g, olive oil 10g')",
            placeholder="chicken 165g, rice 180g, olive oil 10g",
            height=60
        )

        if weight_override and st.button("🔄 Update with Your Weights"):
            # Parse user weight inputs
            weight_updates = parse_weight_overrides(weight_override)
            if weight_updates:
                # Create a refinement with user-provided weights
                user_refinement_text = f"I can provide exact weights: {weight_override}"
                context = st.session_state.vision_estimate.model_dump() if st.session_state.vision_estimate else {}
                refinement, weights_tool_calls = qa_manager.refine(
                    context=json.dumps(context),
                    user_input=user_refinement_text,
                    chat_session=st.session_state.get('conversation_chat', conversation_chat),
                    available_tools=available_tools
                )

                # Track tool calls
                st.session_state.tool_calls_count = st.session_state.get("tool_calls_count", 0) + weights_tool_calls

                if refinement:
                    st.success(f"✅ Updated {len(refinement.updated_ingredients)} ingredients with your weights!")
                    if "refinements" not in st.session_state:
                        st.session_state.refinements = []
                    st.session_state.refinements.append(refinement)
                else:
                    st.warning("Could not process your weight updates. Please try rephrasing.")

        if st.button("✅ All Details Provided, Calculate Final Estimate!"):
            with st.spinner("Finalizing..."):
                # Use the QA manager for final calculation with tool support
                final_response, final_tool_calls = qa_manager.generate_final_calculation(
                    st.session_state.get('conversation_chat', conversation_chat),
                    available_tools
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
            class FinalBreakdownModel(BaseModel):
                breakdown: list[dict]

            parsed_data, errors = parse_or_repair_json(raw_text, FinalBreakdownModel)

            if parsed_data is None:
                raise ValueError(f"Could not parse final breakdown JSON: {errors}")

            data = parsed_data.model_dump()

            # Validate macro sanity (calories ≈ 4p+4c+9f)
            is_valid, validation_errors = validate_macro_sanity(data)
            if not is_valid:
                st.warning("⚠️ Nutritional calculations may be inaccurate:")
                for error in validation_errors:
                    st.caption(f"• {error}")
                st.caption("The AI may have miscalculated. Consider verifying with nutrition labels.")

            breakdown_list = data.get("breakdown", [])
            if not breakdown_list:
                st.warning("The AI was unable to provide a breakdown. Please try again.")

            total_calories, total_protein, total_carbs, total_fat = 0, 0, 0, 0
            display_data = []

            for item in breakdown_list:
                try:
                    calories = int(item.get("calories"))
                except (ValueError, TypeError):
                    calories = 0

                try:
                    protein = int(item.get("protein_grams"))
                except (ValueError, TypeError):
                    protein = 0

                try:
                    carbs = int(item.get("carbs_grams"))
                except (ValueError, TypeError):
                    carbs = 0

                try:
                    fat = int(item.get("fat_grams"))
                except (ValueError, TypeError):
                    fat = 0

                total_calories += calories
                total_protein += protein
                total_carbs += carbs
                total_fat += fat
                display_data.append(
                    {"Item": item.get("item", "N/A"), "Calories": f"{calories} kcal", "Protein": f"{protein}g",
                     "Carbs": f"{carbs}g", "Fat": f"{fat}g"})

            st.table(display_data)
            st.subheader("Calculated Totals", divider='rainbow')
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Calories", f"{total_calories} kcal")
            col2.metric("Total Protein", f"{total_protein}g")
            col3.metric("Total Carbs", f"{total_carbs}g")
            col4.metric("Total Fat", f"{total_fat}g")

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