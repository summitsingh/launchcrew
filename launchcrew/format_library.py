"""S2 format library and per-channel capabilities table.

Checker-enforced format rules for feed_carousel, reel_script,
story_sequence, and single_image. All helpers are pure stdlib with
no network, model, file, or environment access. Reasons are plain
human-readable strings naming the rule that failed.
"""

from __future__ import annotations

from typing import Any

FORMAT_VERSION = "format-library/v1"
CAPABILITIES_VERSION = "channel-capabilities/v1"

FEED_CAROUSEL_MIN_FRAMES = 5
FEED_CAROUSEL_MAX_FRAMES = 10
FEED_CAROUSEL_ASPECT = "4:5"
REEL_HOOK_MAX_CHARS = 140
STORY_MIN_FRAMES = 3
STORY_MAX_FRAMES = 6

CHANNEL_CAPABILITIES: dict[str, dict[str, Any]] = {
    "instagram": {
        "channel": "instagram",
        "allowed_formats": ["feed_carousel", "reel_script", "story_sequence", "single_image"],
        "caption_limit": 2200,
        "media_constraints": {"aspect_ratios": ["4:5", "1:1", "9:16"], "min_frames": 1, "max_frames": 10},
    },
    "facebook": {
        "channel": "facebook",
        "allowed_formats": ["feed_carousel", "reel_script", "story_sequence", "single_image"],
        "caption_limit": 2000,
        "media_constraints": {"aspect_ratios": ["4:5", "1:1", "16:9"], "min_frames": 1, "max_frames": 10},
    },
    "threads": {
        "channel": "threads",
        "allowed_formats": ["single_image", "story_sequence", "feed_carousel"],
        "caption_limit": 500,
        "media_constraints": {"aspect_ratios": ["4:5", "1:1"], "min_frames": 1, "max_frames": 10},
    },
    "x": {
        "channel": "x",
        "allowed_formats": ["single_image"],
        "caption_limit": 280,
        "media_constraints": {"aspect_ratios": ["16:9", "1:1", "4:5"], "min_frames": 1, "max_frames": 4},
    },
    "linkedin": {
        "channel": "linkedin",
        "allowed_formats": ["single_image", "feed_carousel"],
        "caption_limit": 3000,
        "media_constraints": {"aspect_ratios": ["4:5", "1:1", "16:9"], "min_frames": 1, "max_frames": 10},
    },
    "tiktok": {
        "channel": "tiktok",
        "allowed_formats": ["reel_script", "single_image"],
        "caption_limit": 2200,
        "media_constraints": {"aspect_ratios": ["9:16"], "min_frames": 1, "max_frames": 10},
    },
    "pinterest": {
        "channel": "pinterest",
        "allowed_formats": ["single_image", "feed_carousel"],
        "caption_limit": 500,
        "media_constraints": {"aspect_ratios": ["4:5", "1:1"], "min_frames": 1, "max_frames": 10},
    },
    "email": {
        "channel": "email",
        "allowed_formats": ["single_image"],
        "caption_limit": 10000,
        "media_constraints": {"aspect_ratios": [], "min_frames": 0, "max_frames": 0},
    },
    "shopify": {
        "channel": "shopify",
        "allowed_formats": ["single_image"],
        "caption_limit": 2000,
        "media_constraints": {"aspect_ratios": ["4:5", "1:1"], "min_frames": 0, "max_frames": 0},
    },
}

CAPABILITY_CHANNELS = tuple(CHANNEL_CAPABILITIES.keys())


def list_formats() -> list[dict[str, Any]]:
    """Describe each supported format with its Checker-enforced rule."""
    return [
        {"format": "feed_carousel",
         "label": "Feed carousel",
         "rule": "Feed carousel needs 5 to 10 frames at 4:5 aspect ratio.",
         "min_frames": FEED_CAROUSEL_MIN_FRAMES,
         "max_frames": FEED_CAROUSEL_MAX_FRAMES,
         "aspect_ratio": FEED_CAROUSEL_ASPECT},
        {"format": "reel_script",
         "label": "Reel script",
         "rule": "Reel script needs a hook under 140 characters and a shot list with at least 1 shot.",
         "hook_max_chars": REEL_HOOK_MAX_CHARS},
        {"format": "story_sequence",
         "label": "Story sequence",
         "rule": "Story sequence needs 3 to 6 frames with one idea per frame.",
         "min_frames": STORY_MIN_FRAMES,
         "max_frames": STORY_MAX_FRAMES},
        {"format": "single_image",
         "label": "Single image",
         "rule": "Single image is allowed for stories and ads drafts, never for feed posts.",
         "allowed_surfaces": ["stories", "ads"],
         "blocked_surfaces": ["feed"]},
    ]


def list_channel_capabilities() -> list[dict[str, Any]]:
    """Return the per-channel capabilities table rows in channel order."""
    import copy

    return [copy.deepcopy(CHANNEL_CAPABILITIES[channel]) for channel in CAPABILITY_CHANNELS]


def get_channel_capability(channel: Any) -> dict[str, Any] | None:
    """Return a copy of one channel capability row, or None when unknown."""
    import copy

    if not isinstance(channel, str):
        return None
    row = CHANNEL_CAPABILITIES.get(channel.strip().lower())
    return copy.deepcopy(row) if row is not None else None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _frame_count_of(spec: dict[str, Any]) -> int | None:
    count = _as_int(spec.get("frame_count"))
    if count is not None:
        return count
    frames = spec.get("frames")
    if isinstance(frames, list):
        return len(frames)
    ideas = spec.get("frame_ideas")
    if isinstance(ideas, list):
        return len(ideas)
    return None


