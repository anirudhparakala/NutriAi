import json
from typing import Any, Callable, Dict, List, Tuple, Union
import google.generativeai as genai
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.model_config import GENERATION_CONFIG


# Safety cap to prevent infinite tool-call loops
MAX_ROUNDS = 8


def llm_tiebreak(query: str, candidates: list[dict]) -> int:
    """
    Use LLM to pick the best match from 2-3 close USDA candidates.

    Args:
        query: Original search query
        candidates: List of 2-3 candidate dicts with 'description' and 'fdcId'

    Returns:
        Index of best match (0, 1, or 2)
    """
    if not candidates or len(candidates) == 1:
        return 0

    # Build prompt
    candidate_text = "\n".join([
        f"{i}. {food.get('description', 'Unknown')} (FDC: {food.get('fdcId', 'N/A')})"
        for i, food in enumerate(candidates[:3])
    ])

    prompt = f"""Match the query to the best USDA candidate.

Query: "{query}"

Candidates:
{candidate_text}

Which candidate (0, 1, or 2) best matches "{query}"?
Consider:
- Exact match of qualifiers (diet, 2%, lean %, etc.)
- Cooking method if specified
- Avoid non-foods (seasonings, spice mixes)

Respond with ONLY a JSON object: {{"pick": 0}}"""

    try:
        # Create ephemeral model with frozen config
        import google.generativeai as genai
        from config.model_config import MODEL_NAME

        model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            generation_config=GENERATION_CONFIG
        )

        response = model.generate_content(prompt)

        # Extract JSON from response
        result_text = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'json') and part.json:
                result_text = json.dumps(part.json)
                break
            elif hasattr(part, 'text') and part.text:
                result_text = part.text
                break

        # Parse pick value
        result = json.loads(result_text)
        pick = result.get("pick", 0)

        # Validate range
        if 0 <= pick < len(candidates):
            print(f"DEBUG: LLM tiebreaker selected candidate #{pick}: {candidates[pick].get('description')}")
            print(f"METRICS: {json.dumps({'event': 'usda_tiebreak_success', 'query': query, 'pick': pick, 'fdc_id': candidates[pick].get('fdcId')})}")
            return pick
        else:
            print(f"WARNING: LLM tiebreaker returned invalid pick {pick}, using first candidate")
            return 0

    except Exception as e:
        print(f"ERROR: LLM tiebreaker failed: {e}, using first candidate")
        print(f"METRICS: {json.dumps({'event': 'usda_tiebreak_fail', 'query': query, 'error': str(e)})}")
        return 0


def _jsonify_for_function_response(obj: Any) -> Any:
    """
    Ensure tool results are JSON-serializable before sending back to model.
    Handles non-serializable types (set, bytes, custom objects).
    """
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {"content": str(obj)}


