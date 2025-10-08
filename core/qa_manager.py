import google.generativeai as genai
import json
from .schemas import RefinementUpdate, VisionEstimate, Explanation
from .json_repair import parse_or_repair_json, llm_retry_with_system_hardener
from .tool_runner import run_with_tools
from .nutrition_lookup import build_deterministic_breakdown
from .validators import run_all_validations
from .portion_resolver import resolve_portions


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


def refine(context: str, user_input: str | dict, chat_session: genai.ChatSession, available_tools: dict = None) -> tuple[RefinementUpdate | None, int]:
    """
    Processes user input to refine the nutritional estimate.

    Args:
        context: Context from the previous conversation
        user_input: Either a dict[question_id, answer] for structured answers,
                   or a string for free-form clarifications (backward compat)
        chat_session: Active chat session with conversation history
        available_tools: Dict mapping tool names to functions for search, etc.

    Returns:
        Tuple of (RefinementUpdate object or None if parsing failed, tool_calls_count)
    """
    if isinstance(user_input, dict):
        print(f"DEBUG: refine() called with structured answers: {user_input}")
        answers_json = json.dumps(user_input, indent=2)
        input_text = f"User provided these answers to critical questions:\n{answers_json}"
    else:
        # Free-form text is only allowed when there are no critical questions
        # Otherwise, reject to enforce dict[id, answer] format
        print(f"WARNING: Received free-form user_input (deprecated path): '{user_input}'")
        print(f"WARNING: Prefer dict[id, answer] format for reliability")
        input_text = f"User input: {user_input}"

    try:
        # Load prompt template
        base_prompt = load_qa_prompt()

        # Construct refinement prompt with context
        full_prompt = f"""
{base_prompt}

Context from conversation: {context}
{input_text}

Based on this information, provide the JSON response with any updates to ingredients or assumptions.
"""

        print(f"DEBUG: Sending refinement prompt to LLM")

        # Send message to chat session with tool support
        # Always route through run_with_tools for consistent error handling
        response_text, tool_calls_count = run_with_tools(chat_session, available_tools or {}, full_prompt)

        print(f"DEBUG: LLM response received, length: {len(response_text)} chars")
        print(f"DEBUG: LLM response text: {response_text[:500]}...")

        # Parse and validate response
        print(f"DEBUG: Attempting to parse refinement JSON")
        parsed_update, errors = parse_or_repair_json(response_text, RefinementUpdate)

        if parsed_update is None and errors:
            # Attempt retry with hardener
            print(f"ERROR: Initial parsing failed: {errors}")
            print(f"DEBUG: Attempting retry with hardener")
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
                print(f"ERROR: Retry parsing also failed: {retry_errors}")
                print(f"DEBUG: Retry response was: {retry_response[:500]}...")
                print(f"Raw response: {retry_response}")
                return None, tool_calls_count

        # Store raw model response for debugging
        if parsed_update:
            try:
                parsed_update.raw_model = json.loads(response_text)
            except:
                parsed_update.raw_model = {"raw_text": response_text}

            print(f"DEBUG: Successfully parsed refinement")
            print(f"DEBUG: Updated ingredients: {len(parsed_update.updated_ingredients)}")

            # Enforce amount/source contract before returning
            for ing in parsed_update.updated_ingredients:
                # Validation is already done by Pydantic validator in schemas.py
                # Just log for debugging
                if ing.amount is not None:
                    print(f"DEBUG:   - {ing.name}: {ing.amount}g (source: {ing.source})")
                else:
                    portion_info = f" [{ing.portion_label}]" if ing.portion_label else ""
                    print(f"DEBUG:   - {ing.name}: portion_label{portion_info} (source: {ing.source})")

            print(f"DEBUG: Updated assumptions: {len(parsed_update.updated_assumptions)}")
        else:
            print(f"ERROR: parsed_update is None, refinement failed")

        return parsed_update, tool_calls_count

    except Exception as e:
        print(f"Error in QA refinement: {e}")
        return None, 0


