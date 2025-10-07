import json
from typing import Any, Callable, Dict, List, Tuple, Union
import google.generativeai as genai


# Safety cap to prevent infinite tool-call loops
MAX_ROUNDS = 8


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
            final_text = "{}"
            if parts:
                for part in parts:
                    if hasattr(part, 'json') and part.json:
                        final_text = json.dumps(part.json)
                        break
                    if hasattr(part, 'text') and part.text and part.text.strip():
                        final_text = part.text
                        break
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
            # No more function calls, extract final text content
            final_text = ""

            # Try to get text from response
            try:
                final_text = resp.text
            except Exception:
                # resp.text failed (finish_reason=1, no valid Part, etc.)
                pass

            # Graceful fallback for non-text replies
            if not final_text or final_text.strip() == "":
                # Prefer JSON parts over text (boosts structured returns)
                for part in parts:
                    if hasattr(part, 'json') and part.json:
                        final_text = json.dumps(part.json)
                        break
                    if hasattr(part, 'text') and part.text and part.text.strip():
                        final_text = part.text
                        break

                # If still empty, provide JSON-parseable fallback (not prose)
                # This prevents downstream JSON parsing errors
                if not final_text or final_text.strip() == "":
                    final_text = "{}"
                    print("WARNING: LLM returned empty response, using empty JSON object fallback")

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