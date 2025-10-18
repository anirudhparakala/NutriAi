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

        print(f"DEBUG: Sending refinement prompt to LLM (FIX D: tools disabled for Stage-1)")

        # FIX D: Disable tools for Stage-1 to prevent empty response failures
        # Stage-1 should be JSON-only, no web search needed
        # Send message to chat session WITHOUT tool support for reliability
        try:
            response_text, tool_calls_count = run_with_tools(chat_session, {}, full_prompt)  # Empty tools dict
        except ValueError as e:
            # LLM returned empty response - retry once with minimal JSON-only prompt
            print(f"ERROR: LLM returned empty response on first attempt: {e}")
            print(f"METRICS: {json.dumps({'event': 'qa_stage1_empty', 'attempt': 1})}")
            print(f"DEBUG: Retrying QA refinement with simpler JSON-only prompt")
            retry_prompt = f"""
User answers: {input_text}

Return ONLY valid JSON (no tools, no prose). Include updated ingredients list:

{{
  "updated_ingredients": [...],
  "updated_assumptions": [...]
}}
"""
            try:
                response_text, tool_calls_count = run_with_tools(chat_session, {}, retry_prompt)  # Empty tools dict
            except ValueError as retry_error:
                print(f"ERROR: Retry also failed: {retry_error}")
                print(f"METRICS: {json.dumps({'event': 'qa_stage1_empty', 'attempt': 2, 'fatal': True})}")
                # Return minimal "no change" JSON instead of None
                print(f"WARNING: Returning minimal no-change JSON to allow Stage-2 to proceed")
                return RefinementUpdate(updated_ingredients=[], updated_assumptions=[]), 0

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
        "follow_up_prompt": "Use 'name amount unit' to adjust or add components. Examples: 'rice 2 cups; dal 0.5 cup; 1 scoop whey protein; 2 tbsp syrup'",
        "checksum": checksum,
        "ingredients_snapshot": ingredients  # For validation
    }