def check_format(spec: Any) -> dict[str, Any]:
    """Check one format spec against Checker-enforced format rules.

    Accepted spec keys: format_kind (or format), frame_count (or frames
    / frame_ideas length), aspect_ratio, hook_text, shots, frame_ideas,
    target_surface. Returns a dict with passed (bool), format, and
    reasons (list of plain human-readable strings). Unknown or missing
    format fails closed with a plain reason.
    """
    if not isinstance(spec, dict):
        return {"passed": False, "format": None, "version": FORMAT_VERSION,
                "reasons": ["No format was supplied; pick feed_carousel, reel_script, story_sequence, or single_image."]}
    raw_kind = spec.get("format_kind", spec.get("format"))
    kind = raw_kind.strip().lower() if isinstance(raw_kind, str) else None
    if kind == "feed_post":
        kind = "feed_carousel"
    if kind not in ("feed_carousel", "reel_script", "story_sequence", "single_image"):
        return {"passed": False, "format": raw_kind, "version": FORMAT_VERSION,
                "reasons": ["Unknown format '%s'; pick feed_carousel, reel_script, story_sequence, or single_image." % (raw_kind,)]}
    reasons: list[str] = []
    if kind == "feed_carousel":
        count = _frame_count_of(spec)
        aspect = spec.get("aspect_ratio")
        aspect_text = aspect.strip() if isinstance(aspect, str) else ""
        if count is None:
            reasons.append("Feed carousel needs 5 to 10 frames at 4:5 aspect ratio; frame count is missing.")
        elif not FEED_CAROUSEL_MIN_FRAMES <= count <= FEED_CAROUSEL_MAX_FRAMES:
            if count == 1:
                reasons.append("Blocked: a 1-frame feed post is not a carousel; the carousel rule needs 5 to 10 frames at 4:5.")
            else:
                reasons.append("Blocked: feed carousel needs 5 to 10 frames at 4:5; got %d frames." % count)
        if aspect_text != FEED_CAROUSEL_ASPECT:
            reasons.append("Blocked: feed carousel needs 4:5 aspect ratio; got '%s'." % (aspect_text or "missing"))
        passed = not reasons
        return {"passed": passed, "format": kind, "version": FORMAT_VERSION,
                "frame_count": count, "aspect_ratio": aspect_text or None, "reasons": reasons}
    if kind == "reel_script":
        hook = spec.get("hook_text", spec.get("hook"))
        shots = spec.get("shots", spec.get("shot_list"))
        if not isinstance(hook, str) or not hook.strip():
            reasons.append("Blocked: reel script needs a hook under 140 characters; hook text is missing.")
        elif len(hook.strip()) >= REEL_HOOK_MAX_CHARS:
            reasons.append("Blocked: reel hook is %d characters; the reel hook limit is under 140 characters." % len(hook.strip()))
        if not isinstance(shots, list) or not [s for s in shots if isinstance(s, str) and s.strip()]:
            reasons.append("Blocked: reel script needs a shot list with at least 1 shot.")
        passed = not reasons
        return {"passed": passed, "format": kind, "version": FORMAT_VERSION,
                "hook_chars": len(hook.strip()) if isinstance(hook, str) else None,
                "shot_count": len([s for s in shots if isinstance(s, str) and s.strip()]) if isinstance(shots, list) else 0,
                "reasons": reasons}
    if kind == "story_sequence":
        ideas = spec.get("frame_ideas", spec.get("frames"))
        if not isinstance(ideas, list) or not ideas:
            reasons.append("Blocked: story sequence needs 3 to 6 frames with one idea per frame; no frames were supplied.")
            return {"passed": False, "format": kind, "version": FORMAT_VERSION, "frame_count": 0, "reasons": reasons}
        count = len(ideas)
        if not STORY_MIN_FRAMES <= count <= STORY_MAX_FRAMES:
            reasons.append("Blocked: story sequence needs 3 to 6 frames with one idea per frame; got %d frames." % count)
        blanks = [i for i in range(count) if not (isinstance(ideas[i], str) and ideas[i].strip())]
        if blanks:
            reasons.append("Blocked: story sequence needs one idea per frame; frame %d is blank." % (blanks[0] + 1,))
        passed = not reasons
        return {"passed": passed, "format": kind, "version": FORMAT_VERSION, "frame_count": count, "reasons": reasons}
    surface = spec.get("target_surface", spec.get("surface"))
    surface_text = surface.strip().lower() if isinstance(surface, str) else ""
    if surface_text in ("feed", "feed_post", "feed post"):
        reasons.append("Blocked: single_image is never allowed for feed posts; use feed_carousel with 5 to 10 frames at 4:5, or move this to stories or ads drafts.")
    elif surface_text and surface_text not in ("stories", "story", "ads", "ad", "email", "shopify", "draft"):
        reasons.append("Blocked: single_image is allowed for stories and ads drafts, never for feed posts; got surface '%s'." % surface_text)
    passed = not reasons
    return {"passed": passed, "format": kind, "version": FORMAT_VERSION,
            "target_surface": surface_text or None, "reasons": reasons}


def format_block_reason(spec: Any, result: dict[str, Any] | None = None) -> str | None:
    """Return the first plain format block reason, or None when passing."""
    checked = result if isinstance(result, dict) else check_format(spec)
    if checked.get("passed") is True:
        return None
    reasons = checked.get("reasons")
    if isinstance(reasons, list) and reasons:
        first = reasons[0]
        if isinstance(first, str) and first.strip():
            return first
    return "Blocked by format rule."
