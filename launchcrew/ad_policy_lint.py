"""Deterministic pre-publish policy lint for ad variant text (Slice 4).

Pure stdlib helper: text in, list of hits out. No I/O, no model calls,
no credentials. Flags three categories:

* ``absolute_claim``: absolute promises such as guaranteed / always /
  never / risk-free / 100%.
* ``personal_attribute``: second-person phrasing that asserts or implies
  a personal attribute (you are / are you / do you / your <noun>).
* ``shaming_comparison``: shaming words (ugly, loser, ...) and
  comparison phrasing (better than, worse than, ...).

Whole-word matching only, case-insensitive. Tokens split on any
non-alphanumeric character so punctuation and hyphens separate words
(risk-free matches risk free; guaranteed! matches guaranteed).
Substrings never match (guaranteedx, whenever, yourself are clean).
Multi-word patterns match only within the same sentence segment:
period, exclamation, question marks, and newlines break adjacency, so
"No. Risk is low." does not flag the "no risk" phrase.

Each hit is a dict with ``category``, ``match``, and a human-readable
``reason`` string. Hits are deduplicated and sorted by
(category, match) so output is deterministic. Not wired into
channel variants; integration happens later.
"""

import re

AD_POLICY_LINT_VERSION: str = "ad-policy/v1"

ABSOLUTE_WORDS = frozenset({
    "guaranteed",
    "guarantee",
    "guarantees",
    "always",
    "never",
    "instant",
    "instantly",
    "overnight",
    "miracle",
    "miracles",
    "cure",
    "cures",
    "cured",
})

ABSOLUTE_PHRASES = (
    ("no", "risk"),
    ("risk", "free"),
    ("zero", "risk"),
    ("100", "percent"),
)

_ABSOLUTE_PHRASE_SET = frozenset(ABSOLUTE_PHRASES)

# "100%" tokenizes to ["100"], which alone is not a claim, so the
# percent-sign form is detected with its own whole-token pattern.
_ABSOLUTE_PERCENT_RE = re.compile(r"(?<![a-z0-9])100\s*%(?![a-z0-9])")

PERSONAL_PHRASES = (
    ("you", "are"),
    ("you", "re"),  # you're
    ("are", "you"),
    ("do", "you"),
    ("did", "you"),
    ("have", "you"),
)

_PERSONAL_PHRASE_SET = frozenset(PERSONAL_PHRASES)

# Nouns that turn "your <noun>" into personal-attribute phrasing.
PERSONAL_YOUR_NOUNS = frozenset({
    "age",
    "weight",
    "race",
    "gender",
    "income",
    "religion",
    "health",
    "illness",
    "disease",
    "disability",
    "condition",
    "diagnosis",
    "orientation",
    "debt",
    "divorce",
})

SHAMING_WORDS = frozenset({
    "shame",
    "shaming",
    "shameful",
    "ugly",
    "stupid",
    "dumb",
    "loser",
    "losers",
    "idiot",
    "idiots",
    "pathetic",
    "worthless",
    "embarrassing",
    "embarrassed",
    "embarrassment",
})

SHAMING_PHRASES = (
    ("better", "than"),
    ("worse", "than"),
    ("shame", "on"),
    ("stop", "being"),
)

_SHAMING_PHRASE_SET = frozenset(SHAMING_PHRASES)

# "don't be ..." tokenizes to ["don", "t", "be"], so it needs a trigram.
_SHAMING_TRIGRAMS = frozenset({
    ("don", "t", "be"),
    ("do", "not", "be"),
})

_REASONS = {
    "absolute_claim": (
        "Remove the absolute promise and replace it with a specific, "
        "verifiable claim from the approved facts."
    ),
    "personal_attribute": (
        "Rephrase without asserting or implying a personal attribute; "
        "describe the product instead of the reader."
    ),
    "shaming_comparison": (
        "Remove the shaming or comparison wording and describe the "
        "product on its own merits."
    ),
}

_TOKEN = re.compile(r"[a-z0-9]+")
_SENTENCE_BREAK = re.compile(r"(?<!\d)[.!?]+|[.!?]+(?!\d)|\n+")


def _segments(text):
    """Tokenize text into per-sentence token lists (lowercase)."""
    if not isinstance(text, str):
        return []
    segments = []
    for part in _SENTENCE_BREAK.split(text.lower()):
        tokens = _TOKEN.findall(part)
        if tokens:
            segments.append(tokens)
    return segments


def _hit(category, match):
    return {
        "category": category,
        "match": match,
        "reason": (
            "Ad policy lint '" + category + "': matched '" + match + "'. "
            + _REASONS[category]
        ),
    }


def lint_ad_policy(text):
    """Lint ad variant text; return a sorted list of hit dicts.

    Each hit has ``category`` (absolute_claim, personal_attribute, or
    shaming_comparison), ``match`` (the word or phrase that fired), and
    ``reason`` (a human-readable explanation). Non-string or empty
    input yields ``[]``.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    found = set()
    if _ABSOLUTE_PERCENT_RE.search(text.lower()):
        found.add(("absolute_claim", "100%"))
    for tokens in _segments(text):
        for token in tokens:
            if token in ABSOLUTE_WORDS:
                found.add(("absolute_claim", token))
            if token in SHAMING_WORDS:
                found.add(("shaming_comparison", token))
        for index in range(len(tokens) - 1):
            pair = (tokens[index], tokens[index + 1])
            if pair in _ABSOLUTE_PHRASE_SET:
                found.add(("absolute_claim", pair[0] + " " + pair[1]))
            if pair in _PERSONAL_PHRASE_SET:
                found.add(("personal_attribute", pair[0] + " " + pair[1]))
            if pair[0] == "your" and pair[1] in PERSONAL_YOUR_NOUNS:
                found.add(("personal_attribute", pair[0] + " " + pair[1]))
            if pair in _SHAMING_PHRASE_SET:
                found.add(("shaming_comparison", pair[0] + " " + pair[1]))
        for index in range(len(tokens) - 2):
            trio = (tokens[index], tokens[index + 1], tokens[index + 2])
            if trio in _SHAMING_TRIGRAMS:
                found.add(("shaming_comparison", "don't be"))
    return [_hit(category, match) for category, match in sorted(found)]


def ad_policy_blocks(text):
    """Return True when lint_ad_policy finds any hit."""
    return bool(lint_ad_policy(text))
