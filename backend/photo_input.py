"""Bounded single-image JSON input for the photo check.

Accepts exactly one ``data:image/{png|jpeg};base64,<payload>`` URI.
Bounds: at most 1 MiB decoded bytes and at most 8 million decoded
pixels. Validates actual PNG/JPEG structure with Pillow (never the
filename or magic alone), rejects malformed, truncated, animated,
empty, and decompression-bomb input, and derives EXIF-oriented
dimensions. The approved raw bytes are never altered here.

No disk writes, no persistence, no logging of bytes.
"""
import base64
import binascii
import hashlib
import io
from typing import TypedDict

MAX_DECODED_BYTES = 1024 * 1024
MAX_PIXELS = 8_000_000

PNG_PREFIX = "data:image/png;base64,"
JPEG_PREFIX = "data:image/jpeg;base64,"

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


class PhotoInputError(ValueError):
    """Rejected photo input; the message names the cause without echoing bytes."""

    def __init__(self, reason: str):
        super().__init__("Photo input rejected: " + reason)
        self.reason = reason


class ParsedPhoto(TypedDict):
    raw: bytes
    mime: str
    width: int
    height: int
    sha256: str


def parse_photo_data_uri(value: object) -> ParsedPhoto:
    """Parse and structurally validate one photo data URI."""
    if not isinstance(value, str) or not value:
        raise PhotoInputError("empty image")
    if value.startswith(PNG_PREFIX):
        mime, payload = "image/png", value[len(PNG_PREFIX):]
    elif value.startswith(JPEG_PREFIX):
        mime, payload = "image/jpeg", value[len(JPEG_PREFIX):]
    else:
        raise PhotoInputError("unsupported image encoding; PNG or JPEG data URI required")
    if not payload:
        raise PhotoInputError("empty image")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise PhotoInputError("malformed base64 image")
    if not raw:
        raise PhotoInputError("empty image")
    if len(raw) > MAX_DECODED_BYTES:
        raise PhotoInputError("image exceeds 1 MiB decoded bound")
    if mime == "image/png" and not raw.startswith(_PNG_MAGIC):
        raise PhotoInputError("bytes are not a PNG image")
    if mime == "image/jpeg" and not raw.startswith(_JPEG_MAGIC):
        raise PhotoInputError("bytes are not a JPEG image")
    width, height = _validated_dimensions(raw, mime)
    if width * height > MAX_PIXELS:
        raise PhotoInputError("image exceeds 8 million pixel bound")
    return {"raw": raw, "mime": mime, "width": width, "height": height,
            "sha256": hashlib.sha256(raw).hexdigest()}


def _validated_dimensions(raw: bytes, mime: str) -> tuple[int, int]:
    """Decode structure with Pillow and return EXIF-oriented dimensions."""
    from PIL import Image, ImageFile, ImageOps

    try:
        with Image.open(io.BytesIO(raw)) as img:
            if (img.format or "").upper() != ("PNG" if mime == "image/png" else "JPEG"):
                raise PhotoInputError("bytes are not a decodable PNG/JPEG image")
            if getattr(img, "is_animated", False) or getattr(img, "n_frames", 1) != 1:
                raise PhotoInputError("animated images are not accepted")
            ImageFile.LOAD_TRUNCATED_IMAGES = False
            img.load()
            oriented = ImageOps.exif_transpose(img)
            width, height = oriented.size
    except PhotoInputError:
        raise
    except Image.DecompressionBombError:
        raise PhotoInputError("image exceeds 8 million pixel bound")
    except Exception:
        raise PhotoInputError("malformed or truncated image")
    if width <= 0 or height <= 0:
        raise PhotoInputError("empty image")
    return width, height
