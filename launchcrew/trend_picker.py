"""Optional trend format picker: Maker angle guidance only, never a fact source.

An owner may attach one short trend format description (a format or angle
seen trending) with a required source label. The attachment is screened
with the same banned-claim and superlative rules that guard drafts, so a
superlative or banned claim in the trend text never leaks into Maker
drafts. Drafts still derive claims only from confirmed product facts.

Pure stdlib helper: text in, attachment out. No I/O, no network, no models.
"""

import re

MODULE_VERSION = "trend-picker/v1"

ROLE = "maker_angle_guidance_only"

TREND_SOURCE_PRESETS = (
    "TikTok inspiration page",
    "Named creator format",
    "Seasonal format",
)

# Superlative and hype terms scrubbed from trend guidance. Covers the
# Checker strict word list plus the trend-specific terms named in the
# milestone spec. Matching is whole-word, case-insensitive; multi-word
# phrases match only within the same sentence segment.
SUPERLATIVE_WORDS = frozenset({
    "amazing",
    "incredible",
    "revolutionary",
    "unbeatable",
    "perfect",
    "best",
    "greatest",
    "fastest",
    "cheapest",
    "only",
    "guaranteed",
    "unmatched",
    "finest",
    "world-class",
    "worldclass",
})

SUPERLATIVE_PHRASES = (
    ("most", "durable"),
    ("world", "class"),
    ("number", "1"),
    ("number", "one"),
)

_TOKEN = re.compile(r"[a-z0-9]+")
_SENTENCE_BREAK = re.compile(r"(?<!\d)[.!?]+|[.!?]+(?!\d)|\n+")
_HASH_TAG_ONE = re.compile(r"#\s*1\b", re.IGNORECASE)

_SINGLE_WORDS = frozenset(word for word in SUPERLATIVE_WORDS if " " not in word and "-" not in word)

_WORD_TUPLE_TO_CANONICAL = {
    ("world", "class"): "world-class",
}

_PHRASE_SET = frozenset(SUPERLATIVE_PHRASES) | frozenset(_WORD_TUPLE_TO_CANONICAL)

_MAX_NGRAM = max([len(phrase) for phrase in _PHRASE_SET])

CLEAN_REPLACEMENT = "[removed]"

MAX_LABEL_CHARS = 280


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


def lint_trend_text(text):
    """List superlative or banned terms found in trend text, sorted.

    Each hit is ``{"term": match, "reason": ...}``. Non-string or blank
    input yields ``[]``.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    found = set()
    if _HASH_TAG_ONE.search(text):
        found.add("#1")
    for tokens in _segments(text):
        for token in tokens:
            if token in _SINGLE_WORDS:
                found.add(token)
        for size in range(2, _MAX_NGRAM + 1):
            for index in range(len(tokens) - size + 1):
                gram = tuple(tokens[index:index + size])
                if gram in _WORD_TUPLE_TO_CANONICAL:
                    found.add(_WORD_TUPLE_TO_CANONICAL[gram])
                elif gram in _PHRASE_SET:
                    found.add(" ".join(gram))
    return [
        {"term": match, "reason": "Superlative or banned claim removed from trend guidance; never a fact."}
        for match in sorted(found)
    ]


def _char_spans(text):
    """Yield (token, start, end, segment_id) for each token in text."""
    lowered = text.lower()
    break_ends = [match.end() for match in _SENTENCE_BREAK.finditer(text)]
    from bisect import bisect_right
    spans = []
    for match in _TOKEN.finditer(lowered):
        segment_id = bisect_right(break_ends, match.start())
        spans.append((match.group(), match.start(), match.end(), segment_id))
    return spans


def sanitize_trend_text(text):
    """Return (sanitized, screened_out_terms) for trend guidance text.

    Every span that lint_trend_text would flag is replaced with
    ``[removed]``; text without hits returns unchanged. Non-string
    input yields ``("", [])``.
    """
    if not isinstance(text, str):
        return "", []
    if not text.strip():
        return text, []
    hits = lint_trend_text(text)
    if not hits:
        return text, []
    hit_terms = {hit["term"] for hit in hits}
    spans = _char_spans(text)
    by_segment = {}
    for position, (token, start, end, segment_id) in enumerate(spans):
        by_segment.setdefault(segment_id, []).append((position, token, start, end))
    char_ranges = []
    for entries in by_segment.values():
        tokens = [token for _, token, _, _ in entries]
        found = []
        for index, token in enumerate(tokens):
            if token in _SINGLE_WORDS:
                found.append((index, index))
        for size in range(2, _MAX_NGRAM + 1):
            for index in range(len(tokens) - size + 1):
                gram = tuple(tokens[index:index + size])
                if gram in _WORD_TUPLE_TO_CANONICAL or gram in _PHRASE_SET:
                    found.append((index, index + size - 1))
        found.sort()
        merged = []
        for start_index, end_index in found:
            if merged and start_index <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end_index)
            else:
                merged.append([start_index, end_index])
        for start_index, end_index in merged:
            char_ranges.append((entries[start_index][2], entries[end_index][3]))
    for match in _HASH_TAG_ONE.finditer(text):
        char_ranges.append((match.start(), match.end()))
    if not char_ranges:
        return text, sorted(hit_terms)
    char_ranges.sort()
    merged_ranges = []
    for start, end in char_ranges:
        if merged_ranges and start <= merged_ranges[-1][1]:
            merged_ranges[-1][1] = max(merged_ranges[-1][1], end)
        else:
            merged_ranges.append([start, end])
    result = text
    for start, end in reversed(merged_ranges):
        result = result[:start] + CLEAN_REPLACEMENT + result[end:]
    result = re.sub(r"\s+", " ", result).strip()
    return result, sorted(hit_terms)


def validate_trend_input(label=None, source_label=None):
    """Validate an optional trend attachment, or raise ValueError.

    No trend (blank label and blank source) is valid and returns None.
    A label without a non-empty source_label raises naming
    'source_label'. An overlong label raises naming the length bound.
    """
    label_text = label if isinstance(label, str) else ("" if label is None else str(label))
    source_text = source_label if isinstance(source_label, str) else ("" if source_label is None else str(source_label))
    if not label_text.strip() and not source_text.strip():
        return None
    if label_text.strip() and not source_text.strip():
        raise ValueError("Trend format requires a non-empty source_label naming where the trend was seen")
    if not label_text.strip():
        raise ValueError("Trend format label must be non-empty when a source_label is provided")
    if len(label_text.strip()) > MAX_LABEL_CHARS:
        raise ValueError("Trend format label must be at most %d characters" % MAX_LABEL_CHARS)
    return {"label": label_text.strip(), "source_label": source_text.strip()}


def build_trend_attachment(label=None, source_label=None):
    """Build the receipt trend attachment, or None when no trend attached.

    Raises ValueError naming 'source_label' when a label is provided
    without a non-empty source label.
    """
    validated = validate_trend_input(label, source_label)
    if validated is None:
        return None
    sanitized, screened = sanitize_trend_text(validated["label"])
    return {
        "label": validated["label"],
        "source_label": validated["source_label"],
        "sanitized_guidance": sanitized,
        "screened_out_claims": list(screened),
        "role": ROLE,
        "guidance_only": True,
        "fact_source": False,
    }
