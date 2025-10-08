"""
Vision output cache: Ensures idempotency by caching LLM vision outputs by image hash + prompt version.

If the same image is analyzed twice with the same prompt version, reuse the cached result.
"""
import hashlib
import json
from typing import Optional
from pathlib import Path

from .cache_interface import get_cache_backend, build_cache_key, DEFAULT_TTL
from config.model_config import MODEL_NAME


# Cache backend (local or Redis based on env)
_cache_backend = get_cache_backend()

# TTL for vision cache (72 hours)
VISION_TTL = DEFAULT_TTL["vision"]


def _compute_image_hash(image_bytes: bytes) -> str:
    """
    Compute SHA256 hash of image bytes.

    Args:
        image_bytes: Raw image data

    Returns:
        Hex digest of SHA256 hash
    """
    return hashlib.sha256(image_bytes).hexdigest()


def get_cached_vision_output(image_bytes: bytes, prompt_version: str) -> Optional[dict]:
    """
    Retrieve cached vision output if available.

    Args:
        image_bytes: Raw image data
        prompt_version: Prompt version (e.g., git commit hash)

    Returns:
        Cached vision output dict or None if not cached
    """
    image_hash = _compute_image_hash(image_bytes)
    cache_key = build_cache_key(
        prefix="vision",
        model_name=MODEL_NAME,
        prompt_version=prompt_version,
        image_hash=image_hash
    )

    cached_data = _cache_backend.get(cache_key)

    if cached_data:
        print(f"INFO: Vision cache HIT - reusing cached output for image {image_hash[:8]}...")
        print(f"METRICS: {json.dumps({'event': 'vision_cache_hit', 'image_hash': image_hash[:8], 'prompt_version': prompt_version})}")
        return cached_data

    print(f"INFO: Vision cache MISS - will compute and cache for image {image_hash[:8]}...")
    print(f"METRICS: {json.dumps({'event': 'vision_cache_miss', 'image_hash': image_hash[:8], 'prompt_version': prompt_version})}")
    return None


def cache_vision_output(image_bytes: bytes, prompt_version: str, vision_output: dict) -> None:
    """
    Cache vision output for future reuse.

    Args:
        image_bytes: Raw image data
        prompt_version: Prompt version (e.g., git commit hash)
        vision_output: Parsed VisionEstimate as dict
    """
    image_hash = _compute_image_hash(image_bytes)
    cache_key = build_cache_key(
        prefix="vision",
        model_name=MODEL_NAME,
        prompt_version=prompt_version,
        image_hash=image_hash
    )

    try:
        _cache_backend.set(cache_key, vision_output, ttl=VISION_TTL)
        print(f"INFO: Cached vision output for image {image_hash[:8]}... with key {cache_key} (TTL: {VISION_TTL}s)")
    except Exception as e:
        print(f"WARNING: Failed to cache vision output: {e}")


def clear_vision_cache() -> None:
    """
    Clear all cached vision outputs (useful for testing).
    Note: Only works with LocalFileCache backend.
    """
    from .cache_interface import LocalFileCache
    if isinstance(_cache_backend, LocalFileCache):
        import shutil
        cache_dir = _cache_backend.cache_dir
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            print(f"INFO: Vision cache cleared")
    else:
        print(f"WARNING: clear_vision_cache() only works with LocalFileCache backend")