def _deterministic_parse_stage2(user_text: str) -> List[Dict[str, Any]]:
    """
    Deterministic pre-parser for Stage-2 adjustments using regex and lexicons.

    Returns:
        List of edit dicts with {"action": str, "item_head": str, "value": str, "variant": str (optional)}
    """
    import re

    # Lexicons
    SIZE_LEXICON = r'\b(small|medium|regular|large|x-large|xl|xlarge|kid|side)\b'
    VARIANT_LEXICON = r'\b(diet|zero|zero sugar|light|lite|coke zero|pepsi zero)\b'
    UNIT_LEXICON = r'\b(cup|cups|tbsp|tsp|teaspoon|tablespoon|piece|pieces|slice|slices|scoop|scoops|oz|ounce|ounces|ml|l|liter|liters|g|gram|grams|kg)\b'

    # Synonym normalization
    SYNONYMS = {
        'xl': 'x-large',
        'xlarge': 'x-large',
        'zero sugar': 'diet',
        'coke zero': 'diet',
        'pepsi zero': 'diet',
        'reg': 'regular',
        'teaspoon': 'tsp',
        'tablespoon': 'tbsp',
        'ounce': 'oz',
        'ounces': 'oz',
        'gram': 'g',
        'grams': 'g',
        'liter': 'l',
        'liters': 'l',
    }

    # Split on separators
    separators = r'[;\n,]|\band\b|\b&\b'
    chunks = re.split(separators, user_text)
    chunks = [c.strip() for c in chunks if c.strip()]

    edits = []

    for chunk in chunks:
        chunk_lower = chunk.lower()
        chunk_normalized = ' '.join(chunk_lower.split())  # Collapse spaces

        # Apply synonyms
        for syn, replacement in SYNONYMS.items():
            chunk_normalized = re.sub(r'\b' + re.escape(syn) + r'\b', replacement, chunk_normalized)

        # Check for ordinal markers (#2, second, 2nd)
        ordinal = None
        ordinal_match = re.search(r'#(\d+)|(\d+)(?:st|nd|rd|th)|(first|second|third|fourth|fifth)', chunk_normalized)
        if ordinal_match:
            if ordinal_match.group(1):  # #2
                ordinal = int(ordinal_match.group(1))
            elif ordinal_match.group(2):  # 2nd
                ordinal = int(ordinal_match.group(2))
            elif ordinal_match.group(3):  # second
                ordinal_words = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5}
                ordinal = ordinal_words.get(ordinal_match.group(3), 1)
            # Remove ordinal from chunk
            chunk_normalized = re.sub(r'#\d+|\d+(?:st|nd|rd|th)|\b(?:first|second|third|fourth|fifth)\b', '', chunk_normalized).strip()

        # Pattern 1: <size> <item> (e.g., "large fries")
        match = re.match(r'^(' + SIZE_LEXICON + r')\s+(.+)$', chunk_normalized)
        if match:
            size, item_name = match.groups()
            edits.append({
                "action": "SET_PORTION_LABEL",
                "item_head": item_name.strip(),
                "value": size.strip(),
                "ordinal": ordinal
            })
            continue

        # Pattern 2: <variant> <item> (e.g., "diet cola")
        match = re.match(r'^(' + VARIANT_LEXICON + r')\s+(.+)$', chunk_normalized)
        if match:
            variant, item_name = match.groups()
            edits.append({
                "action": "SET_VARIANT",
                "item_head": item_name.strip(),
                "variant": variant.strip(),
                "ordinal": ordinal
            })
            continue

        # Pattern 3: <qty> <unit> <item> (e.g., "2 cups rice", "12 oz cola")
        match = re.match(r'^(\d+(?:\.\d+)?)\s*(' + UNIT_LEXICON + r')\s+(.+)$', chunk_normalized)
        if match:
            qty, unit, item_name = match.groups()
            edits.append({
                "action": "SET_PORTION_LABEL",
                "item_head": item_name.strip(),
                "value": f"{qty} {unit}".strip(),
                "ordinal": ordinal
            })
            continue

        # Pattern 4: <item> <size> (e.g., "fries large")
        match = re.match(r'^(.+?)\s+(' + SIZE_LEXICON + r')$', chunk_normalized)
        if match:
            item_name, size = match.groups()
            edits.append({
                "action": "SET_PORTION_LABEL",
                "item_head": item_name.strip(),
                "value": size.strip(),
                "ordinal": ordinal
            })
            continue

        # Pattern 5: <item> <variant> (e.g., "cola diet")
        match = re.match(r'^(.+?)\s+(' + VARIANT_LEXICON + r')$', chunk_normalized)
        if match:
            item_name, variant = match.groups()
            edits.append({
                "action": "SET_VARIANT",
                "item_head": item_name.strip(),
                "variant": variant.strip(),
                "ordinal": ordinal
            })
            continue

        # Pattern 6: <item> <qty> <unit> (e.g., "rice 2 cups", "cola 12 oz")
        match = re.match(r'^(.+?)\s+(\d+(?:\.\d+)?)\s*(' + UNIT_LEXICON + r')$', chunk_normalized)
        if match:
            item_name, qty, unit = match.groups()
            edits.append({
                "action": "SET_PORTION_LABEL",
                "item_head": item_name.strip(),
                "value": f"{qty} {unit}".strip(),
                "ordinal": ordinal
            })
            continue

        # Pattern 7: <item>: <value> or <item>=<value>
        match = re.match(r'^(.+?)\s*[:=]\s*(.+)$', chunk_normalized)
        if match:
            item_name, value = match.groups()
            # Check if value is size or variant
            if re.match(SIZE_LEXICON, value):
                edits.append({
                    "action": "SET_PORTION_LABEL",
                    "item_head": item_name.strip(),
                    "value": value.strip(),
                    "ordinal": ordinal
                })
            elif re.match(VARIANT_LEXICON, value):
                edits.append({
                    "action": "SET_VARIANT",
                    "item_head": item_name.strip(),
                    "variant": value.strip(),
                    "ordinal": ordinal
                })
            elif re.match(r'^\d+(?:\.\d+)?\s*' + UNIT_LEXICON + r'$', value):
                edits.append({
                    "action": "SET_PORTION_LABEL",
                    "item_head": item_name.strip(),
                    "value": value.strip(),
                    "ordinal": ordinal
                })
            continue

        # No pattern matched - mark for LLM fallback
        edits.append({
            "action": "UNPARSED",
            "chunk": chunk_normalized
        })

    return edits