def run_with_tools(
    chat: genai.ChatSession,
    available_tools: Dict[str, Callable[..., Any]],
    user_msg: Union[str, List[Any]],
) -> Tuple[str, int]:
    """
    Send user_msg; if the model issues tool calls, execute them and feed results back until content returns.

    Args:
        chat: Gemini chat session
        available_tools: Dict mapping tool names to functions
        user_msg: Message to send (string or list for multimodal)

    Returns:
        Tuple of (final_text_response, tool_calls_count)
    """
    # Validate model config matches frozen determinism settings
    # Skip response_mime_type when tools are used (Gemini API constraint)
    model_config = chat.model._generation_config if hasattr(chat.model, '_generation_config') else None
    if model_config:
        for key, expected_val in GENERATION_CONFIG.items():
            # Skip response_mime_type check when tools are present
            if key == "response_mime_type" and hasattr(chat.model, 'tools') and chat.model.tools:
                continue
            actual_val = getattr(model_config, key, None)
            if actual_val != expected_val:
                print(f"WARNING: Model config mismatch - {key}: expected {expected_val}, got {actual_val}")

    resp = chat.send_message(user_msg)
    tool_calls_count = 0
    rounds = 0

    # Handle tool calls in a loop until we get regular content
    while True:
        rounds += 1
        if rounds > MAX_ROUNDS:
            print("WARNING: Max tool-call rounds reached; returning best-effort content.")
            # Extract best-effort content from current response
            parts = []
            for candidate in resp.candidates:
                if hasattr(candidate, 'content') and candidate.content and candidate.content.parts:
                    parts.extend(candidate.content.parts)

            # JSON-first extraction (same as normal path)
            final_text = ""
            for part in parts:
                if hasattr(part, 'json') and part.json:
                    final_text = json.dumps(part.json)
                    break

            # Fallback to text if no JSON
            if not final_text or final_text.strip() == "":
                for part in parts:
                    if hasattr(part, 'text') and part.text and part.text.strip():
                        final_text = part.text
                        break

            # Final fallback for max rounds - still raise error instead of silent {}
            if not final_text or final_text.strip() == "":
                print(f"METRICS: {json.dumps({'event': 'llm_empty_json_max_rounds', 'rounds': rounds, 'tool_calls': tool_calls_count})}")
                raise ValueError(
                    f"LLM returned empty response after {rounds} rounds. "
                    "This indicates a model failure or infinite tool-call loop. "
                    "Please try again or simplify your request."
                )

            return final_text, tool_calls_count
        # Extract all parts from the response
        parts = []
        for candidate in resp.candidates:
            if hasattr(candidate, 'content') and candidate.content and candidate.content.parts:
                parts.extend(candidate.content.parts)

        # Check for function calls
        function_calls = []
        for part in parts:
            if hasattr(part, 'function_call') and part.function_call:
                function_calls.append(part.function_call)

        if not function_calls:
            # No more function calls, extract final content
            final_text = ""

            # ALWAYS prefer JSON parts over text extraction (JSON-first policy)
            # This ensures structured responses are properly extracted
            for part in parts:
                if hasattr(part, 'json') and part.json:
                    final_text = json.dumps(part.json)
                    break

            # Fallback to text only if no JSON part exists
            if not final_text or final_text.strip() == "":
                try:
                    final_text = resp.text
                except Exception:
                    # resp.text failed (finish_reason=1, no valid Part, etc.)
                    for part in parts:
                        if hasattr(part, 'text') and part.text and part.text.strip():
                            final_text = part.text
                            break

            # If still empty, DON'T silently fall back - this is an error condition
            if not final_text or final_text.strip() == "":
                print(f"METRICS: {json.dumps({'event': 'llm_empty_json', 'rounds': rounds, 'tool_calls': tool_calls_count})}")
                raise ValueError(
                    "LLM returned empty response (no JSON part, no text). "
                    "This indicates a model failure or configuration issue. "
                    "Please try again or check your API quota."
                )

            return final_text, tool_calls_count

        # Execute all function calls and batch responses
        responses = []
        for call in function_calls:
            tool_name = call.name
            tool_args = dict(call.args)  # Convert from Gemini's args format
            tool_calls_count += 1

            # Execute the tool
            if tool_name in available_tools:
                try:
                    tool_result = available_tools[tool_name](**tool_args)
                    print(f"Tool executed: {tool_name}({tool_args}) -> {len(str(tool_result))} chars")
                except Exception as e:
                    tool_result = {"error": f"Tool execution failed: {e}"}
                    print(f"Tool execution error: {tool_name} failed with {e}")
            else:
                tool_result = {"error": f"Unknown tool: {tool_name}"}
                print(f"Unknown tool requested: {tool_name}")

            # Ensure tool result is JSON-serializable
            tool_result = _jsonify_for_function_response(tool_result)

            # Wrap list results in a dict (Gemini FunctionResponse requires dict)
            if isinstance(tool_result, list):
                tool_result = {"results": tool_result}

            # Add to batch of responses
            responses.append(genai.protos.Part(
                function_response=genai.protos.FunctionResponse(
                    name=tool_name,
                    response=tool_result
                )
            ))

        # Send all tool responses back in a single message (reduces round-trips)
        try:
            resp = chat.send_message(responses)
        except Exception as e:
            print(f"Batch tool response error: {e}")
            # Fallback: send as JSON-ish text
            fallback_data = {
                "tool_fallback": {
                    resp_part.function_response.name: resp_part.function_response.response
                    for resp_part in responses
                }
            }
            resp = chat.send_message(json.dumps(fallback_data, default=str))


def run_with_tools_and_parse(chat: genai.ChatSession, available_tools: dict, user_msg: str | list,
                           parse_function=None, max_retries: int = 1):
    """
    Run with tools and optionally parse the result with retry logic.

    Args:
        chat: Gemini chat session
        available_tools: Dict mapping tool names to functions
        user_msg: Message to send
        parse_function: Optional function to parse the result (e.g., parse_or_repair_json)
        max_retries: Number of retries if parsing fails

    Returns:
        Tuple of (parsed_result_or_text, tool_calls_count)
    """
    response_text, tool_calls_count = run_with_tools(chat, available_tools, user_msg)

    if parse_function is None:
        return response_text, tool_calls_count

    # Try parsing with retries
    for attempt in range(max_retries + 1):
        try:
            parsed_result = parse_function(response_text)
            return parsed_result, tool_calls_count
        except Exception as e:
            if attempt < max_retries:
                print(f"Parse attempt {attempt + 1} failed: {e}, retrying...")
                # Send hardener message and retry
                hardener_msg = """
CRITICAL: Your previous response had parsing errors.
You MUST respond with ONLY a single, valid JSON object. No other text.
- No markdown code blocks
- No trailing commas
- No comments
- No prose before or after the JSON
Please retry with proper JSON format.
"""
                response_text, retry_tool_calls = run_with_tools(chat, available_tools, hardener_msg)
                tool_calls_count += retry_tool_calls
            else:
                print(f"Final parse attempt failed: {e}")
                raise

    return response_text, tool_calls_count