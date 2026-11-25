"""Read and encode a local image for either video provider."""

from __future__ import annotations

import base64
from pathlib import Path


IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class ImageInputError(Exception):
    """An invalid local image input."""


def encode_image(image_path: str | Path) -> tuple[str, str]:
    """Return (base64 data, MIME type) for a supported local image."""
    path = Path(image_path).expanduser()
    mime_type = IMAGE_MIME_TYPES.get(path.suffix.lower())
    if mime_type is None:
        raise ImageInputError("Choose an image in PNG, JPEG or WebP format.")
    if not path.is_file():
        raise ImageInputError(f"Image does not exist or is not accessible: {path}")

    try:
        image_bytes = path.read_bytes()
    except OSError as exc:
        raise ImageInputError(f"Could not read the image: {exc}") from exc
    if not image_bytes:
        raise ImageInputError("The selected image is an empty file.")

    return base64.b64encode(image_bytes).decode("ascii"), mime_type
