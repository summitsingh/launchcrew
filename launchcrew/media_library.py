"""SC4 media library: upload once, format facts, non-destructive derivatives.

One uploaded image or video is hosted by LaunchCrew and reused across
channels without re-upload. Each asset records format facts (dimensions,
aspect ratio, duration) and the Checker validates attached slot media
against slot format rules and channel media capabilities. Channel-ready
crops are generated alongside the original with centered crop boxes and
stored next to it; the original bytes, dimensions, aspect ratio, and
digest are never overwritten or mutated.

All helpers are pure stdlib with no network, model, file, or
environment access. Reasons are plain human-readable strings naming
the rule or mismatch that failed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import math
import struct
from typing import Any

MODULE_VERSION = "media-library/v1"

MEDIA_TYPES = ("image", "video")

DERIVATIVE_KEYS = ("4:5", "1:1", "9:16", "16:9")

CANONICAL_ASPECTS = ("4:5", "1:1", "9:16", "16:9")

FEED_REQUIRED_ASPECT = "4:5"

# Primary channel-ready derivative per channel. Feed surfaces resolve
# to the 4:5 crop, vertical video surfaces to 9:16, and wide link
# surfaces to 16:9. Email carries no media constraint and keeps the
# original without a derivative.
CHANNEL_DERIVATIVE_PREFERENCE: dict[str, str | None] = {
    "instagram": "4:5",
    "facebook": "4:5",
    "threads": "4:5",
    "pinterest": "4:5",
    "shopify": "4:5",
    "x": "16:9",
    "linkedin": "16:9",
    "tiktok": "9:16",
    "email": None,
}

MIME_BY_EXTENSION = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}


def _parse_aspect_key(key: str) -> tuple[int, int] | None:
    if not isinstance(key, str):
        return None
    parts = key.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        first, second = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if first <= 0 or second <= 0:
        return None
    return first, second


def canonical_aspect_ratio(width: int, height: int) -> str:
    """Name the asset aspect: canonical label or reduced ratio.

    Exact canonical matches (4:5, 1:1, 9:16, 16:9) win within a tight
    tolerance; anything else reduces by greatest common divisor
    (for example 1200x800 becomes 3:2).
    """
    if (not isinstance(width, int) or isinstance(width, bool)
            or not isinstance(height, int) or isinstance(height, bool)):
        raise ValueError("width and height must be integers")
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    ratio = width / height
    for label in CANONICAL_ASPECTS:
        parsed = _parse_aspect_key(label)
        if parsed is None:
            continue
        target = parsed[0] / parsed[1]
        if abs(ratio - target) <= 0.005:
            return label
    divisor = math.gcd(width, height)
    return "%d:%d" % (width // divisor, height // divisor)


def parse_png_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read PNG IHDR width and height, or None when absent."""
    if not isinstance(data, bytes) or len(data) < 24:
        return None
    if data[0:8] != b"\x89PNG\r\n\x1a\n":
        return None
    if data[12:16] != b"IHDR":
        return None
    try:
        width, height = struct.unpack(">II", data[16:24])
    except struct.error:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def parse_jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read JPEG SOF width and height, or None when absent."""
    if not isinstance(data, bytes) or len(data) < 4:
        return None
    if data[0:2] != b"\xff\xd8":
        return None
    index = 2
    size = len(data)
    while index + 3 < size:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker == 0xFF:
            index += 1
            continue
        if marker == 0xD8 or marker == 0xD9 or (0xD0 <= marker <= 0xD7) or marker == 0x01:
            index += 2
            continue
        if index + 3 >= size:
            return None
        length = struct.unpack(">H", data[index + 2:index + 4])[0]
        if length < 7 or index + length >= size:
            return None
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height = struct.unpack(">H", data[index + 5:index + 7])[0]
            width = struct.unpack(">H", data[index + 7:index + 9])[0]
            if width > 0 and height > 0:
                return width, height
            return None
        index += 2 + length
    return None


def parse_image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read image dimensions from PNG or JPEG header bytes."""
    found = parse_png_dimensions(data)
    if found is not None:
        return found
    return parse_jpeg_dimensions(data)


