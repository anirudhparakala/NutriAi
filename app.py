import streamlit as st
import google.generativeai as genai
from tavily import TavilyClient
import json
from PIL import Image
import io

# Import new modular components
from core import vision_estimator, qa_manager
from core.schemas import VisionEstimate
from integrations.search_bridge import create_search_tool_function

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
                # Use the new vision estimator
                estimate = vision_estimator.estimate(st.session_state.uploaded_image_data, model)

                if estimate is None:
                    st.error("Failed to analyze the image. Please try again.", icon="❌")
                    return

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

        # Create a fresh chat session for conversation
        conversation_chat = model.start_chat()

        if prompt := st.chat_input("Provide more details..."):
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.spinner("Thinking..."):
                response = conversation_chat.send_message(prompt)

                # Handle tool calls (web search)
                while len(response.candidates[0].content.parts) > 0 and response.candidates[0].content.parts[0].function_call:
                    function_call = response.candidates[0].content.parts[0].function_call
                    tool_name = function_call.name
                    if tool_name in available_tools:
                        tool_args = dict(function_call.args)
                        function_to_call = available_tools[tool_name]
                        tool_response = function_to_call(**tool_args)

                        response = conversation_chat.send_message(
                            [genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(
                                    name=tool_name,
                                    response={"content": tool_response},
                                )
                            )]
                        )
                    else:
                        break

                # Display the response
                with st.chat_message("assistant"):
                    st.markdown(response.text)

                # Store the conversation for final calculation
                st.session_state.conversation_chat = conversation_chat

        if st.button("✅ All Details Provided, Calculate Final Estimate!"):
            with st.spinner("Finalizing..."):
                # Use the QA manager for final calculation
                final_response = qa_manager.generate_final_calculation(
                    st.session_state.get('conversation_chat', conversation_chat)
                )
                st.session_state.final_analysis = final_response
                st.session_state.analysis_stage = "results"
                st.rerun()

    if st.session_state.analysis_stage == "results":
        st.success("### Here is your detailed nutritional estimate:", icon="🎉")
        raw_text = st.session_state.get("final_analysis", "")
        try:
            json_start = raw_text.find('{')
            json_end = raw_text.rfind('}') + 1
            if json_start == -1 or json_end == 0:
                raise ValueError("No valid JSON object found in the AI's response.")
            json_str = raw_text[json_start:json_end]
            data = json.loads(json_str)
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