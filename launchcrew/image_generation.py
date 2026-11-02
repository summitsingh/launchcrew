"""AI image generation: provider-neutral interface plus prompt packs.

Three live providers are supported, each behind its own key: OpenAI,
xAI Grok, and Google Gemini Imagen. Generation jobs bind an owner
character (virtual model), a scene, and product context into one shoot
prompt, call exactly one provider, and store every returned image as
a media library asset with ai_generated provenance. Provider billing
happens on the owner's provider account; this codebase meters job
counts only and never caps provider spend.

Characters are original concepts the owner describes in words. No
real-person likeness is claimed, matched, or stored.

All helpers here are pure stdlib with no network, model, file, or
environment access. Reasons are plain human-readable strings naming
the rule that failed.
"""

from __future__ import annotations

from typing import Any

MODULE_VERSION = "image-generation/v1"

PROVIDERS = ("openai", "xai", "gemini")

PROVENANCE = "ai_generated"

NAME_MAX_CHARS = 120
APPEARANCE_MAX_CHARS = 2000
SCENE_MAX_CHARS = 2000
PROMPT_MAX_CHARS = 8000

NAME_MESSAGE = (
    "character name must be a nonempty string of at most %d characters"
    % NAME_MAX_CHARS
)
APPEARANCE_MESSAGE = (
    "character appearance must be a nonempty string of at most %d characters"
    % APPEARANCE_MAX_CHARS
)
SCENE_MESSAGE = (
    "scene must be a nonempty string of at most %d characters"
    % SCENE_MAX_CHARS
)
PROVIDER_MESSAGE = "image provider must be one of openai, xai, gemini"


def normalize_provider(provider: Any) -> str:
    """Return the canonical provider or raise ValueError naming the rule."""
    if isinstance(provider, str) and provider.strip() in PROVIDERS:
        return provider.strip()
    raise ValueError(PROVIDER_MESSAGE)


def normalize_character_name(name: Any) -> str:
    """Return the stripped character name or raise ValueError."""
    if not isinstance(name, str):
        raise ValueError(NAME_MESSAGE)
    cleaned = name.strip()
    if not cleaned or len(cleaned) > NAME_MAX_CHARS:
        raise ValueError(NAME_MESSAGE)
    return cleaned


def normalize_appearance(text: Any) -> str:
    """Return the stripped appearance notes or raise ValueError."""
    if not isinstance(text, str):
        raise ValueError(APPEARANCE_MESSAGE)
    cleaned = " ".join(text.strip().split())
    if not cleaned or len(cleaned) > APPEARANCE_MAX_CHARS:
        raise ValueError(APPEARANCE_MESSAGE)
    return cleaned


def normalize_scene(text: Any) -> str:
    """Return the stripped scene description or raise ValueError."""
    if not isinstance(text, str):
        raise ValueError(SCENE_MESSAGE)
    cleaned = " ".join(text.strip().split())
    if not cleaned or len(cleaned) > SCENE_MAX_CHARS:
        raise ValueError(SCENE_MESSAGE)
    return cleaned


def build_shoot_prompt(appearance: str, scene: str,
                       product_context: str = "") -> str:
    """Bind character, scene, and product context into one shoot prompt."""
    appearance_text = normalize_appearance(appearance)
    scene_text = normalize_scene(scene)
    prompt = ("Photorealistic product photograph. Model: %s. Scene: %s."
              % (appearance_text, scene_text))
    if isinstance(product_context, str) and product_context.strip():
        context = " ".join(product_context.strip().split())
        prompt += " Product context: %s." % context[:2000]
    prompt += (" Natural light, true colors, no text overlays, "
               "no watermarks, no brand logos except the product itself.")
    if len(prompt) > PROMPT_MAX_CHARS:
        raise ValueError("shoot prompt exceeds %d characters" % PROMPT_MAX_CHARS)
    return prompt
