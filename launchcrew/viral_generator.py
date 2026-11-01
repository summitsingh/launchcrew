"""SC5 viral format generator: metered, owner-media-only packs.

Owner uploads 3 to 10 screenshots or one screen recording plus the
confirmed facts, and LaunchCrew builds a swipeable carousel or short
video pack in the brand voice that passes the Checker as a normal
approval-bound pack. Every generation spends one visible credit and
fails closed when credits are exhausted, before any pipeline or
provider call. Every asset comes from the owner upload, never from a
library of other creators clips.

All helpers are pure stdlib with no network, model, file, or
environment access. Reasons are plain human-readable strings naming
the rule that failed.
"""

from __future__ import annotations

from typing import Any

MODULE_VERSION = "viral-generator/v1"

DEFAULT_CREDITS = 10
CREDITS_PER_GENERATION = 1

MEDIA_MODES = ("screenshots", "screen_recording")
OUTPUT_FORMATS = ("carousel", "short_video")
MEDIA_PROVENANCE = "owner_upload_only"

MIN_SCREENSHOTS = 3
MAX_SCREENSHOTS = 10
REQUIRED_RECORDINGS = 1

CAROUSEL_MIN_FRAMES = 5
CAROUSEL_MAX_FRAMES = 10
CAROUSEL_ASPECT = "4:5"
SHORT_VIDEO_ASPECT = "9:16"
SHORT_VIDEO_SCENES = 3
REEL_HOOK_MAX_CHARS = 140

MAX_FACT_SENTENCES = 12
MAX_FACT_CHARS = 200

CREDITS_EXHAUSTED_MESSAGE = (
    "viral_credits_exhausted: 0 credits remaining; "
    "generation refused before any provider call"
)
OWNER_MEDIA_ONLY_MESSAGE = (
    "owner_media_only: every asset must come from the owner upload, "
    "never a creator clip library or third party stock source"
)
SCREENSHOTS_COUNT_MESSAGE = (
    "screenshots_count_must_be_3_to_10: carousel needs 3 to 10 owner "
    "screenshots, got %d"
)
SCREEN_RECORDING_COUNT_MESSAGE = (
    "screen_recording_requires_single_video: short video needs exactly "
    "1 owner screen recording, got %d"
)
CONFIRMED_FACTS_MESSAGE = (
    "confirmed_facts_required: confirmed facts must be a nonempty string"
)

FOREIGN_ID_PREFIXES = ("creator_", "stock_", "library_", "clip_", "external_")
FOREIGN_ID_MARKERS = ("creator_clip", "clip_library", "stock_clip")


def credits_exhausted(remaining: int | None) -> bool:
    """True when no generation credit remains, failing closed at zero."""
    return not isinstance(remaining, int) or remaining <= 0


def refuse_if_exhausted(remaining: int | None) -> None:
    """Raise before any pipeline or provider call when credits are out."""
    if credits_exhausted(remaining):
        raise ValueError(CREDITS_EXHAUSTED_MESSAGE)