def apply_stage2_adjustments(ingredients: List[Dict[str, Any]], stage2_answer: dict, chat_session: genai.ChatSession, available_tools: dict) -> dict:
    """
    Apply Stage-2 quantity adjustments to ingredients using deterministic-first parsing.

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

    # Step 1: Use deterministic pre-parser
    print(f"DEBUG: Applying deterministic Stage-2 parser on: {answer_value}")
    parsed_edits = _deterministic_parse_stage2(answer_value)
    print(f"DEBUG: Deterministic parser returned {len(parsed_edits)} edits")

    # Separate parsable edits from unparsed chunks
    deterministic_edits = [e for e in parsed_edits if e.get("action") != "UNPARSED"]
    unparsed_chunks = [e.get("chunk") for e in parsed_edits if e.get("action") == "UNPARSED"]

    match_map = {}
    parse_method = "regex" if deterministic_edits else "llm"

    # Step 2: Try LLM for unparsed chunks only (if any and if input is long enough)
    llm_edits = []
    if unparsed_chunks and len(answer_value) >= 50:
        print(f"DEBUG: {len(unparsed_chunks)} chunks unparsed, trying LLM for: {unparsed_chunks}")

        # Bulletize chunks to reduce null replies
        bulletized_chunks = "\n".join([f"- {chunk}" for chunk in unparsed_chunks])

        adjustment_prompt = f"""
User wants to adjust portion quantities. Original estimates:
{json.dumps([{'name': ing.get('name'), 'portion_label': ing.get('portion_label')} for ing in ingredients], indent=2)}

