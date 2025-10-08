"""
Frozen determinism configuration for all Gemini model calls.

This ensures consistent, reproducible results across all LLM interactions.
"""
import os

# Model version tracking
MODEL_NAME = "gemini-2.5-flash-lite"
PROMPT_VERSION = os.popen("git rev-parse --short HEAD 2>nul").read().strip() or "dev"

# Deterministic generation config
# Temperature near-zero for minimal randomness
# Single candidate for consistency
# Low top_p for focused sampling
GENERATION_CONFIG = {
    "response_mime_type": "application/json",
    "temperature": 0.1,
    "candidate_count": 1,
    "top_p": 0.1
}


def get_session_metadata() -> dict:
    """
    Get metadata to log with each session for reproducibility.

    Returns:
        Dict with model name, prompt version, and config
    """
    return {
        "model_name": MODEL_NAME,
        "prompt_version": PROMPT_VERSION,
        "generation_config": GENERATION_CONFIG
    }
