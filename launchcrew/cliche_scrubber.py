"""Spec-to-benefit cliche scrubber.

Pure stdlib helper: text in, hits out. No I/O, no network, no models.
Flags generic marketing cliches (buzzwords and stock phrases) so copy
can be rewritten with verified, concrete product specifications.

Matching is whole-word, case-insensitive. Text is lowercased and split
into alphanumeric tokens, so punctuation and hyphens separate words:
"game-changer", "game changer", and "GAME CHANGER!" all match, while
substrings never match ("elevation", "gameplay", and "levels" are
clean). Multi-word patterns match only within the same sentence
segment: periods, exclamation and question marks, and newlines break
adjacency, so "Our favorite game. Changer cables cost $12." is clean.

Each hit is a dict with ``cliche`` (the matched word or phrase) and a
human-readable ``reason`` string. Hits are deduplicated and sorted so
output is deterministic.
"""

import re
from bisect import bisect_right

CLICHE_SCRUBBER_VERSION: str = "cliche-scrubber/v1"

CLICHE_WORDS = frozenset({
    "game-changer",
    "game-changing",
    "revolutionize",
    "revolutionary",
    "unleash",
    "next-level",
    "elevate",
    "supercharge",
    "seamlessly",
    "cutting-edge",
    "groundbreaking",
    "transformative",
    "redefine",
    "redefining",
    "miracle",
})

CLICHE_PHRASES = (
    ("game", "changer"),
    ("game", "changing"),
    ("next", "level"),
    ("unleash", "your", "potential"),
    ("elevate", "your", "routine"),
    ("take", "to", "the", "next", "level"),
)

CLICHE_REASON = (
    "Generic marketing cliché; replace with a verified, "
    "concrete product specification."
)

CLEAN_REPLACEMENT = "[cliche removed]"

_TOKEN = re.compile(r"[a-z0-9]+")
_SENTENCE_BREAK = re.compile(r"(?<!\d)[.!?]+|[.!?]+(?!\d)|\n+")


def _word_parts(entry):
    return tuple(_TOKEN.findall(entry.lower()))


_SINGLE_WORDS = frozenset(
    _word_parts(entry)[0]
    for entry in CLICHE_WORDS
    if len(_word_parts(entry)) == 1
)

_WORD_TUPLE_TO_CANONICAL = {
    _word_parts(entry): entry
    for entry in CLICHE_WORDS
    if len(_word_parts(entry)) > 1
}

_PHRASE_SET = frozenset(CLICHE_PHRASES)

_MAX_NGRAM = max(
    [len(parts) for parts in _WORD_TUPLE_TO_CANONICAL]
    + [len(phrase) for phrase in _PHRASE_SET]
)


def _segments(text):
    """Tokenize text into per-sentence lowercase token lists."""
    if not isinstance(text, str):
        return []
    segments = []
    for part in _SENTENCE_BREAK.split(text.lower()):
        tokens = _TOKEN.findall(part)
        if tokens:
            segments.append(tokens)
    return segments


def lint_cliches(text):
    """Lint copy for marketing cliches; return a sorted list of hits.

    Each hit is ``{"cliche": match, "reason": ...}`` where ``match``
    is the banned word (e.g. "game-changer", "miracle") or the banned
    phrase joined with single spaces (e.g. "next level",
    "unleash your potential"). Non-string or blank input yields ``[]``.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    found = set()
    for tokens in _segments(text):
        for token in tokens:
            if token in _SINGLE_WORDS:
                found.add(token)
        for size in range(2, _MAX_NGRAM + 1):
            for index in range(len(tokens) - size + 1):
                gram = tuple(tokens[index:index + size])
                if gram in _WORD_TUPLE_TO_CANONICAL:
                    found.add(_WORD_TUPLE_TO_CANONICAL[gram])
                if gram in _PHRASE_SET:
                    found.add(" ".join(gram))
    return [
        {"cliche": match, "reason": CLICHE_REASON}
        for match in sorted(found)
    ]


def has_cliche(text):
    """Return True when lint_cliches finds any hit."""
    return bool(lint_cliches(text))


def _char_spans(text):
    """Yield (token, start, end, segment_id) for each token in text."""
    lowered = text.lower()
    break_ends = [match.end() for match in _SENTENCE_BREAK.finditer(text)]
    spans = []
    for match in _TOKEN.finditer(lowered):
        segment_id = bisect_right(break_ends, match.start())
        spans.append((match.group(), match.start(), match.end(), segment_id))
    return spans


def clean_cliches(text):
    """Return a copy of text with cliche spans replaced.

    Every span that lint_cliches would flag is replaced with
    ``[cliche removed]``; copy without cliches is returned unchanged.
    Non-string input yields ``""``.
    """
    if not isinstance(text, str):
        return ""
    if not text.strip():
        return text
    spans = _char_spans(text)
    by_segment = {}
    for position, (token, start, end, segment_id) in enumerate(spans):
        by_segment.setdefault(segment_id, []).append(
            (position, token, start, end)
        )
    char_ranges = []
    for entries in by_segment.values():
        tokens = [token for _, token, _, _ in entries]
        hits = []
        for index, token in enumerate(tokens):
            if token in _SINGLE_WORDS:
                hits.append((index, index))
        for size in range(2, _MAX_NGRAM + 1):
            for index in range(len(tokens) - size + 1):
                gram = tuple(tokens[index:index + size])
                if (
                    gram in _WORD_TUPLE_TO_CANONICAL
                    or gram in _PHRASE_SET
                ):
                    hits.append((index, index + size - 1))
        hits.sort()
        merged = []
        for start_index, end_index in hits:
            if merged and start_index <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end_index)
            else:
                merged.append([start_index, end_index])
        for start_index, end_index in merged:
            char_ranges.append(
                (entries[start_index][2], entries[end_index][3])
            )
    if not char_ranges:
        return text
    char_ranges.sort()
    result = text
    for start, end in reversed(char_ranges):
        result = result[:start] + CLEAN_REPLACEMENT + result[end:]
    return result
