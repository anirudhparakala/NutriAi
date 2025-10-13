import google.generativeai as genai
import json
from typing import List, Dict, Any
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


# Decomposition logic removed - LLM handles all ingredient decomposition via QA prompts


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
        try:
            response_text, tool_calls_count = run_with_tools(chat_session, available_tools or {}, full_prompt)
        except ValueError as e:
            # LLM returned empty response - retry once
            print(f"ERROR: LLM returned empty response on first attempt: {e}")
            print(f"DEBUG: Retrying QA refinement with simpler prompt")
            retry_prompt = f"""
User answers: {input_text}

Return JSON with updated ingredients list. Each ingredient needs: name, amount (null if unknown), unit ("g"), source, portion_label, notes.

{{
  "updated_ingredients": [...],
  "updated_assumptions": [...]
}}
"""
            try:
                response_text, tool_calls_count = run_with_tools(chat_session, available_tools or {}, retry_prompt)
            except ValueError as retry_error:
                print(f"ERROR: Retry also failed: {retry_error}")
                return None, 0

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


def should_trigger_stage2(ingredients: List[Dict[str, Any]]) -> bool:
    """
    Determine if Stage-2 quantity verification should trigger.

    Skip if all ingredients satisfy:
    - Known brand + size label (small/medium/large), OR
    - Single-serve beverage with portion_label

    Otherwise trigger if:
    - 2+ ingredients, OR
    - Any ingredient missing portion_label

    Args:
        ingredients: List of ingredient dicts

    Returns:
        True if Stage-2 should trigger
    """
    # Known brands for fast-food/restaurant meals
    KNOWN_BRANDS = {'mcdonalds', 'mcdonald', 'kfc', 'subway', 'starbucks', 'burger king',
                    'dominos', 'pizza hut', 'taco bell', 'chipotle', 'wendys', 'arbys'}
    SIZE_LABELS = {'small', 'medium', 'large', 'regular', 'grande', 'venti'}
    SINGLE_SERVE_BEVERAGE_PORTIONS = {'can', 'bottle', 'small', 'medium', 'large', 'regular'}

    # Check if all ingredients are branded+sized (skip Stage-2 for McDonald's meals)
    all_branded_sized = True
    for ing in ingredients:
        notes = (ing.get('notes') or '').lower()
        portion = (ing.get('portion_label') or '').lower()
        name = (ing.get('name') or '').lower()

        # Check if this ingredient is branded+sized
        has_brand = any(brand in notes or brand in name for brand in KNOWN_BRANDS)
        has_size = any(size in portion for size in SIZE_LABELS)

        # Check if single-serve beverage
        is_beverage = any(bev in name for bev in ['cola', 'soda', 'coffee', 'tea', 'juice', 'water', 'drink', 'shake', 'smoothie'])
        has_single_serve = any(portion_type in portion for portion_type in SINGLE_SERVE_BEVERAGE_PORTIONS)

        is_branded_sized = (has_brand and has_size) or (is_beverage and has_single_serve and portion)

        if not is_branded_sized:
            all_branded_sized = False
            break

    if all_branded_sized and len(ingredients) > 0:
        print(f"DEBUG: Skipping Stage-2 (all ingredients are branded+sized)")
        return False

    # Normal trigger conditions
    if len(ingredients) >= 2:
        return True

    # Check for missing portion_labels
    for ing in ingredients:
        if not ing.get('portion_label'):
            return True

    return False


