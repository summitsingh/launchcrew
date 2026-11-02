"""Engagement triage intake: deterministic routing for owner-logged items.

Competitor social inboxes triage comments and DMs with AI tagging and
suggested replies behind human approval. This slice is the code-only
core: the owner logs an item (platform comment or DM), a pure rule set
classifies it as question, complaint, praise, spam risk, or neutral,
and a deterministic template drafts a suggested reply. Approval then
marking handled is staged and explicit. There is no auto-send and no
live comment pull: platform reads and replies stay gated on platform
tokens and are never performed here.

All helpers are pure stdlib with no network, model, file, or
environment access. Reasons are plain human-readable strings naming
the rule that failed.
"""

from __future__ import annotations

from typing import Any

MODULE_VERSION = "engagement-triage/v1"

KINDS = ("comment", "dm")

TRIAGE_LABELS = ("question", "complaint", "praise", "spam_risk", "neutral")

REPLY_STATUSES = ("none", "draft", "approved", "handled")

HANDLE_MAX_CHARS = 120
TEXT_MAX_CHARS = 2000
REF_MAX_CHARS = 256

COMPLAINT_WORDS = ("refund", "broken", "wrong", "terrible", "awful", "scam",
                   "angry", "disgusting", "horrible", "lawsuit", "chargeback")

QUESTION_WORDS = ("?", "how", "when", "where", "why", "what", "which", "who",
                  "does", "is there", "can i", "do you")

PRAISE_WORDS = ("love", "amazing", "awesome", "thanks", "thank you", "great",
                "fantastic", "obsessed", "perfect")

SPAM_WORDS = ("free money", "click here", "crypto", "double your",
              "guaranteed profit", "wire transfer", "bitcoin giveaway")

SPAM_DOMAINS = ("http://", "https://", "www.", ".xyz", ".top", ".click")

TEXT_MESSAGE = (
    "engagement text must be a nonempty string of at most %d characters"
    % TEXT_MAX_CHARS
)
HANDLE_MESSAGE = (
    "author handle must be a nonempty string of at most %d characters"
    % HANDLE_MAX_CHARS
)
REF_MESSAGE = (
    "external reference must be a nonempty string of at most %d characters"
    % REF_MAX_CHARS
)
KIND_MESSAGE = "engagement kind must be one of comment, dm"
NO_DRAFT_MESSAGE = (
    "spam risk items get no suggested draft; log the item and leave it unhandled"
)


def normalize_kind(kind: Any) -> str:
    """Return the canonical kind or raise ValueError naming the rule."""
    if isinstance(kind, str) and kind.strip() in KINDS:
        return kind.strip()
    raise ValueError(KIND_MESSAGE)


def normalize_text(text: Any) -> str:
    """Return stripped item text or raise ValueError naming the rule."""
    if not isinstance(text, str):
        raise ValueError(TEXT_MESSAGE)
    cleaned = text.strip()
    if not cleaned or len(cleaned) > TEXT_MAX_CHARS:
        raise ValueError(TEXT_MESSAGE)
    return cleaned


def normalize_handle(handle: Any) -> str:
    """Return the stripped author handle or raise ValueError."""
    if not isinstance(handle, str):
        raise ValueError(HANDLE_MESSAGE)
    cleaned = handle.strip().lstrip("@")
    if not cleaned or len(cleaned) > HANDLE_MAX_CHARS:
        raise ValueError(HANDLE_MESSAGE)
    return cleaned


def normalize_ref(ref: Any) -> str:
    """Return the stripped external reference or raise ValueError."""
    if not isinstance(ref, str):
        raise ValueError(REF_MESSAGE)
    cleaned = ref.strip()
    if not cleaned or len(cleaned) > REF_MAX_CHARS:
        raise ValueError(REF_MESSAGE)
    return cleaned


def _contains_any(lowered: str, words: tuple[str, ...]) -> bool:
    return any(word in lowered for word in words)


def classify_text(text: str) -> str:
    """Classify item text with deterministic keyword rules.

    Priority is complaint, spam risk, question, praise, then neutral.
    """
    cleaned = normalize_text(text)
    lowered = " " + cleaned.lower() + " "
    if _contains_any(lowered, COMPLAINT_WORDS):
        return "complaint"
    if _contains_any(lowered, SPAM_WORDS) or _contains_any(lowered, SPAM_DOMAINS):
        return "spam_risk"
    if _contains_any(lowered, QUESTION_WORDS):
        return "question"
    if _contains_any(lowered, PRAISE_WORDS):
        return "praise"
    return "neutral"


def suggest_reply(triage: str, handle: str, snippet: str) -> str:
    """Draft a suggested reply for a classified item.

    Spam risk refuses with ValueError. Drafts are brand-safe templates;
    they never promise refunds, timelines, or outcomes.
    """
    if triage == "spam_risk":
        raise ValueError(NO_DRAFT_MESSAGE)
    clean_handle = normalize_handle(handle)
    clean_snippet = normalize_text(snippet)[:140]
    if triage == "complaint":
        return ("Hi %s, thank you for flagging this. We are sorry about "
                "your experience with \"%s\". Please reply here with your "
                "order details and we will look into it right away."
                % (clean_handle, clean_snippet))
    if triage == "question":
        return ("Hi %s, great question about \"%s\". The short answer: check "
                "the pinned product facts on our page, and tell us if you "
                "want a closer look at anything specific."
                % (clean_handle, clean_snippet))
    if triage == "praise":
        return ("Hi %s, thank you for the kind words about \"%s\". It means "
                "a lot to our small team."
                % (clean_handle, clean_snippet))
    return ("Hi %s, thanks for writing about \"%s\". We read every note and "
            "will follow up if we need anything else."
            % (clean_handle, clean_snippet))
