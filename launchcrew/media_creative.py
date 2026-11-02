"""Media creative packs: AI-drafted scripts for owner-shot media.

Social-style generation step for the media library: given confirmed
facts and a target format, a bounded model call drafts the creative
pack (scene scripts, hooks, voiceover lines, captions, and shot
guidance for the owner to film). No pixels or audio are synthesized
here: every shot prompt guides owner-shot media, and every model
string is marked model_draft provenance, never an approved fact. The
pack is a draft attached to the run receipt; Checker approval and
export gates are unchanged.

All helpers are pure stdlib with no network, model, file, or
environment access. Reasons are plain human-readable strings naming
the rule that failed.
"""

from __future__ import annotations

from typing import Any

MODULE_VERSION = "media-creative/v1"

FORMATS = ("carousel", "short_video")

PROVENANCE = "model_draft_unverified"
ITEM_SOURCE = "model_draft"

CAROUSEL_MIN_FRAMES = 5
CAROUSEL_MAX_FRAMES = 10
SHORT_VIDEO_SCENES = 3

LINE_MAX_CHARS = 140
SHOT_MAX_CHARS = 200
FACTS_MAX_CHARS = 2000

SEPARATOR = " || "

FORMAT_MESSAGE = (
    "media_format_must_be_carousel_or_short_video: got %r"
)
FACTS_MESSAGE = (
    "confirmed_facts_required: confirmed facts must be a nonempty string "
    "of at most %d characters"
) % FACTS_MAX_CHARS
MODEL_NOT_CONFIGURED_MESSAGE = (
    "media_creative_unavailable: model key not configured, "
    "generation refused before any admission or provider call"
)
BUDGET_EXHAUSTED_MESSAGE = (
    "media_creative_budget_exhausted: model budget is zero, "
    "generation refused before any provider call"
)
MODEL_CALL_FAILED_MESSAGE = (
    "media_creative_unavailable: model call failed or returned "
    "an unusable pack; nothing was stored"
)
COUNT_MESSAGE = (
    "media_pack_count_out_of_bounds: %s needs %s items, got %d"
)
PARTS_MESSAGE = (
    "media_pack_shape_invalid: %s item %d needs %d parts joined "
    "by %r, got %d"
)
EMPTY_PART_MESSAGE = (
    "media_pack_part_empty: %s item %d part %d must be nonempty"
)
LINE_BOUND_MESSAGE = (
    "media_pack_line_too_long: %s item %d part %d allows at most "
    "%d characters, got %d"
)
EXTRA_KEYS_MESSAGE = (
    "media_pack_shape_invalid: unexpected keys %r"
)


def normalize_format(value: Any) -> str:
    """Return the canonical format or raise ValueError naming the rule."""
    if isinstance(value, str) and value.strip() in FORMATS:
        return value.strip()
    raise ValueError(FORMAT_MESSAGE % (value,))


def normalize_facts(text: Any) -> str:
    """Return stripped facts text or raise ValueError naming the rule."""
    if not isinstance(text, str):
        raise ValueError(FACTS_MESSAGE)
    cleaned = text.strip()
    if not cleaned or len(cleaned) > FACTS_MAX_CHARS:
        raise ValueError(FACTS_MESSAGE)
    return cleaned


def schema_hint_for(fmt: str) -> dict[str, list[str]]:
    """Return the strict-transport schema hint for the format."""
    fmt = normalize_format(fmt)
    if fmt == "carousel":
        return {"frames": ["caption" + SEPARATOR + "shot guidance"]}
    return {"scenes": ["hook" + SEPARATOR + "shot guidance" + SEPARATOR + "voiceover line"]}


def system_prompt_for(fmt: str) -> str:
    """Return the deterministic system prompt for the format."""
    fmt = normalize_format(fmt)
    if fmt == "carousel":
        return (
            "Draft a swipeable carousel creative pack in the brand voice. "
            "Return only JSON with key frames: a list of %d to %d strings. "
            "Each string is one frame as caption%s"
            "shot guidance for the owner to film. "
            "Captions copy the approved facts exactly and stay under %d characters. "
            "Never invent product claims, prices, or availability."
            % (CAROUSEL_MIN_FRAMES, CAROUSEL_MAX_FRAMES, SEPARATOR,
               LINE_MAX_CHARS)
        )
    return (
        "Draft a short video creative pack in the brand voice. "
        "Return only JSON with key scenes: a list of exactly %d strings. "
        "Each string is one scene as hook%s"
        "shot guidance for the owner to film%s"
        "voiceover line. Hooks and voiceover lines stay under %d characters "
        "and copy the approved facts exactly. "
        "Never invent product claims, prices, or availability."
        % (SHORT_VIDEO_SCENES, SEPARATOR, SEPARATOR, LINE_MAX_CHARS)
    )