def generate_final_calculation(chat_session: genai.ChatSession, available_tools: dict = None, vision_estimate: VisionEstimate = None, refinements: list = None) -> tuple[str, int]:
    """
    Generates the final nutritional breakdown using deterministic USDA pipeline.
    LLM is only used for explanations, not macro calculations.

    Args:
        chat_session: Active chat session with full conversation history
        available_tools: Dict mapping tool names to functions for search, etc.
        vision_estimate: Original vision estimate with ingredients
        refinements: List of refinement updates from user interactions

    Returns:
        Tuple of (JSON string with breakdown format expected by UI, tool_calls_count)
    """
    tool_calls_count = 0

    try:
        # Step 1: Collect all ingredients from vision estimate and refinements
        ingredients = []

        if vision_estimate and hasattr(vision_estimate, 'ingredients'):
            for ingredient in vision_estimate.ingredients:
                if hasattr(ingredient, 'name') and hasattr(ingredient, 'amount'):
                    ingredients.append({
                        "name": ingredient.name,
                        "amount": ingredient.amount
                    })
                elif isinstance(ingredient, dict):
                    ingredients.append({
                        "name": ingredient.get('name', ''),
                        "amount": ingredient.get('amount', 0)
                    })

        # Apply refinements - Trust the LLM's output completely
        # The LLM is given full context (original ingredients + questions + answers)
        # and is smart enough to return the correct updated ingredient list
        if refinements:
            print(f"DEBUG: Applying {len(refinements)} refinements")
            for refinement in refinements:
                if hasattr(refinement, 'updated_ingredients') and refinement.updated_ingredients:
                    updated_count = len(refinement.updated_ingredients)
                    original_count = len(ingredients)

                    print(f"DEBUG: Refinement has {updated_count} ingredients, original had {original_count}")

                    # If LLM returned ALL ingredients, it's a complete replacement (handles corrections)
                    # If LLM returned fewer, it's a partial update (handles additions/specific changes)
                    if updated_count >= original_count:
                        print(f"DEBUG: Complete replacement - LLM provided full updated list")
                        ingredients = []
                        for updated_ingredient in refinement.updated_ingredients:
                            name = updated_ingredient.name if hasattr(updated_ingredient, 'name') else updated_ingredient.get('name', '')
                            amount = updated_ingredient.amount if hasattr(updated_ingredient, 'amount') else updated_ingredient.get('amount', 0)
                            ingredients.append({"name": name, "amount": amount})
                            print(f"DEBUG:   - {name}: {amount}g")
                    else:
                        print(f"DEBUG: Partial update - merging specific changes")
                        for updated_ingredient in refinement.updated_ingredients:
                            name = updated_ingredient.name if hasattr(updated_ingredient, 'name') else updated_ingredient.get('name', '')
                            amount = updated_ingredient.amount if hasattr(updated_ingredient, 'amount') else updated_ingredient.get('amount', 0)

                            # Find and replace by fuzzy matching (handles variants like "cola" -> "cola (diet)")
                            name_lower = name.lower()
                            found = False
                            for i, existing in enumerate(ingredients):
                                existing_name = existing.get('name', '').lower()

                                # Exact match
                                if existing_name == name_lower:
                                    ingredients[i] = {"name": name, "amount": amount}
                                    print(f"DEBUG:   - Replaced (exact): {name}: {amount}g")
                                    found = True
                                    break

                                # Variant match: check if one is a variant of the other
                                # E.g., "cola" matches "cola (diet)", "milk" matches "milk (2%)"
                                existing_base = existing_name.split('(')[0].strip()
                                new_base = name_lower.split('(')[0].strip()

                                if existing_base == new_base:
                                    # Same base ingredient, replace with the more specific variant
                                    ingredients[i] = {"name": name, "amount": amount}
                                    print(f"DEBUG:   - Replaced (variant): '{existing.get('name')}' with '{name}': {amount}g")
                                    found = True
                                    break

                            if not found:
                                # New ingredient, append it
                                ingredients.append({"name": name, "amount": amount})
                                print(f"DEBUG:   - Added new: {name}: {amount}g")

        # Step 2: Canonicalize names (normalize aliases, portion labels)
        from .normalize import canonicalize_name, canonicalize_portion_label
        print(f"DEBUG: Canonicalizing {len(ingredients)} ingredient names")
        for ingredient in ingredients:
            original_name = ingredient.get("name", "")
            original_portion = ingredient.get("portion_label", "")

            # Canonicalize name (context-aware)
            brand = ingredient.get("notes", "") or ""
            canonical_name = canonicalize_name(original_name, brand=brand)

            # Canonicalize portion label
            canonical_portion = canonicalize_portion_label(original_portion)

            if canonical_name != original_name:
                print(f"DEBUG: Canonicalized name: '{original_name}' → '{canonical_name}'")
                ingredient["name"] = canonical_name

            if canonical_portion and canonical_portion != original_portion:
                print(f"DEBUG: Canonicalized portion: '{original_portion}' → '{canonical_portion}'")
                ingredient["portion_label"] = canonical_portion

        # Step 3: Resolve portions deterministically (prevents LLM from inventing grams)
        print(f"DEBUG: Resolving portions for {len(ingredients)} ingredients")
        ingredients, portion_metrics = resolve_portions(ingredients)
        print(f"DEBUG: Portions resolved with metrics: {portion_metrics}")

        # Step 4: Use deterministic pipeline to compute macros
        search_fn = available_tools.get('perform_web_search') if available_tools else None
        deterministic_result, nutrition_tool_calls = build_deterministic_breakdown(ingredients, search_fn)

        tool_calls_count += nutrition_tool_calls  # Accurate tool call count

        # Step 3: Run validations
        scaled_items = deterministic_result.get('items', [])
        print(f"DEBUG: Running validations on {len(scaled_items)} scaled items")
        validations = run_all_validations(scaled_items)
        print(f"DEBUG: Validation results: {validations}")

        # Step 4: Convert to legacy UI format
        breakdown_items = []
        print(f"DEBUG: Converting {len(scaled_items)} items to legacy UI format")
        for item in scaled_items:
            breakdown_item = {
                "item": item["name"],
                "calories": int(round(item["kcal"])),
                "protein_grams": int(round(item["protein_g"])),
                "carbs_grams": int(round(item["carb_g"])),
                "fat_grams": int(round(item["fat_g"]))
            }
            breakdown_items.append(breakdown_item)
            print(f"DEBUG: Converted item: {breakdown_item}")

        # Step 5: Build complete final JSON with USDA attribution (no confidence score for users)
        attribution = deterministic_result.get('attribution', [])
        print(f"DEBUG: Adding {len(attribution)} attribution entries to final JSON")

        final_json_data = {
            "breakdown": breakdown_items,
            "attribution": attribution,
            "validations": {
                "four_four_nine": validations.get("four_four_nine", {}),
                "portion_warnings": validations.get("portion_warnings", [])
                # Note: confidence score excluded from user output
            }
        }

        # Step 6: Ask LLM for explanation only (not calculations)
        explanation_prompt = f"""
Based on our conversation, I've calculated the nutritional breakdown using USDA data. Here are the results:

{json.dumps(breakdown_items, indent=2)}

Please provide a brief explanation of the assumptions made and suggest one follow-up question if there are any uncertainties.
Do NOT recalculate or modify any nutritional values - they are final.

Respond with ONLY a JSON object:
{{
  "explanation": "brief explanation of assumptions",
  "follow_up_question": "optional question for user"
}}
"""

        try:
            # Always route through run_with_tools for consistent error handling
            explanation_response, explanation_tools = run_with_tools(chat_session, available_tools or {}, explanation_prompt)
            tool_calls_count += explanation_tools

            # Parse the explanation with proper schema validation
            parsed_explanation, _ = parse_or_repair_json(explanation_response, Explanation)
            if parsed_explanation:
                # Add LLM explanation to our deterministic data
                final_json_data["explanation"] = parsed_explanation.explanation
                final_json_data["follow_up_question"] = parsed_explanation.follow_up_question

            return json.dumps(final_json_data), tool_calls_count

        except Exception as e:
            print(f"Error getting LLM explanation: {e}")
            # Add empty explanation on error
            final_json_data["explanation"] = ""
            final_json_data["follow_up_question"] = ""
            return json.dumps(final_json_data), tool_calls_count

    except Exception as e:
        print(f"Error in deterministic final calculation: {e}")
        return '{"breakdown": []}', tool_calls_count