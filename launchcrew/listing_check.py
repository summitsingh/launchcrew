"""Slice 1 incremental feature: check a pasted listing title.

Pure helper only, no routes. The title is checked as one explicit claim
against caller-supplied confirmed claims, reusing the exact claim-level
verdicts from launchcrew.facts (supported, unsupported, conflicts).
Unsupported means not in confirmed facts. No invented facts: only the
passed confirmed_claims authorize, never demo template fields.

Also provides a deterministic Google Shopping title-rule lint, per Google
Merchant Center title rules: no promotional text, no all-caps words, and
no gimmicky repeated punctuation. Stdlib only.
"""

import re

from launchcrew.facts import (
    CONFLICTS,
    OWNER_SOURCE_LABEL,
    SUPPORTED,
    UNSUPPORTED,
    check_claim,
)

__all__ = [
    "CONFLICTS",
    "PROMOTIONAL_PHRASES",
    "SUPPORTED",
    "UNSUPPORTED",
    "check_listing_title",
    "lint_shopping_title",
]

# Fixed promotional-text list only. Narrow phrases from Google Merchant
# Center title rules; unknown hype stays unflagged rather than guessed.
PROMOTIONAL_PHRASES = (
    "free shipping",
    "free delivery",
    "free gift",
    "on sale",
    "best seller",
    "bestseller",
    "buy now",
    "limited time",
    "money back",
    "discount",
)

_ALL_CAPS_RE = re.compile(r"\b[A-Z]{2,}\b")
_REPEATED_PUNCT_RE = re.compile(r"([!?*~#])\1+|\.{3,}|-{3,}")


def check_listing_title(title, confirmed_claims):
    """Check one pasted listing title against confirmed claims.

    Args:
        title: the pasted listing title string.
        confirmed_claims: list of explicitly confirmed claim strings.

    Returns:
        The exact check_claim result dict with claim, verified, verdict
        (supported, unsupported, or conflicts), evidence, and reason.
    """
    facts = {
        "approved_claims": list(confirmed_claims) if confirmed_claims else [],
        "sources": [OWNER_SOURCE_LABEL],
    }
    return check_claim(title, facts)


def lint_shopping_title(title):
    """Lint a pasted title against Google Shopping title rules.

    Deterministic, stdlib only, pure: no I/O, no mutation. Flags
    promotional text (fixed phrase list, case-insensitive), all-caps
    words of two or more letters, and gimmicky repeated punctuation
    (repeated ! ? * ~ #, or runs of 3+ dots or dashes). Prices like
    $49.99 never flag: single dots between digits are not repetition.

    Returns a list of issue dicts with rule and match keys. An empty
    list means the title passes this lint.
    """
    text = title if isinstance(title, str) else ""
    issues = []
    lowered = text.lower()
    for phrase in PROMOTIONAL_PHRASES:
        if re.search(r"\b" + re.escape(phrase) + r"\b", lowered):
            issues.append({"rule": "promotional_text", "match": phrase})
    for word in _ALL_CAPS_RE.findall(text):
        issues.append({"rule": "all_caps", "match": word})
    for found in _REPEATED_PUNCT_RE.finditer(text):
        issues.append({"rule": "repeated_punctuation", "match": found.group()})
    return issues