def normalize_confirmed_facts(value: Any) -> str:
    """Require a nonempty owner confirmed-facts string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(CONFIRMED_FACTS_MESSAGE)
    return " ".join(value.strip().split())


def split_fact_sentences(confirmed_facts: str) -> list[str]:
    """Split confirmed facts into short unique sentences for claims.

    Each sentence is capped at 200 characters and the list at 12 so the
    sentences always fit the owner allowed-claim shape downstream.
    """
    text = normalize_confirmed_facts(confirmed_facts)
    sentences: list[str] = []
    current: list[str] = []

    def flush() -> None:
        sentence = "".join(current).strip()
        current.clear()
        if not sentence:
            return
        if len(sentence) > MAX_FACT_CHARS:
            sentence = sentence[:MAX_FACT_CHARS].rstrip()
        if sentence and sentence not in sentences:
            sentences.append(sentence)

    for char in text:
        current.append(char)
        if char in (".", "!", "?"):
            flush()
    flush()
    if not sentences:
        sentences.append(text[:MAX_FACT_CHARS].rstrip())
    return sentences[:MAX_FACT_SENTENCES]


def normalize_media_mode(value: Any, has_screenshots: bool = False,
                         has_recording: bool = False) -> str:
    """Resolve screenshots vs screen_recording mode, defaulting by input."""
    if value is None:
        return "screen_recording" if has_recording and not has_screenshots else "screenshots"
    if not isinstance(value, str):
        raise ValueError("media_mode must be screenshots or screen_recording")
    mode = value.strip().lower()
    if mode not in MEDIA_MODES:
        raise ValueError("media_mode must be screenshots or screen_recording")
    return mode


def _item_source(item: Any) -> str | None:
    if isinstance(item, dict):
        for key in ("source", "media_source", "provenance"):
            raw = item.get(key)
            if raw is not None:
                return str(raw).strip().lower()
    return None


def _item_id_text(item: Any) -> str:
    if isinstance(item, str):
        return item.strip().lower()
    if isinstance(item, dict):
        for key in ("id", "asset_id", "clip_id", "creator_clip_id",
                    "library_id", "stock_id", "clip_library_id"):
            raw = item.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip().lower()
    return ""


def validate_owner_item(item: Any) -> None:
    """Reject any item that is not an owner upload."""
    source = _item_source(item)
    if source is not None and source != "owner_upload":
        raise ValueError(OWNER_MEDIA_ONLY_MESSAGE)
    ident = _item_id_text(item)
    if ident.startswith(FOREIGN_ID_PREFIXES):
        raise ValueError(OWNER_MEDIA_ONLY_MESSAGE)
    for marker in FOREIGN_ID_MARKERS:
        if marker in ident:
            raise ValueError(OWNER_MEDIA_ONLY_MESSAGE)
    if isinstance(item, str) and "://" in item:
        raise ValueError(OWNER_MEDIA_ONLY_MESSAGE)


def validate_owner_media_source(media_source: Any) -> None:
    """Reject a request-level non-owner media source."""
    if media_source is None:
        return
    if not isinstance(media_source, str) or media_source.strip().lower() != "owner_upload":
        raise ValueError(OWNER_MEDIA_ONLY_MESSAGE)


def validate_counts(media_mode: str, screenshot_count: int,
                    recording_count: int) -> None:
    """Enforce the per-mode owner media count rules."""
    if media_mode == "screenshots":
        if recording_count != 0 or not MIN_SCREENSHOTS <= screenshot_count <= MAX_SCREENSHOTS:
            raise ValueError(SCREENSHOTS_COUNT_MESSAGE % (screenshot_count,))
        return
    if media_mode == "screen_recording":
        if screenshot_count != 0 or recording_count != REQUIRED_RECORDINGS:
            raise ValueError(SCREEN_RECORDING_COUNT_MESSAGE % (recording_count,))
        return
    raise ValueError("media_mode must be screenshots or screen_recording")


def output_format_for(media_mode: str) -> str:
    """Map the owner media mode to the built pack format."""
    if media_mode == "screen_recording":
        return "short_video"
    return "carousel"


def _sentence_for(index: int, sentences: list[str]) -> str:
    if not sentences:
        return "Owner confirmed fact %d." % (index + 1,)
    return sentences[index % len(sentences)]


def build_carousel_frames(screenshot_labels: list[str],
                          confirmed_facts: str) -> list[dict[str, Any]]:
    """Build 5 to 10 frames at 4:5 grounded in the confirmed facts."""
    sentences = split_fact_sentences(confirmed_facts)
    count = len(screenshot_labels)
    frame_count = min(CAROUSEL_MAX_FRAMES, max(CAROUSEL_MIN_FRAMES, count))
    frames: list[dict[str, Any]] = []
    for index in range(frame_count):
        label = screenshot_labels[index % count] if count else "owner_screenshot_%d" % (index + 1,)
        frames.append({
            "frame_index": index + 1,
            "frame_count": frame_count,
            "aspect_ratio": CAROUSEL_ASPECT,
            "text": "Frame %d of %d: %s" % (index + 1, frame_count, _sentence_for(index, sentences)),
            "source_asset": label,
            "media_provenance": MEDIA_PROVENANCE,
        })
    return frames


def build_short_video_scenes(recording_label: str,
                             confirmed_facts: str) -> list[dict[str, Any]]:
    """Build short video scenes at 9:16 grounded in the confirmed facts."""
    sentences = split_fact_sentences(confirmed_facts)
    hook = _sentence_for(0, sentences)
    if len(hook) >= REEL_HOOK_MAX_CHARS:
        hook = hook[:REEL_HOOK_MAX_CHARS - 3].rstrip() + "..."
    scenes: list[dict[str, Any]] = []
    beats = ["Hook", "Proof", "Close"]
    for index in range(SHORT_VIDEO_SCENES):
        scenes.append({
            "scene_index": index + 1,
            "scene_count": SHORT_VIDEO_SCENES,
            "aspect_ratio": SHORT_VIDEO_ASPECT,
            "beat": beats[index],
            "hook" if index == 0 else "shot_text": hook if index == 0 else _sentence_for(index, sentences),
            "source_asset": recording_label,
            "media_provenance": MEDIA_PROVENANCE,
        })
    return scenes


def format_spec_for(media_mode: str,
                    frames_or_scenes: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the Checker-enforced S2 format spec for the pack."""
    if media_mode == "screen_recording":
        hook = ""
        shots: list[str] = []
        for scene in frames_or_scenes:
            if isinstance(scene, dict):
                if not hook and isinstance(scene.get("hook"), str):
                    hook = scene["hook"]
                text = scene.get("shot_text") or scene.get("hook")
                if isinstance(text, str) and text.strip():
                    shots.append(text.strip())
        return {"format_kind": "reel_script", "hook_text": hook or "Owner story",
                "shots": shots or ["Owner screen recording walkthrough"]}
    return {"format_kind": "feed_carousel", "frame_count": len(frames_or_scenes),
            "aspect_ratio": CAROUSEL_ASPECT}


def product_facts_for(confirmed_facts: str) -> dict[str, Any]:
    """Shape confirmed facts as owner allowed claims for the pipeline."""
    return {"allowed_claims": [
        {"value": sentence, "confirmed": True, "source": "owner"}
        for sentence in split_fact_sentences(confirmed_facts)
    ]}


def idea_for(media_mode: str, confirmed_facts: str) -> str:
    """Describe the viral pack build for the pipeline idea line."""
    kind = "short video from one owner screen recording" if media_mode == "screen_recording" \
        else "swipeable carousel from owner screenshots"
    facts = normalize_confirmed_facts(confirmed_facts)
    if len(facts) > 500:
        facts = facts[:500].rstrip()
    return "Viral %s grounded in owner facts: %s" % (kind, facts)


def generation_id() -> str:
    """New viral generation id with the vgen_ prefix."""
    from uuid import uuid4

    return "vgen_" + uuid4().hex


def public_generation(row: dict[str, Any]) -> dict[str, Any]:
    """Public viral generation shape with stable list defaults."""
    data = dict(row)
    created = data.get("created_at")
    if hasattr(created, "isoformat"):
        data["created_at"] = created.isoformat()
    if not isinstance(data.get("asset_ids"), list):
        data["asset_ids"] = []
    if not isinstance(data.get("frames_or_scenes"), list):
        data["frames_or_scenes"] = []
    return data
