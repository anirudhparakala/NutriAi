import google.generativeai as genai
from .schemas import RefinementUpdate, VisionEstimate
from .json_repair import parse_or_repair_json, llm_retry_with_system_hardener
from .tool_runner import run_with_tools


def load_qa_prompt() -> str:
    """Load the QA manager prompt template."""
    try:
        with open("config/llm_prompts/qa_manager_prompt.txt", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        # Fallback prompt if file not found
        return """
You are Nutri-AI's refinement module. Based on the conversation context and user's clarifications, update the meal estimate.

IMPORTANT: If the user mentions branded/restaurant/fast-food items, first call `perform_web_search` with a precise query like '<brand> <item> nutrition facts' and use those results.

CRITICAL: Respond with ONLY a single JSON object. No prose. No markdown. No trailing commas.

Required JSON Output Format:
{
  "updated_ingredients": [
    {
      "name": "ingredient_name",
      "amount": weight_in_grams,
      "unit": "g",
      "source": "user",
      "notes": "updated_details"
    }
  ],
  "updated_assumptions": [
    {
      "key": "assumption_key",
      "value": "assumption_value",
      "confidence": 0.9
    }
  ]
}
"""


def refine(context: str, user_input: str, chat_session: genai.ChatSession, available_tools: dict = None) -> tuple[RefinementUpdate | None, int]:
    """
    Processes user input to refine the nutritional estimate.

    Args:
        context: Context from the previous conversation
        user_input: User's clarification or correction
        chat_session: Active chat session with conversation history
        available_tools: Dict mapping tool names to functions for search, etc.

    Returns:
        Tuple of (RefinementUpdate object or None if parsing failed, tool_calls_count)
    """
    try:
        # Load prompt template
        base_prompt = load_qa_prompt()

        # Construct refinement prompt with context
        full_prompt = f"""
{base_prompt}

Context from conversation: {context}
User input: {user_input}

Based on this information, provide the JSON response with any updates to ingredients or assumptions.
"""

        # Send message to chat session with tool support
        if available_tools:
            response_text, tool_calls_count = run_with_tools(chat_session, available_tools, full_prompt)
        else:
            response = chat_session.send_message(full_prompt)
            response_text = response.text
            tool_calls_count = 0

        # Parse and validate response
        parsed_update, errors = parse_or_repair_json(response_text, RefinementUpdate)

        if parsed_update is None and errors:
            # Attempt retry with hardener
            print(f"Initial parsing failed: {errors}")
            if available_tools:
                hardener_prompt = """
CRITICAL: Your previous response had JSON parsing errors.
You MUST respond with ONLY a single, valid JSON object. No other text.
- No markdown code blocks
- No trailing commas
- No comments
- No prose before or after the JSON
Please retry the request and provide ONLY the JSON response.
"""
                retry_response, retry_tool_calls = run_with_tools(chat_session, available_tools, hardener_prompt)
                tool_calls_count += retry_tool_calls
            else:
                retry_response = llm_retry_with_system_hardener(chat_session, full_prompt, errors)
            parsed_update, retry_errors = parse_or_repair_json(retry_response, RefinementUpdate)

            if parsed_update is None:
                print(f"Retry parsing also failed: {retry_errors}")
                print(f"Raw response: {retry_response}")
                return None, tool_calls_count

        # Store raw model response for debugging
        if parsed_update:
            try:
                import json
                parsed_update.raw_model = json.loads(response_text)
            except:
                parsed_update.raw_model = {"raw_text": response_text}

        return parsed_update, tool_calls_count

    except Exception as e:
        print(f"Error in QA refinement: {e}")
        return None, 0


def generate_final_calculation(chat_session: genai.ChatSession, available_tools: dict = None) -> tuple[str, int]:
    """
    Generates the final nutritional breakdown in the legacy JSON format
    for backward compatibility with the existing UI.

    Args:
        chat_session: Active chat session with full conversation history
        available_tools: Dict mapping tool names to functions for search, etc.

    Returns:
        Tuple of (JSON string with breakdown format expected by UI, tool_calls_count)
    """
    final_prompt = """
Based on our entire conversation, your final and most important task is to act as an expert nutritionist and CALCULATE a detailed nutritional breakdown.

- **Synthesize All Information:** Use every piece of information from our conversation (ingredients, preparation methods, quantities, and any data from web searches) to inform your calculations.
- **Use Your Internal Knowledge:** For ingredients like "one large chicken breast," or if a web search failed, you must use your internal knowledge to estimate the nutritional values.
- **Output Format:** You MUST ONLY respond with a single, valid JSON object. Do not include any other text. The object must have a "breakdown" key containing a list of items. Each item must have keys for "item", "calories", "protein_grams", "carbs_grams", and "fat_grams".
- **Handle Uncertainty:** If, after using all your knowledge and tools, you are still truly unable to calculate a specific value, default that value to 0. But you must try to calculate first.

Example: `{"breakdown": [{"item": "Pan-fried Chicken Kebabs (1 large breast)","calories": 550,"protein_grams": 75,"carbs_grams": 5,"fat_grams": 25}]}`

Now, provide the final JSON response for the meal we discussed.
"""

    try:
        if available_tools:
            response_text, tool_calls_count = run_with_tools(chat_session, available_tools, final_prompt)
            return response_text, tool_calls_count
        else:
            response = chat_session.send_message(final_prompt)
            return response.text, 0
    except Exception as e:
        print(f"Error generating final calculation: {e}")
        return '{"breakdown": []}', 0