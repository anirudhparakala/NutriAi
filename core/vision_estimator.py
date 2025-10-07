import google.generativeai as genai
from PIL import Image
import io
from .schemas import VisionEstimate
from .json_repair import parse_or_repair_json, llm_retry_with_system_hardener
from .tool_runner import run_with_tools


def load_vision_prompt() -> str:
    """Load the vision estimator prompt template."""
    try:
        with open("config/llm_prompts/vision_estimator_prompt.txt", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        # Fallback prompt if file not found
        return """
You are Nutri-AI, an expert visual nutritional estimator. Analyze the food image and provide a structured estimate.

IMPORTANT: If the dish appears branded/restaurant/fast-food, first call `perform_web_search` with a precise query like '<brand> <item> nutrition facts' and use those results.

CRITICAL: Respond with ONLY a single JSON object. No prose. No markdown. No trailing commas.

Required JSON Output Format:
{
  "dish": "descriptive name of the dish",
  "portion_guess_g": estimated_total_weight_in_grams,
  "ingredients": [
    {
      "name": "ingredient_name",
      "amount": weight_in_grams,
      "unit": "g",
      "source": "vision",
      "notes": "optional_details"
    }
  ],
  "critical_questions": [
    {
      "id": "unique_key",
      "text": "clarification_question",
      "options": ["option1", "option2"],
      "default": "default_option",
      "impact_score": 0.8
    }
  ]
}
"""


def estimate(image_bytes: bytes, model: genai.GenerativeModel, available_tools: dict = None) -> tuple[VisionEstimate | None, int]:
    """
    Analyzes an image and returns a structured nutritional estimate.

    Args:
        image_bytes: Raw image data
        model: Configured Gemini model instance
        available_tools: Dict mapping tool names to functions for search, etc.

    Returns:
        Tuple of (VisionEstimate object or None if parsing failed, tool_calls_count)
    """
    try:
        # Load prompt template
        prompt = load_vision_prompt()

        # Convert bytes to PIL Image
        image = Image.open(io.BytesIO(image_bytes))

        # Create chat session and send message with tool support
        # Always route through run_with_tools for consistent error handling
        chat = model.start_chat()
        response_text, tool_calls_count = run_with_tools(chat, available_tools or {}, [prompt, image])

        # Parse and validate response
        parsed_estimate, errors = parse_or_repair_json(response_text, VisionEstimate)

        if parsed_estimate is None and errors:
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
                retry_response, retry_tool_calls = run_with_tools(chat, available_tools, hardener_prompt)
                tool_calls_count += retry_tool_calls
            else:
                retry_response = llm_retry_with_system_hardener(chat, prompt, errors)
            parsed_estimate, retry_errors = parse_or_repair_json(retry_response, VisionEstimate)

            if parsed_estimate is None:
                print(f"Retry parsing also failed: {retry_errors}")
                print(f"Raw response: {retry_response}")
                return None, tool_calls_count

        # Store raw model response for debugging
        if parsed_estimate:
            try:
                import json
                parsed_estimate.raw_model = json.loads(response_text)
            except:
                parsed_estimate.raw_model = {"raw_text": response_text}

        return parsed_estimate, tool_calls_count

    except Exception as e:
        print(f"Error in vision estimation: {e}")
        return None, 0