def decode_data_b64(data_b64: str | None) -> bytes | None:
    """Decode an optional base64 payload, or None when absent."""
    if data_b64 is None:
        return None
    if not isinstance(data_b64, str) or not data_b64.strip():
        return None
    try:
        return base64.b64decode(data_b64.strip(), validate=True)
    except (binascii.Error, ValueError):
        return None


def original_digest(data_b64: str | None, filename: str, width: int,
                    height: int, media_type: str) -> str:
    """Digest the immutable original bytes and metadata.

    The digest covers the uploaded payload plus the recorded format
    facts, so any overwrite of the original would change it.
    """
    payload = decode_data_b64(data_b64) or b""
    material = b"|".join([
        payload,
        str(filename or "").encode("utf-8"),
        str(width).encode("utf-8"),
        str(height).encode("utf-8"),
        str(media_type or "").encode("utf-8"),
    ])
    return hashlib.sha256(material).hexdigest()


def derivative_digest(source_digest: str, derivative_key: str) -> str:
    """Distinct digest for one derivative, bound to its source."""
    material = (str(source_digest) + ":" + str(derivative_key)).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def compute_crop_box(width: int, height: int, target: str) -> dict[str, int]:
    """Centered crop box fitting the target aspect inside the original.

    Returns integer pixel box {x, y, width, height} fully contained in
    the original frame.
    """
    parsed = _parse_aspect_key(target)
    if parsed is None:
        raise ValueError("Unknown derivative aspect: %s" % (target,))
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    target_ratio = parsed[0] / parsed[1]
    source_ratio = width / height
    if abs(source_ratio - target_ratio) <= 0.005:
        return {"x": 0, "y": 0, "width": width, "height": height}
    if source_ratio > target_ratio:
        crop_height = height
        crop_width = max(1, int(round(height * target_ratio)))
        offset_x = (width - crop_width) // 2
        return {"x": offset_x, "y": 0, "width": crop_width, "height": crop_height}
    crop_width = width
    crop_height = max(1, int(round(width / target_ratio)))
    offset_y = (height - crop_height) // 2
    return {"x": 0, "y": offset_y, "width": crop_width, "height": crop_height}