def user_prompt_for(fmt: str, facts_text: str) -> str:
    """Return the deterministic user prompt binding the approved facts."""
    fmt = normalize_format(fmt)
    facts = normalize_facts(facts_text)
    return "Approved facts only:\n%s\n\nFormat: %s." % (facts, fmt)


def _split_parts(text: Any, expected: int, kind: str, index: int) -> list[str]:
    if not isinstance(text, str):
        raise ValueError(PARTS_MESSAGE % (kind, index, expected, SEPARATOR, 0))
    parts = [part.strip() for part in text.split(SEPARATOR)]
    if len(parts) != expected:
        raise ValueError(
            PARTS_MESSAGE % (kind, index, expected, SEPARATOR, len(parts)))
    return parts


def _checked_part(part: str, bound: int, kind: str, index: int,
                  position: int) -> str:
    if not part:
        raise ValueError(EMPTY_PART_MESSAGE % (kind, index, position))
    if len(part) > bound:
        raise ValueError(
            LINE_BOUND_MESSAGE % (kind, index, position, bound, len(part)))
    return part


def parse_pack(raw: Any, fmt: str) -> dict[str, Any]:
    """Parse strict model JSON into a validated creative pack.

    Raises ValueError naming the failed rule. Every drafted string
    carries model_draft provenance and the pack is marked unverified.
    """
    fmt = normalize_format(fmt)
    key = "frames" if fmt == "carousel" else "scenes"
    if not isinstance(raw, dict):
        raise ValueError(PARTS_MESSAGE % (key, 0, 0, SEPARATOR, 0))
    extra = sorted(set(raw) - {key})
    if extra:
        raise ValueError(EXTRA_KEYS_MESSAGE % (extra,))
    items = raw.get(key)
    if not isinstance(items, list):
        raise ValueError(
            COUNT_MESSAGE % (key, "a list of strings",
                             0 if items is None else -1))
    if fmt == "carousel":
        expected_count: tuple[int, ...] = tuple(
            range(CAROUSEL_MIN_FRAMES, CAROUSEL_MAX_FRAMES + 1))
        if len(items) not in expected_count:
            raise ValueError(
                COUNT_MESSAGE % (
                    key, "%d to %d strings"
                    % (CAROUSEL_MIN_FRAMES, CAROUSEL_MAX_FRAMES), len(items)))
        frames = []
        for index, entry in enumerate(items):
            caption, shot = _split_parts(entry, 2, "frame", index)
            frames.append({
                "caption": _checked_part(caption, LINE_MAX_CHARS,
                                         "frame", index, 1),
                "shot": _checked_part(shot, SHOT_MAX_CHARS,
                                      "frame", index, 2),
                "source": ITEM_SOURCE,
            })
        pack: dict[str, Any] = {
            "module_version": MODULE_VERSION,
            "format": fmt,
            "provenance": PROVENANCE,
            "frames": frames,
        }
    else:
        if len(items) != SHORT_VIDEO_SCENES:
            raise ValueError(
                COUNT_MESSAGE % (key, "exactly %d strings"
                                 % SHORT_VIDEO_SCENES, len(items)))
        scenes = []
        for index, entry in enumerate(items):
            hook, shot, voiceover = _split_parts(entry, 3, "scene", index)
            scenes.append({
                "hook": _checked_part(hook, LINE_MAX_CHARS,
                                      "scene", index, 1),
                "shot": _checked_part(shot, SHOT_MAX_CHARS,
                                      "scene", index, 2),
                "voiceover": _checked_part(voiceover, LINE_MAX_CHARS,
                                           "scene", index, 3),
                "source": ITEM_SOURCE,
            })
        pack = {
            "module_version": MODULE_VERSION,
            "format": fmt,
            "provenance": PROVENANCE,
            "scenes": scenes,
        }
    pack["voiceover_script"] = voiceover_script_for(pack)
    pack["captions"] = captions_for(pack)
    pack["shot_prompts"] = shot_prompts_for(pack)
    return pack


def voiceover_script_for(pack: dict[str, Any]) -> str:
    """Join the speakable lines of a validated pack in order."""
    if "scenes" in pack:
        return "\n".join(str(scene.get("voiceover", ""))
                         for scene in pack["scenes"])
    return "\n".join(str(frame.get("caption", ""))
                     for frame in pack.get("frames", []))


def captions_for(pack: dict[str, Any]) -> list[str]:
    """Return the caption or hook line of each pack item in order."""
    if "scenes" in pack:
        return [str(scene.get("hook", "")) for scene in pack["scenes"]]
    return [str(frame.get("caption", "")) for frame in pack.get("frames", [])]


def shot_prompts_for(pack: dict[str, Any]) -> list[str]:
    """Return the owner-shot guidance of each pack item in order."""
    items = pack.get("scenes", pack.get("frames", []))
    return [str(item.get("shot", "")) for item in items]
