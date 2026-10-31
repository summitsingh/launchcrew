"""Visual context and ratio linter for photos.

Pure stdlib deterministic checks of image aspect ratio and resolution
against channel requirements. Dimensions are parsed directly from PNG
and JPEG binary headers, with an optional PIL fallback when headers
cannot be parsed and PIL is installed. No I/O beyond reading a file
path when one is given, no model calls, no credentials.
"""

import os
import struct

PHOTO_LINT_VERSION = "photo-lint/v1"

RETINA_MIN_PX = 1080

TARGET_RATIOS = {
    "feed_square": {"ratio": 1.0, "label": "1:1", "tolerance": 0.02},
    "instagram_ad_portrait": {"ratio": 0.80, "label": "4:5", "tolerance": 0.02},
    "reels_story_vertical": {"ratio": 0.5625, "label": "9:16", "tolerance": 0.02},
    "landscape": {"ratio": 16.0 / 9.0, "label": "16:9", "tolerance": 0.02},
}

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_JPEG_SOF_MARKERS = frozenset({
    0xC0, 0xC1, 0xC2, 0xC3,
    0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB,
    0xCD, 0xCE, 0xCF,
})

_JPEG_STANDALONE = frozenset({0xD8, 0xD9, 0x01} | set(range(0xD0, 0xD8)))


def _read_bytes(data_or_path):
    if isinstance(data_or_path, (bytes, bytearray, memoryview)):
        return bytes(data_or_path)
    if isinstance(data_or_path, (str, os.PathLike)):
        with open(data_or_path, "rb") as handle:
            return handle.read()
    raise TypeError("data_or_path must be bytes or a file path")


def _parse_png_dimensions(data):
    if len(data) < 24:
        raise ValueError("not a PNG: truncated header")
    if data[:8] != _PNG_SIGNATURE:
        raise ValueError("not a PNG: bad signature")
    if data[12:16] != b"IHDR":
        raise ValueError("not a PNG: missing IHDR")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        raise ValueError("not a PNG: bad dimensions")
    return (width, height)


def _parse_jpeg_dimensions(data):
    if len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
        raise ValueError("not a JPEG: bad SOI")
    pos = 2
    size = len(data)
    while pos < size:
        if data[pos] != 0xFF:
            pos += 1
            continue
        while pos < size and data[pos] == 0xFF:
            pos += 1
        if pos >= size:
            break
        marker = data[pos]
        pos += 1
        if marker in _JPEG_STANDALONE or marker == 0x00:
            continue
        if pos + 2 > size:
            raise ValueError("not a JPEG: truncated segment")
        seg_len = struct.unpack(">H", data[pos:pos + 2])[0]
        if seg_len < 2:
            raise ValueError("not a JPEG: bad segment length")
        if marker in _JPEG_SOF_MARKERS:
            if pos + 7 >= size:
                raise ValueError("not a JPEG: truncated SOF")
            height = struct.unpack(">H", data[pos + 3:pos + 5])[0]
            width = struct.unpack(">H", data[pos + 5:pos + 7])[0]
            if width <= 0 or height <= 0:
                raise ValueError("not a JPEG: bad dimensions")
            return (width, height)
        pos += seg_len
    raise ValueError("not a JPEG: no SOF marker found")


def _parse_with_pil(data):
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("unsupported image format") from exc
    import io
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
    except Exception as exc:
        raise ValueError("unsupported image format") from exc
    if not width or not height:
        raise ValueError("unsupported image format")
    return (int(width), int(height))


def get_image_dimensions(data_or_path):
    """Extract (width, height) from image bytes or a file path.

    Parses PNG and JPEG binary headers directly with stdlib only.
    Falls back to PIL when headers cannot be parsed and PIL is
    installed. Raises TypeError for unsupported input types and
    ValueError for undecodable image data.
    """
    data = _read_bytes(data_or_path)
    errors = []
    for parser in (_parse_png_dimensions, _parse_jpeg_dimensions):
        try:
            return parser(data)
        except ValueError as exc:
            errors.append(exc)
    try:
        return _parse_with_pil(data)
    except ValueError:
        raise errors[0] if errors else ValueError("unsupported image format")


def lint_photo_aspect_ratio(width, height, target_channel):
    """Lint width/height against a target channel ratio.

    Returns {"compliant", "aspect_ratio", "target_ratio", "warning"}.
    "target_ratio" is the label string (e.g. "1:1"). Raises
    ValueError for bad dimensions or an unknown channel.
    """
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
    ):
        raise ValueError("width and height must be positive ints")
    spec = TARGET_RATIOS.get(target_channel)
    if spec is None:
        raise ValueError("unknown target_channel: %r" % (target_channel,))
    aspect = width / height
    compliant = abs(aspect - spec["ratio"]) <= spec["tolerance"]
    warning = None
    if not compliant:
        warning = (
            "aspect ratio %.4f does not match %s target %s (%.4f)"
            % (aspect, target_channel, spec["label"], spec["ratio"])
        )
    return {
        "compliant": compliant,
        "aspect_ratio": aspect,
        "target_ratio": spec["label"],
        "warning": warning,
    }


def lint_photo_resolution(width, height, min_width=1080, min_height=1080):
    """Lint width/height against minimum resolution guidelines.

    Returns {"compliant", "width", "height", "warning"}. Defaults
    enforce the 1080px retina minimum on both axes. Raises ValueError
    for bad dimensions or bad minima.
    """
    for name, value in (("width", width), ("height", height)):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
        ):
            raise ValueError("%s must be a positive int" % name)
    for name, value in (("min_width", min_width), ("min_height", min_height)):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
        ):
            raise ValueError("%s must be a positive int" % name)
    compliant = width >= min_width and height >= min_height
    warning = None
    if not compliant:
        warning = (
            "resolution %dx%d below minimum %dx%d"
            % (width, height, min_width, min_height)
        )
    return {
        "compliant": compliant,
        "width": width,
        "height": height,
        "warning": warning,
    }


def audit_photo(data_or_path, target_channels):
    """Full audit summary for image bytes or a file path.

    Returns a dict with version, width, height, aspect_ratio,
    per-channel aspect results, resolution result, overall compliant
    flag, and a warnings list. Raises ValueError for bad channels.
    """
    if not isinstance(target_channels, list) or not target_channels:
        raise ValueError("target_channels must be a non-empty list")
    if any(not isinstance(c, str) for c in target_channels):
        raise ValueError("target_channels must be a list of str")
    width, height = get_image_dimensions(data_or_path)
    channels = {}
    for channel in target_channels:
        channels[channel] = lint_photo_aspect_ratio(width, height, channel)
    resolution = lint_photo_resolution(width, height)
    warnings = []
    for channel, result in channels.items():
        if result["warning"]:
            warnings.append("%s: %s" % (channel, result["warning"]))
    if resolution["warning"]:
        warnings.append(resolution["warning"])
    compliant = all(r["compliant"] for r in channels.values())
    compliant = compliant and resolution["compliant"]
    return {
        "version": PHOTO_LINT_VERSION,
        "width": width,
        "height": height,
        "aspect_ratio": width / height,
        "channels": channels,
        "resolution": resolution,
        "compliant": compliant,
        "warnings": warnings,
    }