def normalize_focal_point(focal_x: Any, focal_y: Any) -> tuple[float, float]:
    """Validate an owner focal point as relative coordinates in [0, 1].

    (0.5, 0.5) is the frame center and reproduces the default centered
    crop. Raises ValueError naming the rule.
    """
    for name, value in (("focal_x", focal_x), ("focal_y", focal_y)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(name + " must be a number between 0 and 1")
        if not 0 <= float(value) <= 1:
            raise ValueError(name + " must be a number between 0 and 1")
    return (float(focal_x), float(focal_y))


def compute_focal_crop_box(width: int, height: int, target: str,
                           focal_x: float = 0.5,
                           focal_y: float = 0.5) -> dict[str, int]:
    """Crop box fitting the target aspect, biased toward the focal point.

    The box keeps the centered size and stays fully inside the frame;
    only its offset slides toward the owner focal point. The exact
    center reproduces compute_crop_box. Raises ValueError naming the rule.
    """
    focal_x, focal_y = normalize_focal_point(focal_x, focal_y)
    if focal_x == 0.5 and focal_y == 0.5:
        return compute_crop_box(width, height, target)
    box = compute_crop_box(width, height, target)
    free_x = width - box["width"]
    free_y = height - box["height"]
    offset_x = min(free_x, max(0, int(round(free_x * focal_x)))) if free_x else 0
    offset_y = min(free_y, max(0, int(round(free_y * focal_y)))) if free_y else 0
    return {"x": offset_x, "y": offset_y,
            "width": box["width"], "height": box["height"]}


def focal_derivative_digest(source_digest: str, derivative_key: str,
                            focal_x: float, focal_y: float) -> str:
    """Distinct digest for one focal derivative, bound to its source."""
    focal_x, focal_y = normalize_focal_point(focal_x, focal_y)
    material = (str(source_digest) + ":" + str(derivative_key)
                + ":%.6f,%.6f" % (focal_x, focal_y)).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def build_focal_derivatives(asset_id: str, width: int, height: int,
                            source_digest: str, focal_x: float, focal_y: float,
                            keys: Any = None) -> dict[str, dict[str, Any]]:
    """Generate focal crop records without touching the original.

    Each record carries its own digest, the focal crop box, the focal
    point, and a back link to the source asset with original_preserved
    True. Unknown aspect keys raise ValueError.
    """
    focal_x, focal_y = normalize_focal_point(focal_x, focal_y)
    wanted = list(DERIVATIVE_KEYS) if keys is None else list(keys)
    derivatives: dict[str, dict[str, Any]] = {}
    for key in wanted:
        if _parse_aspect_key(key) is None or key not in DERIVATIVE_KEYS:
            raise ValueError("Unknown derivative aspect: %s" % (key,))
        box = compute_focal_crop_box(width, height, key, focal_x, focal_y)
        derivatives[key] = {
            "derivative_key": key,
            "aspect_ratio": key,
            "width": box["width"],
            "height": box["height"],
            "crop_box": dict(box),
            "focal_point": {"x": focal_x, "y": focal_y},
            "derived_from_id": asset_id,
            "original_preserved": True,
            "sha256_digest": focal_derivative_digest(
                source_digest, key, focal_x, focal_y),
        }
    return derivatives


def build_derivatives(asset_id: str, width: int, height: int,
                      source_digest: str) -> dict[str, dict[str, Any]]:
    """Generate every channel-ready crop alongside the original.

    Each record carries its own digest, the centered crop box, and a
    back link to the source asset with original_preserved True. The
    original record is never touched here.
    """
    derivatives: dict[str, dict[str, Any]] = {}
    for key in DERIVATIVE_KEYS:
        parsed = _parse_aspect_key(key)
        if parsed is None:
            continue
        box = compute_crop_box(width, height, key)
        derivatives[key] = {
            "derivative_key": key,
            "aspect_ratio": key,
            "width": box["width"],
            "height": box["height"],
            "crop_box": dict(box),
            "derived_from_id": asset_id,
            "original_preserved": True,
            "sha256_digest": derivative_digest(source_digest, key),
        }
    return derivatives


def infer_media_type(filename: str, mime_type: str | None,
                     duration_seconds: Any) -> str:
    """Infer image vs video from MIME type, filename, or duration."""
    if isinstance(duration_seconds, (int, float)) and duration_seconds > 0:
        return "video"
    lowered_mime = (mime_type or "").strip().lower()
    if lowered_mime.startswith("video/"):
        return "video"
    if lowered_mime.startswith("image/"):
        return "image"
    lowered_name = (filename or "").strip().lower()
    for extension, mime in MIME_BY_EXTENSION.items():
        if lowered_name.endswith(extension):
            return "video" if mime.startswith("video/") else "image"
    return "image"


def normalize_filename(filename: Any) -> str:
    """Require a short plain-text filename for one uploaded asset."""
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("filename must be a nonempty string")
    cleaned = " ".join(filename.strip().split())
    if len(cleaned) > 200:
        raise ValueError("filename must be at most 200 characters")
    for char in cleaned:
        if ord(char) < 32 or ord(char) == 127:
            raise ValueError("filename contains unsafe control characters")
    return cleaned


def validate_upload(filename: Any, mime_type: Any, width: Any,
                    height: Any, duration_seconds: Any,
                    data_b64: Any) -> dict[str, Any]:
    """Validate one upload-once payload and compute its format facts."""
    name = normalize_filename(filename)
    if mime_type is not None and (not isinstance(mime_type, str) or not mime_type.strip()):
        raise ValueError("mime_type must be a nonempty string when provided")
    mime = mime_type.strip() if isinstance(mime_type, str) else None
    payload = decode_data_b64(data_b64) if data_b64 is not None else None
    if data_b64 is not None and not (isinstance(data_b64, str) and data_b64.strip()) and data_b64 is not None:
        raise ValueError("data_b64 must be a nonempty base64 string when provided")
    parsed_width: int | None = None
    parsed_height: int | None = None
    if payload:
        parsed = parse_image_dimensions(payload)
        if parsed is not None:
            parsed_width, parsed_height = parsed
    if width is None and parsed_width is not None:
        width = parsed_width
    if height is None and parsed_height is not None:
        height = parsed_height
    if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
        raise ValueError("width must be a positive integer (or supply decodable image bytes)")
    if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
        raise ValueError("height must be a positive integer (or supply decodable image bytes)")
    if width > 16384 or height > 16384:
        raise ValueError("width and height must each be at most 16384 pixels")
    duration: float | None = None
    if duration_seconds is not None:
        if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (int, float)):
            raise ValueError("duration_seconds must be a number when provided")
        if duration_seconds < 0:
            raise ValueError("duration_seconds must not be negative")
        duration = float(duration_seconds)
    media_type = infer_media_type(name, mime, duration)
    aspect = canonical_aspect_ratio(width, height)
    digest = original_digest(
        data_b64 if isinstance(data_b64, str) else None,
        name, width, height, media_type)
    return {"filename": name, "mime_type": mime, "media_type": media_type,
            "width": width, "height": height, "aspect_ratio": aspect,
            "duration_seconds": duration, "sha256_digest": digest}