User's adjustments (only parse these):
{bulletized_chunks}

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

            # Guard against empty/whitespace responses
            if not response_text or not response_text.strip():
                print(f"ERROR: LLM returned empty response for Stage-2 adjustments")
                print(f"METRICS: {json.dumps({'event': 'qa_quantity_parse', 'method': 'llm', 'ok': False, 'reason': 'empty'})}")
            else:
                response_data = json.loads(response_text)
                llm_edits_raw = response_data.get('adjustments', [])

                # Convert LLM format to our edit format
                for adj in llm_edits_raw:
                    llm_edits.append({
                        "action": "SET_PORTION_LABEL",
                        "item_head": adj.get("name", ""),
                        "value": adj.get("new_portion_label", "")
                    })

                print(f"DEBUG: Stage-2 LLM parse found {len(llm_edits)} additional adjustments")
                parse_method = "hybrid"
        except Exception as e:
            print(f"ERROR: Failed to parse Stage-2 adjustments with LLM: {e}")
            print(f"METRICS: {json.dumps({'event': 'qa_quantity_parse', 'method': 'llm', 'ok': False, 'reason': str(e)})}")
            # Don't fail - continue with deterministic edits only

    # Combine deterministic + LLM edits
    all_edits = deterministic_edits + llm_edits

    if not all_edits:
        print(f"ERROR: No edits parsed from user input")
        print(f"METRICS: {json.dumps({'event': 'qa_quantity_parse', 'method': parse_method, 'ok': False, 'items': 0})}")
        return {
            "ok": False,
            "ingredients": ingredients,
            "applied_count": 0,
            "message": "I couldn't understand the edits. Try formats like: 'large fries, diet cola' or 'rice 2 cups; dal 0.5 cup'",
            "match_map": {}
        }

    # Step 3: Apply edits with safe matching and variant handling
    from .normalize import normalize_for_matching, canonicalize_name
    from .schemas import Ingredient
    import uuid

    changed_count = 0
    added_count = 0
    variant_count = 0
    skipped_edits = []

    # Soft drink keywords for variant detection
    SOFT_DRINK_KEYWORDS = ['cola', 'coke', 'pepsi', 'sprite', 'fanta', 'soda', 'pop', 'lemonade', 'tea', 'coffee']

    for edit in all_edits:
        action = edit.get("action")
        item_head = edit.get("item_head", "")
        value = edit.get("value", "")
        variant = edit.get("variant")
        ordinal = edit.get("ordinal")

        # Use safe matching to find ingredient (with ordinal disambiguation if provided)
        matched_ing, confidence = _safe_match_ingredient(item_head, ingredients, ordinal=ordinal)

        if not matched_ing:
            # No match - skip this edit for now
            skipped_edits.append({"item": item_head, "reason": "no_match"})
            print(f"DEBUG: Stage-2 couldn't match '{item_head}' to any ingredient (skipped)")
            continue

        if action == "SET_PORTION_LABEL":
            # Set portion_label, preserving existing values if needed
            old_portion = matched_ing.get('portion_label', '')
            matched_ing['portion_label'] = value
            matched_ing['source'] = 'user'  # Mark as user-provided
            changed_count += 1
            match_map[item_head] = matched_ing.get('name')
            print(f"DEBUG: Stage-2 adjusted '{matched_ing.get('name')}': portion_label '{old_portion}' → '{value}'")

        elif action == "SET_VARIANT" and variant:
            # Handle variant (diet/zero/light) for soft drinks
            ing_name = matched_ing.get('name', '')
            ing_name_lower = ing_name.lower()

            # Check if this is a soft drink
            is_soft_drink = any(kw in ing_name_lower for kw in SOFT_DRINK_KEYWORDS)

            if is_soft_drink:
                # Update name to include critical modifier in parentheses
                # Remove existing variant parens first
                base_name = ing_name.split('(')[0].strip()
                new_name = f"{base_name} ({variant})"
                matched_ing['name'] = new_name
                matched_ing['source'] = 'user'
                variant_count += 1
                match_map[item_head] = new_name
                print(f"DEBUG: Stage-2 set variant for '{base_name}': → '{new_name}'")
            else:
                # Not a soft drink - skip variant setting
                skipped_edits.append({"item": item_head, "reason": "variant_not_applicable"})
                print(f"DEBUG: Stage-2 skipped variant '{variant}' for '{ing_name}' (not a soft drink)")

    # Step 4: Emit metrics (partial success model)
    total_changes = changed_count + variant_count + added_count
    parse_ok = total_changes > 0

    print(f"METRICS: {json.dumps({'event': 'qa_quantity_parse', 'method': parse_method, 'ok': parse_ok, 'items': len(all_edits)})}")
    print(f"METRICS: {json.dumps({'event': 'qa_quantity_applied_partial', 'applied': total_changes, 'skipped': len(skipped_edits)})}")
    print(f"METRICS: {json.dumps({'event': 'qa_quantity_changed', 'changed': changed_count, 'variant': variant_count, 'added': added_count, 'total': len(ingredients)})}")
    print(f"METRICS: {json.dumps({'event': 'qa_quantity_match_map', 'map': match_map})}")

    # Build user message (partial success feedback)
    if total_changes == 0 and skipped_edits:
        # Everything was skipped
        skipped_items = [e["item"] for e in skipped_edits]
        return {
            "ok": False,
            "ingredients": ingredients,
            "applied_count": 0,
            "message": f"Couldn't match: {', '.join(skipped_items[:3])}. Try exact ingredient names.",
            "match_map": match_map
        }

    # Build success message with applied changes
    action_parts = []
    if changed_count > 0:
        action_parts.append(f"{changed_count} portion(s) updated")
    if variant_count > 0:
        action_parts.append(f"{variant_count} variant(s) set")
    if added_count > 0:
        action_parts.append(f"{added_count} item(s) added")

    message = "Applied: " + ", ".join(action_parts)

    # Add soft warning if some edits were skipped
    if skipped_edits:
        skipped_items = [e["item"] for e in skipped_edits[:2]]  # Show max 2
        message += f". Couldn't parse: {', '.join(skipped_items)}"
        if len(skipped_edits) > 2:
            message += f" (+{len(skipped_edits) - 2} more)"

    return {
        "ok": True,
        "ingredients": ingredients,
        "applied_count": total_changes,
        "message": message,
        "match_map": match_map,
        "skipped_count": len(skipped_edits)
    }


