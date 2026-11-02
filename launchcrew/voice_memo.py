"""Voice memo intake: transcript text attached to a run as draft context.

Voice-first founders speak instead of typing. This slice is the
code-only core: the owner supplies transcript text from any recording
flow, and it is stored on the run receipt with voice_transcript
provenance, a revision bump, and reset approval. Real speech-to-text
needs a transcription provider and is gated: no audio is accepted or
decoded here, only text the owner provides.

All helpers are pure stdlib with no network, model, file, or
environment access. Reasons are plain human-readable strings naming
the rule that failed.
"""

from __future__ import annotations

from typing import Any

MODULE_VERSION = "voice-memo/v1"

PROVENANCE = "voice_transcript"

TEXT_MAX_CHARS = 5000

TEXT_MESSAGE = (
    "voice transcript must be a nonempty string of at most %d characters"
    % TEXT_MAX_CHARS
)


def normalize_transcript(text: Any) -> str:
    """Return stripped transcript text or raise ValueError naming the rule."""
    if not isinstance(text, str):
        raise ValueError(TEXT_MESSAGE)
    cleaned = " ".join(text.strip().split())
    if not cleaned or len(cleaned) > TEXT_MAX_CHARS:
        raise ValueError(TEXT_MESSAGE)
    return cleaned


def build_memo_section(memo_id: str, transcript: str, revision: int,
                       actor: str) -> dict[str, Any]:
    """Build the receipt voice_memo section with transcript provenance."""
    return {"id": memo_id,
            "transcript": normalize_transcript(transcript),
            "media_provenance": PROVENANCE,
            "revision": int(revision),
            "actor": actor}
