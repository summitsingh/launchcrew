"""Bounded single-image JSON input for the photo check.

Accepts exactly one ``data:image/{png|jpeg};base64,<payload>`` URI.
Bounds: at most 1 MiB decoded bytes and at most 8 million decoded
pixels. Every bound is enforced BEFORE the allocation it guards: the
encoded length is checked before base64 decoding, and the original
header dimensions (EXIF-oriented safely) are checked before any pixel
buffer is allocated. Actual PNG/JPEG structure is validated with
Pillow (never the filename or magic alone); malformed, truncated,
empty, animated, and decompression-bomb input is rejected without
changing the approved raw bytes.

No disk writes, no persistence, no logging of bytes. No global Pillow
state is mutated here; truncated images fail on the default strict
loader path and map to a malformed-input rejection.
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

# Base64 expands 3 raw bytes to 4 chars; anything longer cannot decode
# within the raw bound, so reject it before allocating the decoder.
MAX_B64_CHARS = (MAX_DECODED_BYTES + 2) // 3 * 4

_EXIF_ORIENTATION_TAG = 274
_EXIF_SWAP_ORIENTATIONS = frozenset({5, 6, 7, 8})

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


def _oriented_header_dims(img) -> tuple[int, int]:
    """EXIF-oriented dimensions from header metadata only; no pixels decoded."""
    width, height = img.size
    try:
        orientation = img.getexif().get(_EXIF_ORIENTATION_TAG)
    except Exception:
        orientation = None
    if orientation in _EXIF_SWAP_ORIENTATIONS:
        return height, width
    return width, height


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
    if len(payload) > MAX_B64_CHARS:
        raise PhotoInputError("image exceeds 1 MiB decoded bound")
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
    return {"raw": raw, "mime": mime, "width": width, "height": height,
            "sha256": hashlib.sha256(raw).hexdigest()}


def _validated_dimensions(raw: bytes, mime: str) -> tuple[int, int]:
    """Validate structure with Pillow and return EXIF-oriented dimensions.

    Header dimensions and the pixel bound are enforced before ``load()``
    allocates the pixel buffer. ``exif_transpose`` runs only on images
    already known to fit the bound, so its output cannot exceed it.
    """
    from PIL import Image

    expected = "PNG" if mime == "image/png" else "JPEG"
    try:
        with Image.open(io.BytesIO(raw)) as img:
            if (img.format or "").upper() != expected:
                raise PhotoInputError("bytes are not a decodable PNG/JPEG image")
            if getattr(img, "is_animated", False) or getattr(img, "n_frames", 1) != 1:
                raise PhotoInputError("animated images are not accepted")
            width, height = _oriented_header_dims(img)
            if width <= 0 or height <= 0:
                raise PhotoInputError("empty image")
            if width * height > MAX_PIXELS:
                raise PhotoInputError("image exceeds 8 million pixel bound")
            try:
                img.load()
            except Image.DecompressionBombError:
                raise PhotoInputError("image exceeds 8 million pixel bound")
            except Exception:
                raise PhotoInputError("malformed or truncated image")
            from PIL import ImageOps
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
    if width * height > MAX_PIXELS:
        raise PhotoInputError("image exceeds 8 million pixel bound")
    return width, height
