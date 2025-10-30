"""
Image I/O helper: Converts image bytes to Gemini-compatible format with MIME type validation.
"""
from PIL import Image
import io


SUPPORTED_MIME_TYPES = {"image/jpeg", "image/png"}

FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}


def guess_mime_from_bytes(img_bytes: bytes) -> str:
    """Detect MIME type from image bytes using Pillow."""
    try:
        with Image.open(io.BytesIO(img_bytes)) as im:
            return FORMAT_TO_MIME.get(im.format, "application/octet-stream")
    except Exception:
        return "application/octet-stream"


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
    # Detect image format using Pillow
    mime_type = guess_mime_from_bytes(image_bytes)

    # Validate supported types
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise ValueError(
            f"Unsupported image format: {mime_type}. "
            f"Supported formats: {', '.join(SUPPORTED_MIME_TYPES)}"
        )

    print(f"DEBUG: Image validated - MIME type: {mime_type}")

    # Convert to PIL Image (Gemini SDK accepts PIL Images directly)
    image = Image.open(io.BytesIO(image_bytes))
    return image
