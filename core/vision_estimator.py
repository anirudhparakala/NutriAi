import google.generativeai as genai
from typing import List
from .schemas import VisionEstimate
from .json_repair import parse_or_repair_json, llm_retry_with_system_hardener
from .tool_runner import run_with_tools
from .image_io import get_image_part
from .vision_cache import get_cached_vision_output, cache_vision_output
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.model_config import MODEL_NAME, GENERATION_CONFIG, PROMPT_VERSION


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


def filter_critical_questions(questions: List, portion_guess_g: float, max_questions: int = 2):
    """
    Filter critical questions to highest-impact ones that meet calorie threshold.

    UX Guardrail: Max 2 questions per meal, only if impact ≥10-15% or ≥120 kcal.

    Args:
        questions: List of question dicts
        portion_guess_g: Estimated total meal weight in grams
        max_questions: Maximum number of questions to show (default 2)

    Returns:
        Filtered list of questions (max 2, sorted by impact)
    """
    if not questions:
        return []

    # Estimate typical calorie impact based on portion size
    # Rough estimate: ~2 kcal/g average for mixed meals
    estimated_total_kcal = portion_guess_g * 2

    # Filter questions by impact threshold
    # Only ask if impact ≥ 10-15% of meal OR ≥ 120 kcal
    min_impact_pct = 0.10  # 10% of meal
    min_impact_kcal = 120

    filtered = []
    for q in questions:
        impact_score = q.get("impact_score", 0.5)  # 0-1 scale
        estimated_impact_kcal = estimated_total_kcal * impact_score

        if estimated_impact_kcal >= min_impact_kcal or impact_score >= min_impact_pct:
            filtered.append(q)

    # Sort by impact score descending and take top N
    filtered.sort(key=lambda q: q.get("impact_score", 0), reverse=True)

    limited = filtered[:max_questions]

    if len(questions) > len(limited):
        print(f"DEBUG: Filtered questions from {len(questions)} to {len(limited)} (max={max_questions}, impact threshold: {min_impact_kcal}kcal or {min_impact_pct*100}%)")

    return limited


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
        # Check cache first for idempotency
        cached_output = get_cached_vision_output(image_bytes, PROMPT_VERSION)
        if cached_output:
            # Reconstruct VisionEstimate from cached dict
            try:
                parsed_estimate = VisionEstimate(**cached_output)
                return parsed_estimate, 0  # 0 tool calls since cached
            except Exception as e:
                print(f"WARNING: Failed to parse cached vision output: {e}, will re-compute")

        # Load prompt template
        prompt = load_vision_prompt()

        # Convert image bytes to PIL Image with MIME validation
        # Raises ValueError if unsupported format (e.g., BMP, GIF)
        image = get_image_part(image_bytes)

        # Create chat session and send message with tool support
        # Gemini SDK accepts PIL Images directly - no upload needed
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

            # Apply UX guardrail: filter questions to max 2, high-impact only
            if parsed_estimate.critical_questions:
                from core.schemas import ClarificationQuestion
                original_count = len(parsed_estimate.critical_questions)

                # Convert to dicts for filtering
                questions_as_dicts = [q.model_dump() if hasattr(q, 'model_dump') else q for q in parsed_estimate.critical_questions]
                filtered_dicts = filter_critical_questions(
                    questions_as_dicts,
                    parsed_estimate.portion_guess_g,
                    max_questions=2
                )

                # Convert back to ClarificationQuestion objects
                parsed_estimate.critical_questions = [
                    ClarificationQuestion(**q) if isinstance(q, dict) else q
                    for q in filtered_dicts
                ]

                if original_count != len(parsed_estimate.critical_questions):
                    print(f"INFO: Question budget applied - reduced from {original_count} to {len(parsed_estimate.critical_questions)} questions")

            # Cache successful parse for idempotency
            cache_vision_output(image_bytes, PROMPT_VERSION, parsed_estimate.model_dump())

        return parsed_estimate, tool_calls_count

    except Exception as e:
        print(f"Error in vision estimation: {e}")
        return None, 0