def _extract_head_term(ingredient_name: str) -> str:
    """
    Extract head term from ingredient name using base-before-parens logic.

    Examples:
        "potato fries (large)" -> "fries"
        "cola (diet)" -> "cola"
        "rice" -> "rice"
    """
    # Remove parenthetical content
    base = ingredient_name.split('(')[0].strip()

    # Normalize and get tokens
    tokens = base.lower().split()

    if not tokens:
        return ingredient_name.lower()

    # Return last meaningful token (usually the head noun)
    return tokens[-1] if len(tokens) > 1 else tokens[0]


def _safe_match_ingredient(item_head: str, ingredients: List[Dict[str, Any]], ordinal: int = None) -> tuple[Dict[str, Any] | None, float]:
    """
    Safely match item_head to an ingredient using Jaccard similarity.
    Prevents loose "in" matching that caused dal->daliya bug.

    Args:
        item_head: Normalized item name from user edit
        ingredients: List of ingredient dicts
        ordinal: Optional 1-based index for disambiguation (e.g., "cola #2" -> ordinal=2)

    Returns:
        Tuple of (matched_ingredient, confidence_score) or (None, 0.0)
    """
    from .normalize import normalize_for_matching

    item_head_normalized = normalize_for_matching(item_head)
    item_head_tokens = set(item_head_normalized.split())

    # Check if item_head is very short (≤3 chars) - require exact match
    is_short_token = len(item_head_normalized) <= 3

    candidates = []

    for idx, ing in enumerate(ingredients):
        ing_name = ing.get('name', '')
        ing_head = _extract_head_term(ing_name)
        ing_normalized = normalize_for_matching(ing_head)
        ing_tokens = set(ing_normalized.split())

        # Exact head match
        if item_head_normalized == ing_normalized:
            candidates.append((ing, 1.0, idx))
            continue

        # For short tokens (≤3 chars), skip fuzzy matching
        if is_short_token:
            continue

        # Jaccard similarity
        if item_head_tokens and ing_tokens:
            overlap = item_head_tokens & ing_tokens
            union = item_head_tokens | ing_tokens
            jaccard = len(overlap) / len(union) if union else 0.0

            # For short tokens, require higher threshold
            threshold = 0.7 if len(item_head_normalized) <= 5 else 0.6

            if jaccard >= threshold:
                candidates.append((ing, jaccard, idx))

    if not candidates:
        return (None, 0.0)

    # If ordinal specified, use it to pick the Nth match
    if ordinal is not None and ordinal > 0:
        # Filter candidates by same head term
        head_term = item_head_normalized.split()[0] if item_head_normalized else ""
        same_head_candidates = [
            c for c in candidates
            if normalize_for_matching(_extract_head_term(c[0].get('name', ''))).split()[0] == head_term
        ]
        if len(same_head_candidates) >= ordinal:
            return (same_head_candidates[ordinal - 1][0], same_head_candidates[ordinal - 1][1])

    # Otherwise, return best match if significantly better
    candidates.sort(key=lambda x: x[1], reverse=True)
    best_match, best_score, _ = candidates[0]

    if len(candidates) == 1 or (best_score - candidates[1][1] >= 0.1):
        return (best_match, best_score)

    # Multiple ambiguous matches - return None to avoid wrong update
    return (None, 0.0)


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

        # Calculate portion heuristic rate for quality tracking
        total_portions = sum(portion_metrics.values()) if portion_metrics else 0
        heuristic_rate = (portion_metrics.get('category_heuristic', 0) / total_portions * 100) if total_portions > 0 else 0.0

        final_json_data = {
            "breakdown": breakdown_items,
            "attribution": attribution,
            "validations": {
                "four_four_nine": validations.get("four_four_nine", {}),
                "portion_warnings": validations.get("portion_warnings", [])
                # Note: confidence score excluded from user output
            },
            # Internal tracking data (not shown to users)
            "_internal": {
                "portion_heuristic_rate": heuristic_rate,
                "portion_metrics": portion_metrics
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