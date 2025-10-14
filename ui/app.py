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
from config.model_config import MODEL_NAME, GENERATION_CONFIG, get_session_metadata
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

# When using tools, we cannot use response_mime_type (Gemini API constraint)
# Remove it from generation config for tool-enabled model
tool_compatible_config = {k: v for k, v in GENERATION_CONFIG.items() if k != "response_mime_type"}

model = genai.GenerativeModel(
    model_name=MODEL_NAME,
    tools=[my_search_tool],
    generation_config=tool_compatible_config
)

# Log model configuration at startup
print(f"INFO: Model initialized with config: {get_session_metadata()}")


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
                try:
                    # Use the new vision estimator with tool support
                    estimate, vision_tool_calls = vision_estimator.estimate(st.session_state.uploaded_image_data, model, available_tools)

                    if estimate is None:
                        st.error("Failed to analyze the image. Please try again.", icon="❌")
                        return
                except ValueError as e:
                    # Handle empty response error from tool_runner
                    error_msg = str(e)
                    if "empty response" in error_msg.lower():
                        st.error(
                            "⚠️ The AI returned an empty response. This may indicate:\n\n"
                            "- API quota exceeded\n"
                            "- Model temporary failure\n"
                            "- Network issues\n\n"
                            "**Please try again in a moment.**",
                            icon="🔄"
                        )
                        if st.button("🔄 Try Again"):
                            st.rerun()
                        return
                    else:
                        raise
                except Exception as e:
                    st.error(f"Unexpected error during analysis: {e}", icon="❌")
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

        # Display assumption chips for silent defaults (UX guardrail)
        if st.session_state.vision_estimate and st.session_state.vision_estimate.critical_questions:
            # Collect all defaults that user hasn't explicitly changed
            defaults_display = []
            for question in st.session_state.vision_estimate.critical_questions:
                if question.default:
                    # Extract ingredient name from question ID (e.g., "fries_size" -> "Fries")
                    ingredient_hint = question.id.split('_')[0].capitalize()
                    defaults_display.append(f"{ingredient_hint} · **{question.default}**")

            if defaults_display:
                st.markdown("**🔹 Current assumptions:**")
                st.caption(" • ".join(defaults_display) + " _(Change below if needed)_")
                st.markdown("---")

        # Display critical questions with structured answer collection
        question_answers = {}
        if st.session_state.vision_estimate and st.session_state.vision_estimate.critical_questions:
            with st.expander("✎ Change assumptions (optional)", expanded=False):
                for i, question in enumerate(st.session_state.vision_estimate.critical_questions, 1):
                    st.markdown(f"**{i}. {question.text}**")

                    # Collect structured answers using question ID
                    if question.options:
                        # Use selectbox for options-based questions
                        default_index = 0
                        if question.default and question.default in question.options:
                            default_index = question.options.index(question.default)

                        answer = st.selectbox(
                            f"Select answer for: {question.text}",
                            options=question.options,
                            index=default_index,
                            key=f"q_{question.id}",
                            label_visibility="collapsed"
                        )
                        question_answers[question.id] = answer

                        # Show follow-up prompt if available
                        if question.follow_up_prompt and answer.lower() in ["specify", "other", "custom"]:
                            follow_up = st.text_input(
                                question.follow_up_prompt,
                                key=f"followup_{question.id}",
                                placeholder=question.follow_up_prompt
                            )
                            if follow_up and follow_up.strip():
                                question_answers[question.id] = follow_up
                    else:
                        # Free-form text input for open questions
                        answer = st.text_input(
                            f"Answer: {question.text}",
                            key=f"q_{question.id}",
                            placeholder=question.default if question.default else "",
                            label_visibility="collapsed"
                        )
                        if answer and answer.strip():
                            question_answers[question.id] = answer
                        elif question.default:
                            question_answers[question.id] = question.default

        # Store question answers in session state for use in Calculate button
        st.session_state.question_answers = question_answers

        # Create or reuse chat session for conversation persistence
        if "conversation_chat" not in st.session_state:
            st.session_state.conversation_chat = model.start_chat()
        conversation_chat = st.session_state.conversation_chat

        # Only show additional clarifications if there are no structured questions
        # This enforces dict[id, answer] format and prevents free-form parsing errors
        clarification_input = ""
        if not (st.session_state.vision_estimate and st.session_state.vision_estimate.critical_questions):
            st.markdown("### Additional Details")
            clarification_input = st.text_area(
                "No specific questions generated. Add any details here:",
                placeholder="Example: medium fries, diet cola, etc.",
                key="clarification_input_box",
                help="Provide specific details about sizes, variants, or ingredients",
                height=80
            )

        # Process button for immediate refinement (optional - user can also just click Calculate)
        col1, col2 = st.columns([1, 3])
        with col1:
            # Submit button now uses structured answers + optional clarifications
            has_answers = bool(question_answers and any(v for v in question_answers.values()))
            has_clarifications = bool(clarification_input and clarification_input.strip())

            if st.button("💬 Submit Answers", disabled=not (has_answers or has_clarifications)):
                with st.spinner("Processing your input..."):
                    # Prepare input for QA manager
                    # If we have structured answers, use dict format
                    # Otherwise fall back to free-form text
                    if has_answers:
                        user_input = question_answers.copy()
                        # If there are clarifications, add them as a special key
                        if has_clarifications:
                            user_input["_additional_clarifications"] = clarification_input
                    else:
                        user_input = clarification_input

                    # Process the answer immediately
                    context = st.session_state.vision_estimate.model_dump() if st.session_state.vision_estimate else {}
                    refinement, qa_tool_calls = qa_manager.refine(
                        context=json.dumps(context),
                        user_input=user_input,
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
                                if ingredient.amount is not None:
                                    amount_text = f"{ingredient.amount}g"
                                else:
                                    amount_text = f"portion: {ingredient.portion_label}" if ingredient.portion_label else "portion pending"
                                notes_text = f" ({ingredient.notes})" if ingredient.notes else ""
                                response_text += f"- {ingredient.name}: {amount_text}{notes_text}\n"

                        st.success(response_text)

                        # Store the refinement for final calculation
                        if "refinements" not in st.session_state:
                            st.session_state.refinements = []
                        st.session_state.refinements.append(refinement)

                        # Rerun to refresh (input will be cleared automatically)
                        st.rerun()
                    else:
                        st.warning("I'm having trouble understanding that. Please try providing more details.")

        st.divider()

        # Show refinement status
        refinement_count = len(st.session_state.get('refinements', []))
        if refinement_count > 0:
            st.info(f"✅ {refinement_count} refinement(s) submitted", icon="✅")

        # Calculate button - auto-processes any pending answers
        if st.button("🎯 Calculate Final Estimate", type="primary"):
            # FIRST: Check if there are any pending answers/clarifications that haven't been submitted
            has_pending_answers = bool(question_answers and any(v for v in question_answers.values()))
            has_pending_clarifications = bool(clarification_input and clarification_input.strip())

            if has_pending_answers or has_pending_clarifications:
                with st.spinner("Processing your pending answers..."):
                    # Prepare input same way as Submit button
                    if has_pending_answers:
                        user_input = question_answers.copy()
                        if has_pending_clarifications:
                            user_input["_additional_clarifications"] = clarification_input
                    else:
                        user_input = clarification_input

                    context = st.session_state.vision_estimate.model_dump() if st.session_state.vision_estimate else {}
                    refinement, qa_tool_calls = qa_manager.refine(
                        context=json.dumps(context),
                        user_input=user_input,
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
                # Pass Stage-2 answer if available
                stage2_answer = st.session_state.get('stage2_answer')

                final_response, final_tool_calls = qa_manager.generate_final_calculation(
                    st.session_state.get('conversation_chat', conversation_chat),
                    available_tools,
                    vision_estimate=st.session_state.get('vision_estimate'),
                    refinements=st.session_state.get('refinements', []),
                    stage2_answer=stage2_answer
                )

                # Track tool calls
                st.session_state.tool_calls_count = st.session_state.get("tool_calls_count", 0) + final_tool_calls

                # Check if response is a Stage-2 question
                try:
                    response_data = json.loads(final_response)
                    if "stage2_question" in response_data:
                        # Store Stage-2 question and go to Stage-2 QA mode
                        st.session_state.stage2_question = response_data["stage2_question"]
                        st.session_state.analysis_stage = "stage2_qa"
                        st.rerun()
                        return  # Don't continue to results
                except Exception as e:
                    # Not Stage-2 JSON, continue to normal results
                    pass

                # Normal response - store and show results
                st.session_state.final_analysis = final_response
                st.session_state.analysis_stage = "results"
                st.rerun()

    # Stage-2: Quantity verification
    if st.session_state.analysis_stage == "stage2_qa":
        st.markdown("### 📏 Portion Confirmation")

        # Show error banner if there was a parsing issue
        stage2_error = st.session_state.get('stage2_error')
        if stage2_error:
            st.warning(f"⚠️ {stage2_error}", icon="⚠️")
            # Clear error after showing
            st.session_state.stage2_error = None

        stage2_q = st.session_state.get('stage2_question', {})
        question_text = stage2_q.get('text', 'Confirm portions?')
        options = stage2_q.get('options', ['Looks right', 'I want to adjust'])
        follow_up = stage2_q.get('follow_up_prompt', 'Use "name amount unit", e.g., "rice 2 cups; dal 0.5 cup; ghee 1 tbsp"')
        checksum = stage2_q.get('checksum', '')

        st.markdown(f"**{question_text}**")

        # Radio button for quick response
        selected_option = st.radio(
            "Your response:",
            options,
            key="stage2_radio",
            label_visibility="collapsed"
        )

        # If user wants to adjust, show text area with hint
        adjustment_text = ""
        if selected_option == "I want to adjust":
            st.caption(follow_up)
            adjustment_text = st.text_area(
                "Your adjustments:",
                placeholder="rice 2 cups; dal 0.5 cup",
                key="stage2_adjustment",
                height=80,
                label_visibility="collapsed"
            )

        # Submit button
        if st.button("✅ Confirm Portions", type="primary"):
            # Store the answer with checksum
            if selected_option == "I want to adjust" and adjustment_text:
                st.session_state.stage2_answer = {
                    "qty_confirm": adjustment_text,
                    "checksum": checksum
                }
            else:
                st.session_state.stage2_answer = {
                    "qty_confirm": selected_option,
                    "checksum": checksum
                }

            # Directly trigger final calculation with the Stage-2 answer
            with st.spinner("Calculating final nutrition breakdown..."):
                conversation_chat = st.session_state.get('conversation_chat')
                stage2_answer = st.session_state.stage2_answer

                final_response, final_tool_calls = qa_manager.generate_final_calculation(
                    conversation_chat,
                    available_tools,
                    vision_estimate=st.session_state.get('vision_estimate'),
                    refinements=st.session_state.get('refinements', []),
                    stage2_answer=stage2_answer
                )

                # Track tool calls
                st.session_state.tool_calls_count = st.session_state.get("tool_calls_count", 0) + final_tool_calls

                # Check if there was a Stage-2 error (need to stay on this screen)
                try:
                    response_data = json.loads(final_response)
                    if "stage2_error" in response_data:
                        # Store error and re-show the form
                        st.session_state.stage2_error = response_data["stage2_error"]
                        st.session_state.stage2_question = response_data.get("stage2_question", stage2_q)
                        # Stay on stage2_qa, don't change stage
                        st.rerun()
                        return

                    # Check if this is a Stage-2 question (shouldn't happen here, but be safe)
                    if "stage2_question" in response_data:
                        st.session_state.stage2_question = response_data["stage2_question"]
                        # Stay on stage2_qa
                        st.rerun()
                        return

                except Exception as e:
                    # Log parse error for debugging
                    print(f"DEBUG: Could not parse response as JSON: {e}")
                    pass

                # Success - store response and go to results
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
                explanation: Optional[str] = None
                follow_up_question: Optional[str] = None

            parsed_data, errors = parse_or_repair_json(raw_text, FinalBreakdownModel)

            if parsed_data is None:
                raise ValueError(f"Could not parse final breakdown JSON: {errors}")

            data = parsed_data.model_dump()

            breakdown_list = data.get("breakdown", [])
            attribution_list = data.get("attribution", [])
            validations = data.get("validations") or {}  # Handle None case
            explanation = data.get("explanation", "")
            follow_up_question = data.get("follow_up_question", "")

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

            # Show LLM explanation if available
            if explanation and explanation.strip():
                with st.expander("💡 AI Explanation", expanded=False):
                    st.markdown(explanation)
                    if follow_up_question and follow_up_question.strip():
                        st.info(f"**Suggestion:** {follow_up_question}", icon="💭")

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

            # Log successful session to database with model metadata
            if st.session_state.vision_estimate and not st.session_state.get("session_logged", False):
                try:
                    # Add model metadata to session log
                    metadata = get_session_metadata()
                    print(f"INFO: Logging session with metadata: {metadata}")

                    session_id = db.log_session(
                        estimate=st.session_state.vision_estimate,
                        refinements=st.session_state.get("refinements", []),
                        final_json=raw_text,
                        tool_calls_count=st.session_state.get("tool_calls_count", 0),
                        metadata=metadata  # Pass model name, prompt version, config
                    )
                    st.session_state.session_logged = True
                    st.caption(f"📊 Session logged (ID: {session_id}, model: {metadata['model_name']}, version: {metadata['prompt_version']})")
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