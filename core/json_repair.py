import json
import re
from typing import TypeVar, Type, Tuple
from pydantic import BaseModel, ValidationError

T = TypeVar('T', bound=BaseModel)


def parse_or_repair_json(text: str, model: Type[T]) -> Tuple[T | None, list[str]]:
    """
    Attempts to parse JSON from text and validate against a pydantic model.
    Returns (parsed_model, errors) where parsed_model is None if parsing failed.
    """
    errors = []

    # Try direct parsing first
    try:
        data = json.loads(text)
        parsed_model = model(**data)
        return parsed_model, []
    except json.JSONDecodeError as e:
        errors.append(f"JSON decode error: {e}")
    except ValidationError as e:
        errors.append(f"Validation error: {e}")
    except Exception as e:
        errors.append(f"Unexpected error: {e}")

    # Try to repair common issues
    cleaned_text = _attempt_json_repair(text)
    if cleaned_text != text:
        try:
            data = json.loads(cleaned_text)
            parsed_model = model(**data)
            return parsed_model, []
        except json.JSONDecodeError as e:
            errors.append(f"JSON decode error after repair: {e}")
        except ValidationError as e:
            errors.append(f"Validation error after repair: {e}")
        except Exception as e:
            errors.append(f"Unexpected error after repair: {e}")

    return None, errors


def _attempt_json_repair(text: str) -> str:
    """
    Attempts to repair common JSON formatting issues in LLM output.
    """
    # Remove markdown code blocks
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*$', '', text)

    # Remove leading/trailing text, find first { to last }
    first_brace = text.find('{')
    last_brace = text.rfind('}')

    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text = text[first_brace:last_brace + 1]

    # Remove trailing commas before closing braces/brackets
    text = re.sub(r',(\s*[}\]])', r'\1', text)

    # Remove any comments (// or /* */)
    text = re.sub(r'//.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)

    return text.strip()


def llm_retry_with_system_hardener(chat, last_prompt: str, errors: list[str]) -> str:
    """
    Sends a system hardener message to emphasize JSON-only output and retries once.
    """
    error_summary = "; ".join(errors[:3])  # Limit to first 3 errors

    hardener_prompt = f"""
CRITICAL: Your previous response had JSON parsing errors: {error_summary}

You MUST respond with ONLY a single, valid JSON object. No other text.
- No markdown code blocks
- No trailing commas
- No comments
- No prose before or after the JSON

Please retry the request and provide ONLY the JSON response.
"""

    response = chat.send_message(hardener_prompt + "\n\n" + last_prompt)
    return response.text