import json
import google.generativeai as genai


def run_with_tools(chat: genai.ChatSession, available_tools: dict, user_msg: str | list):
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

    # Handle tool calls in a loop until we get regular content
    while True:
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
            final_text = resp.text

            # Graceful fallback for non-text replies
            if not final_text or final_text.strip() == "":
                # Look for any text or JSON parts to return
                for part in parts:
                    if hasattr(part, 'text') and part.text and part.text.strip():
                        final_text = part.text
                        break
                    elif hasattr(part, 'json') and part.json:
                        final_text = json.dumps(part.json)
                        break

                # If still empty, provide a fallback
                if not final_text or final_text.strip() == "":
                    final_text = "Analysis completed successfully."

            return final_text, tool_calls_count

        # Execute all function calls and send responses back
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
                    tool_result = json.dumps({"error": f"Tool execution failed: {e}"})
                    print(f"Tool execution error: {tool_name} failed with {e}")
            else:
                tool_result = json.dumps({"error": f"Unknown tool: {tool_name}"})
                print(f"Unknown tool requested: {tool_name}")

            # Send tool response back to the model with SDK-compatible format
            try:
                # Try the structured format first (newer SDK versions)
                resp = chat.send_message(
                    [genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=tool_name,
                            response={"content": tool_result},
                        )
                    )]
                )
            except Exception as e:
                # Fallback format for SDK compatibility
                try:
                    resp = chat.send_message([{
                        "function_response": {
                            "name": tool_name,
                            "response": {"content": tool_result}
                        }
                    }])
                except Exception as e2:
                    print(f"SDK compatibility error: {e2}")
                    # Simple text fallback
                    resp = chat.send_message(f"Tool {tool_name} returned: {tool_result}")


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