def generate_stage2_question(ingredients: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate Stage-2 quantity confirmation question.

    Args:
        ingredients: List of ingredient dicts with portion_label estimates

    Returns:
        Question dict with id, text, options, follow_up_prompt, and checksum
    """
    import hashlib

    # Build summary of current estimates
    portions_summary = []
    for ing in ingredients:
        name = ing.get('name', 'unknown')
        portion = ing.get('portion_label', 'unknown amount')
        portions_summary.append(f"{portion} {name}")

    question_text = f"I estimated: {', '.join(portions_summary)}. Does this look right?"

    # Create checksum from ingredient names to detect stale answers
    ingredient_signature = json.dumps([ing.get('name', '') for ing in ingredients], sort_keys=True)
    checksum = hashlib.md5(ingredient_signature.encode()).hexdigest()[:8]

    return {
        "id": "qty_confirm",
        "text": question_text,
        "options": ["Looks right", "I want to adjust"],
        "default": "Looks right",
        "impact_score": 0.3,
        "follow_up_prompt": "Use 'name amount unit', e.g., 'rice 2 cups; dal 0.5 cup; ghee 1 tbsp'",
        "checksum": checksum,
        "ingredients_snapshot": ingredients  # For validation
    }


def apply_stage2_adjustments(ingredients: List[Dict[str, Any]], stage2_answer: dict, chat_session: genai.ChatSession, available_tools: dict) -> dict:
    """
    Apply Stage-2 quantity adjustments to ingredients.

    Args:
        ingredients: List of ingredient dicts
        stage2_answer: Dict with user's response and checksum (e.g., {"qty_confirm": "rice 2 cups", "checksum": "abc123"})
        chat_session: Active chat session
        available_tools: Dict of available tools

    Returns:
        Dict with {"ok": bool, "ingredients": list, "applied_count": int, "message": str, "match_map": dict}
    """
    import re
    import hashlib

    answer_value = stage2_answer.get("qty_confirm", "").strip()
    answer_checksum = stage2_answer.get("checksum", "")

    # Validate checksum to prevent stale answers
    ingredient_signature = json.dumps([ing.get('name', '') for ing in ingredients], sort_keys=True)
    current_checksum = hashlib.md5(ingredient_signature.encode()).hexdigest()[:8]

    if answer_checksum and answer_checksum != current_checksum:
        print(f"ERROR: Stage-2 checksum mismatch (stale answer)")
        print(f"METRICS: {json.dumps({'event': 'qa_quantity_stale', 'ok': False})}")
        return {
            "ok": False,
            "ingredients": ingredients,
            "applied_count": 0,
            "message": "The ingredient list changed. Please review the portions again.",
            "match_map": {}
        }

    # If user said "Looks right", no changes needed
    if answer_value.lower() in ["looks right", "yes", "correct", "good"]:
        print(f"DEBUG: Stage-2 accepted as-is")
        print(f"METRICS: {json.dumps({'event': 'qa_quantity_skip', 'reason': 'user_accepted'})}")
        return {
            "ok": True,
            "ingredients": ingredients,
            "applied_count": 0,
            "message": "Portions confirmed",
            "match_map": {}
        }

    # First try regex parsing for common patterns
    adjustments = []
    match_map = {}
    parse_method = "regex"

    # Support both formats:
    # Pattern 1: "milk 22 oz" - <name> <number> <unit>
    # Pattern 2: "22 oz milk" - <number> <unit> <name>

    # Try pattern 2 first (more common user input: "22 oz milk")
    pattern2 = r'(\d+(?:\.\d+)?)\s*([a-zA-Z]+)\s+([a-zA-Z\s]+?)(?:[;,]|$)'
    matches_p2 = re.findall(pattern2, answer_value)

    if matches_p2:
        print(f"DEBUG: Stage-2 regex (amount-first) found {len(matches_p2)} matches")
        for match in matches_p2:
            amount, unit, name_part = match
            name_part = name_part.strip()
            new_portion_label = f"{amount} {unit}"
            adjustments.append({"name": name_part, "new_portion_label": new_portion_label})
    else:
        # Try pattern 1: "milk 22 oz"
        pattern1 = r'([a-zA-Z\s]+?)\s+(\d+(?:\.\d+)?)\s*([a-zA-Z]+)'
        matches_p1 = re.findall(pattern1, answer_value)
        if matches_p1:
            print(f"DEBUG: Stage-2 regex (name-first) found {len(matches_p1)} matches")
            for match in matches_p1:
                name_part, amount, unit = match
                name_part = name_part.strip()
                new_portion_label = f"{amount} {unit}"
                adjustments.append({"name": name_part, "new_portion_label": new_portion_label})
        else:
            # Fallback to LLM parsing
            parse_method = "llm"
            adjustment_prompt = f"""
User wants to adjust portion quantities. Original estimates:
{json.dumps([{'name': ing.get('name'), 'portion_label': ing.get('portion_label')} for ing in ingredients], indent=2)}

User's adjustments: "{answer_value}"

Parse the user's adjustments and return updated portion_label values. Return JSON only:

{{
  "adjustments": [
    {{"name": "ingredient_name", "new_portion_label": "2 cups"}}
  ]
}}

CRITICAL: Only include items the user mentioned. Accept grams/mL if user specified them, otherwise use human units (cups, tbsp, pieces, slices).
"""

            try:
                response_text, tool_calls = run_with_tools(chat_session, available_tools, adjustment_prompt)
                response_data = json.loads(response_text)
                adjustments = response_data.get('adjustments', [])
                print(f"DEBUG: Stage-2 LLM parse found {len(adjustments)} adjustments")
            except Exception as e:
                print(f"ERROR: Failed to parse Stage-2 adjustments with LLM: {e}")
                print(f"METRICS: {json.dumps({'event': 'qa_quantity_parse', 'method': 'llm', 'ok': False, 'items': 0})}")
                return {
                    "ok": False,
                    "ingredients": ingredients,
                    "applied_count": 0,
                    "message": "I couldn't understand the edits. Try 'rice 2 cups; dal 0.5 cup'",
                    "match_map": {}
                }

    # Apply adjustments with tightened name matching
    from .normalize import normalize_for_matching
    changed_count = 0

    for adj in adjustments:
        adj_name = adj.get('name', '')
        adj_name_normalized = normalize_for_matching(adj_name)
        new_portion = adj.get('new_portion_label', '')

        matched = False
        for ing in ingredients:
            ing_name = ing.get('name', '')
            ing_name_normalized = normalize_for_matching(ing_name)

            # Tightened matching: require head-token equality or significant overlap
            if _names_match(adj_name_normalized, ing_name_normalized):
                old_portion = ing.get('portion_label', '')
                ing['portion_label'] = new_portion
                ing['source'] = 'user'  # Mark as user-provided
                changed_count += 1
                match_map[adj_name] = ing_name
                print(f"DEBUG: Stage-2 adjusted '{ing_name}': '{old_portion}' → '{new_portion}'")
                matched = True
                break

        if not matched:
            print(f"WARNING: Stage-2 could not match adjustment '{adj_name}' to any ingredient")

    parse_ok = changed_count > 0
    print(f"METRICS: {json.dumps({'event': 'qa_quantity_parse', 'method': parse_method, 'ok': parse_ok, 'items': len(adjustments)})}")
    print(f"METRICS: {json.dumps({'event': 'qa_quantity_changed', 'changed': changed_count, 'total': len(ingredients)})}")
    print(f"METRICS: {json.dumps({'event': 'qa_quantity_match_map', 'map': match_map})}")

    if changed_count == 0:
        return {
            "ok": False,
            "ingredients": ingredients,
            "applied_count": 0,
            "message": "I couldn't match your changes to the ingredients. Try using the exact ingredient names.",
            "match_map": match_map
        }

    return {
        "ok": True,
        "ingredients": ingredients,
        "applied_count": changed_count,
        "message": f"Updated {changed_count} ingredient(s)",
        "match_map": match_map
    }


def _names_match(name1_normalized: str, name2_normalized: str) -> bool:
    """
    Tightened name matching using head-token equality.

    Args:
        name1_normalized: First normalized name (tokens)
        name2_normalized: Second normalized name (tokens)

    Returns:
        True if names match with sufficient confidence
    """
    tokens1 = set(name1_normalized.split())
    tokens2 = set(name2_normalized.split())

    if not tokens1 or not tokens2:
        return False

    # Get head tokens (first meaningful token)
    head1 = name1_normalized.split()[0]
    head2 = name2_normalized.split()[0]

    # Require head token equality
    if head1 == head2:
        return True

    # Or require significant token overlap (at least 1 common token and one must be the head)
    overlap = tokens1 & tokens2
    if overlap and (head1 in overlap or head2 in overlap):
        return True

    return False


def generate_final_calculation(chat_session: genai.ChatSession, available_tools: dict = None, vision_estimate: VisionEstimate = None, refinements: list = None, stage2_answer: dict = None) -> tuple[str, int]:
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

        # Collect assumptions from refinements
        assumptions = []

        # Apply refinements using ID-based merge logic
        if refinements:
            print(f"DEBUG: Applying {len(refinements)} refinements")

            # Build ingredient map by ID for efficient lookups
            ingredient_map = {}
            for ing in ingredients:
                ing_id = ing.get('id')
                if ing_id:
                    ingredient_map[ing_id] = ing

            for refinement in refinements:
                # Collect assumptions
                if hasattr(refinement, 'updated_assumptions') and refinement.updated_assumptions:
                    for assumption in refinement.updated_assumptions:
                        if hasattr(assumption, 'model_dump'):
                            assumptions.append(assumption.model_dump())
                        elif isinstance(assumption, dict):
                            assumptions.append(assumption)

                if hasattr(refinement, 'updated_ingredients') and refinement.updated_ingredients:
                    # Convert to dicts
                    updated_dicts = []
                    for updated_ingredient in refinement.updated_ingredients:
                        if hasattr(updated_ingredient, 'model_dump'):
                            ingredient_dict = updated_ingredient.model_dump()
                        elif isinstance(updated_ingredient, dict):
                            ingredient_dict = updated_ingredient.copy()
                        else:
                            ingredient_dict = {
                                "name": updated_ingredient.name if hasattr(updated_ingredient, 'name') else '',
                                "amount": updated_ingredient.amount if hasattr(updated_ingredient, 'amount') else None
                            }
                        updated_dicts.append(ingredient_dict)

                    # ID-based merge: Remove parents, add/update children
                    parents_to_remove = set()
                    items_to_add = []

                    for ing_dict in updated_dicts:
                        parent_id = ing_dict.get('parent_id')
                        ing_id = ing_dict.get('id')

                        if parent_id:
                            # Mark parent for removal
                            parents_to_remove.add(parent_id)
                            print(f"DEBUG: Item '{ing_dict.get('name')}' replaces parent_id={parent_id}")

                        if ing_id and ing_id in ingredient_map:
                            # Update existing item
                            ingredient_map[ing_id].update(ing_dict)
                            print(f"DEBUG: Updated existing → id={ing_id}, name='{ing_dict.get('name')}'")
                        else:
                            # New item
                            items_to_add.append(ing_dict)
                            print(f"DEBUG: New item → name='{ing_dict.get('name')}'")

                    # Remove parents
                    for parent_id in parents_to_remove:
                        if parent_id in ingredient_map:
                            removed = ingredient_map.pop(parent_id)
                            print(f"DEBUG: Removed parent → id={parent_id}, name='{removed.get('name')}'")

                    # Rebuild ingredient list
                    ingredients = list(ingredient_map.values()) + items_to_add

                    # Rebuild map for next iteration
                    ingredient_map = {ing.get('id'): ing for ing in ingredients if ing.get('id')}

                    print(f"DEBUG: After refinement: {len(ingredients)} ingredients, removed {len(parents_to_remove)} parents")

        # Step 1.4: Canonical dedup safety net (prevents double-counting if LLM didn't set parent_id)
        from .normalize import canonicalize_name
        COMPOSITE_TERMS = {'smoothie', 'shake', 'bowl', 'salad', 'soup', 'biryani', 'wrap', 'pizza', 'plate', 'mix'}

        canonical_groups = {}
        composite_items = []
        dropped_composites = 0
        deduped = 0

        for ing in ingredients:
            name = ing.get('name', '')
            canonical = canonicalize_name(name)
            name_lower = name.lower()

            # Check if this is a composite term
            is_composite = any(term in name_lower for term in COMPOSITE_TERMS)

            if canonical not in canonical_groups:
                canonical_groups[canonical] = []
            canonical_groups[canonical].append((ing, is_composite))

        # For each canonical group, keep only specific ingredients (not composites)
        filtered_ingredients = []
        for canonical, items in canonical_groups.items():
            if len(items) == 1:
                # No conflict, keep it
                filtered_ingredients.append(items[0][0])
            else:
                # Multiple items with same canonical name - keep specific over composite
                has_composite = any(is_comp for _, is_comp in items)
                has_specific = any(not is_comp for _, is_comp in items)

                if has_composite and has_specific:
                    # Keep only specific items, drop composites
                    for ing, is_comp in items:
                        if not is_comp:
                            filtered_ingredients.append(ing)
                        else:
                            dropped_composites += 1
                            print(f"DEBUG: Dedup safety net dropped composite '{ing.get('name')}'")
                else:
                    # All composite or all specific - keep all
                    for ing, _ in items:
                        filtered_ingredients.append(ing)
                    if len(items) > 1:
                        deduped += len(items) - 1

        ingredients = filtered_ingredients
        print(f"METRICS: {json.dumps({'event': 'merge_result', 'count': len(ingredients), 'dropped_composites': dropped_composites, 'deduped': deduped})}")

        # Guardrail: Check if any parent_id still exists in the list
        ing_ids = {ing.get('id') for ing in ingredients if ing.get('id')}
        for ing in ingredients:
            parent_id = ing.get('parent_id')
            if parent_id and parent_id in ing_ids:
                print(f"WARN: Ingredient '{ing.get('name')}' has parent_id='{parent_id}' but parent still exists - this shouldn't happen")

        # Step 1.5: Check if Stage-2 quantity verification should trigger
        if should_trigger_stage2(ingredients):
            # Check if we've already received a Stage-2 answer
            if stage2_answer is None:
                # Generate Stage-2 question and return early
                stage2_question = generate_stage2_question(ingredients)
                print(f"DEBUG: Stage-2 triggered with question: {stage2_question['text']}")
                print(f"METRICS: {json.dumps({'event': 'qa_quantity_shown', 'count': len(ingredients)})}")

                # Remove non-serializable snapshot before JSON encoding
                stage2_q_clean = {k: v for k, v in stage2_question.items() if k != 'ingredients_snapshot'}

                # Return special response indicating Stage-2 question pending
                return json.dumps({
                    "stage2_question": stage2_q_clean
                }), tool_calls_count
            else:
                # Apply Stage-2 adjustments
                print(f"DEBUG: Applying Stage-2 adjustments: {stage2_answer}")
                result = apply_stage2_adjustments(ingredients, stage2_answer, chat_session, available_tools)
                tool_calls_count += 1  # Count the LLM call for parsing adjustments

                # Check if adjustment succeeded
                if not result["ok"]:
                    # Return error, ask user to try again
                    print(f"ERROR: Stage-2 adjustment failed: {result['message']}")
                    # Generate new question without ingredients_snapshot (causes serialization issues)
                    stage2_q = generate_stage2_question(ingredients)
                    # Remove non-serializable snapshot before JSON encoding
                    stage2_q_clean = {k: v for k, v in stage2_q.items() if k != 'ingredients_snapshot'}
                    return json.dumps({
                        "stage2_error": result["message"],
                        "stage2_question": stage2_q_clean
                    }), tool_calls_count

                # Success - use updated ingredients
                ingredients = result["ingredients"]
                print(f"DEBUG: Stage-2 applied {result['applied_count']} changes: {result['match_map']}")
        else:
            print(f"DEBUG: Skipping Stage-2 (single ingredient with portion_label)")

        # Step 2: Canonicalize names (normalize aliases, portion labels) and categorize
        from .normalize import canonicalize_name, canonicalize_portion_label, categorize_food
        print(f"DEBUG: Canonicalizing {len(ingredients)} ingredient names")
        for ingredient in ingredients:
            original_name = ingredient.get("name", "")
            original_portion = ingredient.get("portion_label", "")

            # Canonicalize name (context-aware)
            brand = ingredient.get("notes", "") or ""
            canonical_name = canonicalize_name(original_name, brand=brand)

            # Canonicalize portion label
            canonical_portion = canonicalize_portion_label(original_portion)

            # Categorize for portion resolution
            category = categorize_food(canonical_name if canonical_name else original_name)
            if category:
                ingredient["category"] = category
                print(f"DEBUG: Categorized '{ingredient.get('name')}' as '{category}'")

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