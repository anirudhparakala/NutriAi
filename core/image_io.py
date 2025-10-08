"""
Image I/O helper: Converts image bytes to Gemini-compatible format with MIME type validation.
"""
import imghdr
from PIL import Image
import io


SUPPORTED_MIME_TYPES = {"image/jpeg", "image/png"}


def get_image_part(image_bytes: bytes):
    """
    Convert image bytes to Gemini-compatible PIL Image with MIME validation.

    Args:
        image_bytes: Raw image data

    Returns:
        PIL.Image object ready for Gemini

    Raises:
        ValueError: If image format is not supported
    """
    # Detect image format
    image_type = imghdr.what(None, h=image_bytes)
    mime_map = {
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'webp': 'image/webp',
        'bmp': 'image/bmp'
    }
    mime_type = mime_map.get(image_type, 'image/jpeg')

    # Validate supported types
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise ValueError(
            f"Unsupported image format: {mime_type}. "
            f"Supported formats: {', '.join(SUPPORTED_MIME_TYPES)}"
        )

    print(f"DEBUG: Image validated - MIME type: {mime_type}, format: {image_type}")

    # Convert to PIL Image (Gemini SDK accepts PIL Images directly)
    image = Image.open(io.BytesIO(image_bytes))
    return image
