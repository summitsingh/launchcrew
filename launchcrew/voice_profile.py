"""Voice style profile helper (isolated, dependency-free).

This module validates small synthetic style profiles and checks candidate
text against a bounded banned-term list. It is intentionally isolated for
later core integration and performs no model, database, network, file, or
environment access.

Public contracts:
- ``validate_profile(profile)`` validates an untrusted mapping and returns
  an independent snapshot dict. It never mutates its input.
- ``check_text(snapshot, candidate)`` scans candidate text and returns a
  stable dict with ``blocked``, ``matches``, ``match_count``, and ``notice``.
  It never returns candidate text or profile examples.
- ``STYLE_ONLY_NOTICE`` states the style-only boundary and is included in
  both the snapshot metadata and every check result.

Profile shape (untrusted input to ``validate_profile``):
- ``{"examples": [...], "banned_terms": [...]}``. Only these top-level keys
  are accepted. ``banned_terms`` is optional and defaults to ``[]``.
- ``examples``: list of 3 to 5 dicts, each exactly
  ``{"input": str, "output": str}``. Each string must be non-empty after
  stripping and within its length bound. The sum of all input/output
  lengths must fit the aggregate bound.
- ``banned_terms``: list of at most ``MAX_BANNED_TERMS`` strings. Each term
  must be non-empty after stripping, within ``MAX_TERM_CHARS``, and contain
  at least one letter or digit. Pure punctuation or whitespace is rejected.

Matching rules (used by ``check_text``):
- Unicode-aware and case-insensitive via ``str.casefold``.
- Whole-word only: a banned term matches only complete word tokens, never
  a substring inside a larger word. A word character is
  ``ch.isalnum() or ch == "_"`` (Unicode alphanumeric plus underscore).
- Multiword terms are normalized to word-token sequences. Any run of one or
  more non-word characters in the candidate (spaces, tabs, newlines,
  punctuation) matches a separator between term words. Leading or trailing
  punctuation around a phrase does not prevent a match.
- No regular expressions are used, so banned terms are never interpolated
  into patterns.
- Deterministic: snapshot terms are deduplicated case-insensitively and
  sorted by ``(casefold, original)``; matches are sorted the same way and
  positions within a term are ascending.

Style boundary:
- Examples are synthetic style references only. They are never factual
  evidence or authority, never bypass Checker, and never become confirmed
  facts. Callers must supply synthetic text only and must not place real
  names, emails, account IDs, photos, secrets, or other personal data in
  profiles. This module validates shape and length only; it does not detect
  personal data.
"""

from __future__ import annotations

from typing import Any

MIN_EXAMPLES = 3
MAX_EXAMPLES = 5
MAX_INPUT_CHARS = 2000
MAX_OUTPUT_CHARS = 2000
MAX_TOTAL_CHARS = 8000
MAX_BANNED_TERMS = 50
MAX_TERM_CHARS = 80
MAX_CANDIDATE_CHARS = 10000

STYLE_ONLY_NOTICE = (
    "Style references only: examples are synthetic style references, "
    "never factual evidence or authority; they never bypass Checker "
    "and never become confirmed facts."
)

_PROFILE_KEYS = frozenset({"examples", "banned_terms"})
_EXAMPLE_KEYS = frozenset({"input", "output"})


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _word_tokens(text: str) -> list[str]:
    """Return casefolded word tokens in order."""
    tokens: list[str] = []
    current: list[str] = []
    for ch in text:
        if _is_word_char(ch):
            current.append(ch)
        elif current:
            tokens.append("".join(current).casefold())
            current = []
    if current:
        tokens.append("".join(current).casefold())
    return tokens


def _word_tokens_with_spans(text: str) -> list[tuple[str, int, int]]:
    """Return (casefolded token, start, end) for each word token."""
    spans: list[tuple[str, int, int]] = []
    start: int | None = None
    for index, ch in enumerate(text):
        if _is_word_char(ch):
            if start is None:
                start = index
        elif start is not None:
            spans.append((text[start:index].casefold(), start, index))
            start = None
    if start is not None:
        spans.append((text[start:].casefold(), start, len(text)))
    return spans


def _normalize_term(raw: str, index: int) -> tuple[str, tuple[str, ...]]:
    stripped = raw.strip()
    if not stripped:
        raise ValueError(f"banned_terms[{index}] must not be empty or whitespace")
    if len(stripped) > MAX_TERM_CHARS:
        raise ValueError(
            f"banned_terms[{index}] exceeds {MAX_TERM_CHARS} characters"
        )
    tokens = tuple(_word_tokens(stripped))
    if not tokens:
        raise ValueError(
            f"banned_terms[{index}] must contain at least one letter or digit"
        )
    return stripped, tokens