def build_asset(asset_id: str, validated: dict[str, Any],
                data_b64: str | None) -> dict[str, Any]:
    """Assemble one stored asset row with derivatives alongside it."""
    digest = validated["sha256_digest"]
    derivatives = build_derivatives(asset_id, validated["width"],
                                    validated["height"], digest)
    return {"id": asset_id,
            "filename": validated["filename"],
            "media_type": validated["media_type"],
            "mime_type": validated["mime_type"],
            "width": validated["width"],
            "height": validated["height"],
            "aspect_ratio": validated["aspect_ratio"],
            "duration_seconds": validated["duration_seconds"],
            "sha256_digest": digest,
            "original_data_b64": data_b64,
            "derivatives": derivatives}


def derivative_for_channel(asset: dict[str, Any], channel: str) -> dict[str, Any] | None:
    """Pick the channel-ready derivative for one channel, or None.

    Email carries no media constraint and keeps the original; every
    other known channel resolves to its preferred crop. Unknown
    channels resolve to the 4:5 feed crop.
    """
    if not isinstance(asset, dict):
        return None
    key = (channel or "").strip().lower() if isinstance(channel, str) else ""
    preferred = CHANNEL_DERIVATIVE_PREFERENCE.get(key, FEED_REQUIRED_ASPECT)
    if preferred is None:
        return None
    derivatives = asset.get("derivatives")
    if not isinstance(derivatives, dict):
        return None
    record = derivatives.get(preferred)
    return dict(record) if isinstance(record, dict) else None


def resolve_channel_derivatives(asset: dict[str, Any],
                                channels: list[str],
                                use_original_without_derivative: bool = False
                                ) -> dict[str, dict[str, Any]]:
    """Bind each channel to its channel-ready derivative without re-upload.

    With use_original_without_derivative True every channel keeps the
    original, so a wrong-aspect original reaches the Checker unchanged
    and fails plainly.
    """
    mapping: dict[str, dict[str, Any]] = {}
    for channel in channels or []:
        if not isinstance(channel, str) or not channel.strip():
            continue
        key = channel.strip().lower()
        if key in mapping:
            continue
        if use_original_without_derivative:
            continue
        record = derivative_for_channel(asset, key)
        if record is not None:
            mapping[key] = record
    return mapping


