"""
Privacy-aware logging utilities.

When LOG_LEVEL=prod, suppresses raw user text and candidate descriptions,
but still logs FDC IDs, scores, and metrics for observability.
"""
import os
import json
from typing import Any, Dict, Optional


LOG_LEVEL = os.getenv("LOG_LEVEL", "dev")  # "dev" or "prod"


def is_production() -> bool:
    """Check if running in production mode."""
    return LOG_LEVEL.lower() == "prod"


def sanitize_user_text(text: str, max_length: int = 50) -> str:
    """
    Sanitize user text for production logging.

    In prod mode: redact or truncate.
    In dev mode: return as-is.

    Args:
        text: User-provided text
        max_length: Max length to keep in prod

    Returns:
        Sanitized text
    """
    if not is_production():
        return text

    # In production, truncate and hash
    if len(text) > max_length:
        import hashlib
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:8]
        return f"[REDACTED-{text_hash}]"

    return text[:max_length] + "..."


def log_with_privacy(message: str, user_data: Optional[Dict[str, Any]] = None) -> None:
    """
    Log message with privacy controls.

    Args:
        message: Log message
        user_data: Optional dict with user-provided data to sanitize
    """
    if user_data and is_production():
        # Sanitize sensitive fields
        sanitized = {}
        for key, value in user_data.items():
            if key in ["text", "query", "description", "dish", "ingredient_name"]:
                sanitized[key] = "[REDACTED]"
            elif key in ["fdc_id", "score", "candidates", "selected_fdc_id"]:
                sanitized[key] = value  # Keep metadata
            else:
                sanitized[key] = value

        print(f"{message}: {json.dumps(sanitized)}")
    else:
        if user_data:
            print(f"{message}: {json.dumps(user_data)}")
        else:
            print(message)


def sanitize_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize metrics for production logging.

    Keeps: event, fdc_id, score, counts, rates
    Redacts: query, description, ingredient names

    Args:
        metrics: Metrics dict

    Returns:
        Sanitized metrics
    """
    if not is_production():
        return metrics

    sanitized = {}
    for key, value in metrics.items():
        if key in ["query", "description", "ingredient", "item", "dish"]:
            sanitized[key] = "[REDACTED]"
        else:
            sanitized[key] = value

    return sanitized