def validate_profile(profile: Any) -> dict[str, Any]:
    """Validate an untrusted profile mapping and return a snapshot.

    Args:
        profile: Expected mapping with ``examples`` (required) and
            ``banned_terms`` (optional).

    Returns:
        A new snapshot dict with ``examples`` (list of input/output dicts),
        ``banned_terms`` (deduplicated, sorted list), and ``meta`` carrying
        the style-only notice and counts.

    Raises:
        TypeError: If the profile, examples, or terms have the wrong types.
        ValueError: If counts, lengths, shapes, or term content are invalid.
    """
    if not isinstance(profile, dict):
        raise TypeError("profile must be a dict")
    unknown = set(profile.keys()) - _PROFILE_KEYS
    if unknown:
        raise ValueError(f"unknown profile keys: {sorted(unknown)}")
    if "examples" not in profile:
        raise ValueError("profile is missing required key 'examples'")

    examples = profile["examples"]
    if not isinstance(examples, list):
        raise TypeError("profile['examples'] must be a list")
    if not MIN_EXAMPLES <= len(examples) <= MAX_EXAMPLES:
        raise ValueError(
            f"examples must contain {MIN_EXAMPLES} to {MAX_EXAMPLES} items, "
            f"got {len(examples)}"
        )

    copied: list[dict[str, str]] = []
    total = 0
    for index, item in enumerate(examples):
        if not isinstance(item, dict):
            raise TypeError(f"examples[{index}] must be a dict")
        keys = set(item.keys())
        if keys != _EXAMPLE_KEYS:
            raise ValueError(
                f"examples[{index}] must have exactly keys {sorted(_EXAMPLE_KEYS)}, "
                f"got {sorted(keys)}"
            )
        text_in = item["input"]
        text_out = item["output"]
        if not isinstance(text_in, str):
            raise TypeError(f"examples[{index}]['input'] must be a string")
        if not isinstance(text_out, str):
            raise TypeError(f"examples[{index}]['output'] must be a string")
        if not text_in.strip():
            raise ValueError(f"examples[{index}]['input'] must not be empty")
        if not text_out.strip():
            raise ValueError(f"examples[{index}]['output'] must not be empty")
        if len(text_in) > MAX_INPUT_CHARS:
            raise ValueError(
                f"examples[{index}]['input'] exceeds {MAX_INPUT_CHARS} characters"
            )
        if len(text_out) > MAX_OUTPUT_CHARS:
            raise ValueError(
                f"examples[{index}]['output'] exceeds {MAX_OUTPUT_CHARS} characters"
            )
        total += len(text_in) + len(text_out)
        copied.append({"input": text_in, "output": text_out})

    if total > MAX_TOTAL_CHARS:
        raise ValueError(
            f"examples total {total} characters exceeds {MAX_TOTAL_CHARS}"
        )

    raw_terms: Any = profile.get("banned_terms", [])
    if not isinstance(raw_terms, list):
        raise TypeError("profile['banned_terms'] must be a list")
    if len(raw_terms) > MAX_BANNED_TERMS:
        raise ValueError(
            f"banned_terms must contain at most {MAX_BANNED_TERMS} items, "
            f"got {len(raw_terms)}"
        )

    by_tokens: dict[tuple[str, ...], str] = {}
    for index, term in enumerate(raw_terms):
        if not isinstance(term, str):
            raise TypeError(f"banned_terms[{index}] must be a string")
        stripped, tokens = _normalize_term(term, index)
        existing = by_tokens.get(tokens)
        if existing is None:
            by_tokens[tokens] = stripped
        else:
            by_tokens[tokens] = min(
                existing, stripped, key=lambda s: (s.casefold(), s)
            )

    ordered_terms = sorted(by_tokens.values(), key=lambda s: (s.casefold(), s))

    return {
        "examples": copied,
        "banned_terms": ordered_terms,
        "meta": {
            "style_only": True,
            "notice": STYLE_ONLY_NOTICE,
            "example_count": len(copied),
            "banned_term_count": len(ordered_terms),
        },
    }


def check_text(snapshot: Any, candidate: Any) -> dict[str, Any]:
    """Check candidate text against a validated snapshot.

    Args:
        snapshot: Snapshot dict returned by ``validate_profile``.
        candidate: Candidate text to scan.

    Returns:
        Dict with ``blocked`` (bool), ``matches`` (list of
        ``{"term", "count", "positions"}`` sorted by term), ``match_count``
        (total occurrences), and ``notice`` (style-only text). The result
        never includes candidate text or profile examples.

    Raises:
        TypeError: If the snapshot or candidate has the wrong type.
        ValueError: If the snapshot shape or candidate length is invalid.
    """
    if not isinstance(snapshot, dict):
        raise TypeError("snapshot must be a dict")
    if "banned_terms" not in snapshot:
        raise ValueError("snapshot is missing 'banned_terms'")
    terms = snapshot["banned_terms"]
    if not isinstance(terms, (list, tuple)):
        raise TypeError("snapshot['banned_terms'] must be a list")
    if not isinstance(candidate, str):
        raise TypeError("candidate must be a string")
    if len(candidate) > MAX_CANDIDATE_CHARS:
        raise ValueError(
            f"candidate exceeds {MAX_CANDIDATE_CHARS} characters"
        )

    normalized: list[tuple[str, tuple[str, ...]]] = []
    for index, term in enumerate(terms):
        if not isinstance(term, str):
            raise TypeError(f"snapshot banned_terms[{index}] must be a string")
        stripped = term.strip()
        if not stripped:
            raise ValueError(f"snapshot banned_terms[{index}] must not be empty")
        tokens = tuple(_word_tokens(stripped))
        if not tokens:
            raise ValueError(
                f"snapshot banned_terms[{index}] must contain a letter or digit"
            )
        normalized.append((stripped, tokens))
    normalized.sort(key=lambda pair: (pair[0].casefold(), pair[0]))

    spans = _word_tokens_with_spans(candidate)
    token_words = [word for word, _, _ in spans]
    token_starts = [start for _, start, _ in spans]

    matches: list[dict[str, Any]] = []
    for original, tokens in normalized:
        width = len(tokens)
        positions: list[int] = []
        if width <= len(token_words):
            for i in range(len(token_words) - width + 1):
                if token_words[i : i + width] == list(tokens):
                    positions.append(token_starts[i])
        if positions:
            matches.append(
                {"term": original, "count": len(positions), "positions": positions}
            )

    matches.sort(key=lambda m: (str(m["term"]).casefold(), str(m["term"])))
    total = sum(m["count"] for m in matches)
    return {
        "blocked": bool(matches),
        "matches": matches,
        "match_count": total,
        "notice": STYLE_ONLY_NOTICE,
    }