def required_aspect_for_slot(slot_type: Any) -> str | None:
    """Required media aspect for one slot type, or None when unconstrained."""
    if slot_type == "feed_post":
        return FEED_REQUIRED_ASPECT
    return None


def _allowed_aspects(channel):
    """Media aspect list from one channel capability, or [] when unconstrained."""
    from .format_library import get_channel_capability

    capability = get_channel_capability(channel)
    if isinstance(capability, dict):
        constraints = capability.get("media_constraints")
        if isinstance(constraints, dict):
            raw = constraints.get("aspect_ratios")
            if isinstance(raw, list):
                return [str(entry) for entry in raw if isinstance(entry, str)]
    return []


def validate_slot_media(asset: dict[str, Any], slot_type: Any,
                        channels: list[str],
                        channel_derivatives: dict[str, dict[str, Any]],
                        use_original_without_derivative: bool = False
                        ) -> dict[str, Any]:
    """Checker validation of attached slot media against format rules.

    Feed slots require the uncropped original to carry the 4:5 aspect,
    so a wrong-aspect original attached without its 4:5 derivative
    fails naming the mismatch. Channel-ready derivatives are checked
    against their own channel media capabilities instead. Failures use
    plain language with the checked and required aspects recorded.
    """
    reasons: list[str] = []
    checked = asset.get("aspect_ratio") if isinstance(asset, dict) else None
    required = required_aspect_for_slot(slot_type)
    selected = [c.strip().lower() for c in (channels or [])
                if isinstance(c, str) and c.strip()]
    for channel in selected:
        record = (channel_derivatives or {}).get(channel)
        effective = None
        if isinstance(record, dict) and isinstance(record.get("aspect_ratio"), str):
            effective = record["aspect_ratio"]
        elif isinstance(asset, dict) and isinstance(asset.get("aspect_ratio"), str):
            effective = asset["aspect_ratio"]
        uncropped = use_original_without_derivative or not isinstance(record, dict)
        allowed = _allowed_aspects(channel)
        if (required is not None and uncropped and effective != required
                and allowed):
            reasons.append(
                "Feed slot media aspect ratio %s does not match required %s aspect ratio" % (
                    effective or "unknown", required))
        if allowed and effective is not None and effective not in allowed:
            reasons.append(
                "Channel %s media aspect ratio %s is not allowed; allowed aspects are %s" % (
                    channel, effective, ", ".join(allowed)))
    seen: list[str] = []
    for reason in reasons:
        if reason not in seen:
            seen.append(reason)
    return {"passed": not seen, "reasons": seen,
            "checked_aspect_ratio": checked,
            "required_aspect_ratio": required}


def focal_point_for(row: dict[str, Any]) -> dict[str, float] | None:
    """Return the stored owner focal point, or None when centered."""
    raw_x, raw_y = row.get("focal_x"), row.get("focal_y")
    if raw_x is None and raw_y is None:
        return None
    try:
        return {"x": float(raw_x), "y": float(raw_y)}
    except (TypeError, ValueError):
        return None


def media_public_asset(row: dict[str, Any]) -> dict[str, Any]:
    """Public asset shape with format facts and derivatives intact."""
    return {"id": row.get("id"),
            "focal_point": focal_point_for(row),
            "filename": row.get("filename"),
            "media_type": row.get("media_type"),
            "mime_type": row.get("mime_type"),
            "width": row.get("width"),
            "height": row.get("height"),
            "aspect_ratio": row.get("aspect_ratio"),
            "duration_seconds": row.get("duration_seconds"),
            "sha256_digest": row.get("sha256_digest"),
            "derivatives": row.get("derivatives") if isinstance(row.get("derivatives"), dict) else {},
            "format_facts": {"width": row.get("width"),
                             "height": row.get("height"),
                             "aspect_ratio": row.get("aspect_ratio"),
                             "duration_seconds": row.get("duration_seconds"),
                             "sha256_digest": row.get("sha256_digest"),
                             "original_preserved": True},
            "created_at": row.get("created_at")}
