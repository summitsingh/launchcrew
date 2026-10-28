"""Photo geometry policy v1: pure stdlib verdict over SAM records.

Implements plan Task 1 of docs/superpowers/plans/2026-10-28-photo-review.md
per spec section 4 of docs/superpowers/specs/2026-10-28-photo-review-design.md.

Record shape matches backend/sam.py parse_sse output. The mask is a
cropped raster for its box: origin (0, 0) with positive dims bounded by
the frame, never required to equal the frame size. The opaque payload is
never decoded or propagated. No I/O, no assets, stdlib only.
"""
from typing import TypedDict

PHOTO_POLICY_VERSION: str = "photo-geometry/v1"


class SamMask(TypedDict):
    x: int
    y: int
    height: int
    width: int
    encoding: str
    payload: str


class SamRecord(TypedDict):
    frame: int
    object_id: int
    box: tuple[int, int, int, int, int, int]
    mask: SamMask


class PhotoVerdict(TypedDict):
    label: str
    reason: str
    policy_version: str


class CropBox(TypedDict):
    x1: int
    y1: int
    x2: int
    y2: int


def _is_int(value: object) -> bool:
    return type(value) is int


def _valid_frame_arg(frame: object) -> bool:
    if not isinstance(frame, (tuple, list)) or len(frame) != 2:
        return False
    width, height = frame
    return (
        _is_int(width)
        and _is_int(height)
        and width > 0
        and height > 0
    )


def _valid_record(rec: object, frame_w: int, frame_h: int) -> bool:
    if not isinstance(rec, dict):
        return False
    if type(rec.get("frame")) is not int or rec.get("frame") != 0:
        return False
    if not _is_int(rec.get("object_id")):
        return False
    box = rec.get("box")
    if not isinstance(box, (tuple, list)) or len(box) != 6:
        return False
    if not all(_is_int(v) for v in box):
        return False
    x1, y1, x2, y2, w, h = box
    if w <= 0 or h <= 0:
        return False
    if w != frame_w or h != frame_h:
        return False
    if x2 < x1 or y2 < y1:
        return False
    if x1 < 0 or y1 < 0 or x2 >= w or y2 >= h:
        return False
    mask = rec.get("mask")
    if not isinstance(mask, dict):
        return False
    if type(mask.get("x")) is not int or mask.get("x") != 0:
        return False
    if type(mask.get("y")) is not int or mask.get("y") != 0:
        return False
    mh, mw = mask.get("height"), mask.get("width")
    if not _is_int(mh) or not _is_int(mw):
        return False
    if mh <= 0 or mw <= 0 or mh > frame_h or mw > frame_w:
        return False
    if mask.get("encoding") != "lossless":
        return False
    if not isinstance(mask.get("payload"), str):
        return False
    return True


def classify_photo_geometry(
    records: list[SamRecord], frame: tuple[int, int] | None
) -> PhotoVerdict:
    """Classify normalized SAM records into a reviewable verdict."""
    if not isinstance(records, list):
        return {
            "label": "unknown",
            "reason": "fix_photo",
            "policy_version": PHOTO_POLICY_VERSION,
        }
    if len(records) == 0:
        return {
            "label": "not_detected",
            "reason": "no_match",
            "policy_version": PHOTO_POLICY_VERSION,
        }
    if not _valid_frame_arg(frame):
        return {
            "label": "unknown",
            "reason": "fix_photo",
            "policy_version": PHOTO_POLICY_VERSION,
        }
    frame_w, frame_h = frame[0], frame[1]
    for rec in records:
        if not _valid_record(rec, frame_w, frame_h):
            return {
                "label": "unknown",
                "reason": "fix_photo",
                "policy_version": PHOTO_POLICY_VERSION,
            }
    if len(records) >= 2:
        return {
            "label": "unknown",
            "reason": "needs_review",
            "policy_version": PHOTO_POLICY_VERSION,
        }
    box = records[0]["box"]
    x1, y1, x2, y2, w, h = box
    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    frame_area = w * h
    near_edge = min(x1, y1, w - 1 - x2, h - 1 - y2) <= 2
    if near_edge or area < 0.02 * frame_area or area > 0.98 * frame_area:
        return {
            "label": "possible_clipping",
            "reason": "edge_or_size_gate",
            "policy_version": PHOTO_POLICY_VERSION,
        }
    return {
        "label": "detected",
        "reason": "clear_single",
        "policy_version": PHOTO_POLICY_VERSION,
    }


def suggest_crop(
    box: tuple[int, int, int, int, int, int],
    frame: tuple[int, int],
    pad_ratio: float = 0.08,
) -> CropBox:
    """Pad each box side by pad_ratio of box size, clamped to the frame."""
    if (
        not isinstance(box, (tuple, list))
        or len(box) != 6
        or not all(_is_int(v) for v in box)
    ):
        raise ValueError("box must be six ints")
    if not _valid_frame_arg(frame):
        raise ValueError("frame must be two positive ints")
    if (
        isinstance(pad_ratio, bool)
        or not isinstance(pad_ratio, (int, float))
        or pad_ratio < 0
    ):
        raise ValueError("pad_ratio must be a non-negative number")
    x1, y1, x2, y2, w, h = box
    frame_w, frame_h = frame[0], frame[1]
    if w != frame_w or h != frame_h or w <= 0 or h <= 0:
        raise ValueError("box dims must match a positive frame")
    if x2 < x1 or y2 < y1 or x1 < 0 or y1 < 0 or x2 >= w or y2 >= h:
        raise ValueError("box coords out of frame")
    box_w = x2 - x1 + 1
    box_h = y2 - y1 + 1
    pad_x = pad_ratio * box_w
    pad_y = pad_ratio * box_h
    cx1 = min(max(round(x1 - pad_x), 0), frame_w - 1)
    cy1 = min(max(round(y1 - pad_y), 0), frame_h - 1)
    cx2 = min(max(round(x2 + pad_x), 0), frame_w - 1)
    cy2 = min(max(round(y2 + pad_y), 0), frame_h - 1)
    return {"x1": cx1, "y1": cy1, "x2": cx2, "y2": cy2}
