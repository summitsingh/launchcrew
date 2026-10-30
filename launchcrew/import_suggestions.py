"""Parse owner text into UNCONFIRMED import suggestions.

Helper only. This module parses plain text the owner pasted from a listing
or an Instagram bio/caption, or text read from one Drive file the owner
selected in Picker, into candidate suggestions for a later explicit
confirmation UI. Every output stays explicitly unconfirmed.

Scope guarantees:

* Pure stdlib parser: deterministic, no I/O, no network, no database, no
  model calls, no photo transport, no filesystem access.
* Never marks anything as owner-confirmed and never writes to any approval
  or memory store. Callers must confirm each suggestion through a separate
  explicit UI step before any other use.
* Splits on newlines only and normalizes horizontal whitespace
  conservatively. Prices, percentages, dates, punctuation, and letter case
  pass through unchanged.
* Returns plain-text suggestions plus stable metadata (source kind,
  unconfirmed status, counts, parser version). No credentials, no invented
  citations, no HTML. Callers must escape text before HTML rendering.

Public API:

* ``SUPPORTED_SOURCES``: accepted source-kind labels.
* ``parse_import_text``: parse text into an unconfirmed result dict.
"""

import re
import unicodedata
from typing import TypedDict

PARSER_VERSION: str = "import-suggestions/v1"
STATUS_UNCONFIRMED: str = "unconfirmed"

SUPPORTED_SOURCES: tuple[str, ...] = (
    "listing",
    "instagram_bio",
    "instagram_caption",
    "drive_file",
)

MAX_INPUT_CHARS: int = 10000
MAX_SUGGESTIONS: int = 20
MAX_SUGGESTION_CHARS: int = 500

_ALLOWED_CONTROLS: frozenset[str] = frozenset({"\n", "\r", "\t"})
_HORIZONTAL_WS: re.Pattern[str] = re.compile(r"[ \t]+")


class ImportSuggestion(TypedDict):
    """One unconfirmed candidate line for later review."""

    text: str
    source: str
    status: str
    index: int


class ImportSuggestionsResult(TypedDict):
    """Stable unconfirmed parse result."""

    status: str
    source: str
    suggestions: list[ImportSuggestion]
    truncated: bool
    dropped_duplicates: int
    dropped_overlong: int
    dropped_empty: int
    parser_version: str


__all__ = [
    "MAX_INPUT_CHARS",
    "MAX_SUGGESTION_CHARS",
    "MAX_SUGGESTIONS",
    "PARSER_VERSION",
    "STATUS_UNCONFIRMED",
    "SUPPORTED_SOURCES",
    "ImportSuggestion",
    "ImportSuggestionsResult",
    "parse_import_text",
]


def _check_source(source: object) -> str:
    if not isinstance(source, str):
        raise TypeError("source must be a string")
    if source not in SUPPORTED_SOURCES:
        raise ValueError(f"unsupported source: {source!r}")
    return source


def _check_text(text: object) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(
            f"text exceeds {MAX_INPUT_CHARS} characters"
        )
    for char in text:
        if char in _ALLOWED_CONTROLS:
            continue
        if unicodedata.category(char) == "Cc":
            raise ValueError("text contains disallowed control characters")
    return text


def _normalize_candidate(line: str) -> str:
    """Collapse spaces/tabs and strip ends; keep all other characters."""
    return _HORIZONTAL_WS.sub(" ", line).strip(" \t")


def parse_import_text(text: str, source: str) -> ImportSuggestionsResult:
    """Parse pasted plain text into unconfirmed suggestions.

    Args:
        text: Owner-pasted plain text. Must be ``str`` with at most
            ``MAX_INPUT_CHARS`` characters and no control characters
            besides newline, carriage return, and tab.
        source: One of ``SUPPORTED_SOURCES``. Matched exactly and echoed
            back on the result and on every suggestion.

    Returns:
        Dict with ``status`` always ``"unconfirmed"``, the echoed
        ``source``, an ordered ``suggestions`` list (at most
        ``MAX_SUGGESTIONS`` items, each at most ``MAX_SUGGESTION_CHARS``
        characters), ``truncated`` flag, drop counts, and
        ``parser_version``. Each suggestion carries its normalized plain
        ``text``, ``source``, ``status`` ``"unconfirmed"``, and stable
        ``index``. Empty or whitespace-only input yields zero suggestions.

    Raises:
        TypeError: ``text`` or ``source`` is not a string.
        ValueError: Unsupported ``source``, overlong input, or input with
            disallowed control characters.

    Notes:
        Splitting is newline-only; bullet markers, pipes, prices (``$4``),
        percentages (``20%``), dates, punctuation, and case are preserved.
        Exact normalized duplicates collapse to the first occurrence and
        keep original order. Overlong candidates are skipped and counted;
        excess candidates beyond ``MAX_SUGGESTIONS`` set ``truncated``.
    """
    kind = _check_source(source)
    raw = _check_text(text)
    normalized_input = raw.replace("\r\n", "\n").replace("\r", "\n")

    suggestions: list[ImportSuggestion] = []
    seen: set[str] = set()
    dropped_duplicates = 0
    dropped_overlong = 0
    dropped_empty = 0
    truncated = False

    for line in normalized_input.split("\n"):
        candidate = _normalize_candidate(line)
        if not candidate:
            dropped_empty += 1
            continue
        if len(candidate) > MAX_SUGGESTION_CHARS:
            dropped_overlong += 1
            continue
        if candidate in seen:
            dropped_duplicates += 1
            continue
        seen.add(candidate)
        if len(suggestions) >= MAX_SUGGESTIONS:
            truncated = True
            continue
        suggestions.append(
            {
                "text": candidate,
                "source": kind,
                "status": STATUS_UNCONFIRMED,
                "index": len(suggestions),
            }
        )

    return {
        "status": STATUS_UNCONFIRMED,
        "source": kind,
        "suggestions": suggestions,
        "truncated": truncated,
        "dropped_duplicates": dropped_duplicates,
        "dropped_overlong": dropped_overlong,
        "dropped_empty": dropped_empty,
        "parser_version": PARSER_VERSION,
    }
