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
* ``parse_import_text``: parse text into an unconfirmed line-result dict.
* ``STRUCTURED_FIELDS``: per-field suggestion targets.
* ``parse_structured_import``: parse text into per-field suggestions the
  owner confirms field by field. Same bounds and unconfirmed guarantees as
  ``parse_import_text``; classification is deterministic stdlib heuristics
  only and never confirms anything.
* ``structured_proposal_digest``: stable digest identifying one structured
  proposal, used so a new paste never silently replaces a pending one.
* ``is_replace_conflict``: non-destructive replacement guard check.
"""

import hashlib
import json
import re
import unicodedata
from typing import TypedDict

PARSER_VERSION: str = "import-suggestions/v1"
STATUS_UNCONFIRMED: str = "unconfirmed"
STRUCTURED_PARSER_VERSION: str = "import-structured/v1"
REPLACE_WARNING: str = (
    "A pending unconfirmed proposal exists. "
    "The new import is held and did not replace it. "
    "Keep the pending proposal or confirm replacement."
)

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


STRUCTURED_FIELDS: tuple[str, ...] = (
    "material",
    "contents",
    "size",
    "price",
    "allowed_claim",
    "founder_note",
)


class StructuredFieldSuggestion(TypedDict):
    """One unconfirmed candidate line routed to a single fact field."""

    field: str
    text: str
    source: str
    status: str
    index: int


class StructuredImportResult(TypedDict):
    """Stable unconfirmed per-field parse result."""

    status: str
    source: str
    field_suggestions: list[StructuredFieldSuggestion]
    proposal_digest: str
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
    "REPLACE_WARNING",
    "STATUS_UNCONFIRMED",
    "STRUCTURED_FIELDS",
    "STRUCTURED_PARSER_VERSION",
    "SUPPORTED_SOURCES",
    "ImportSuggestion",
    "ImportSuggestionsResult",
    "StructuredFieldSuggestion",
    "StructuredImportResult",
    "is_replace_conflict",
    "parse_import_text",
    "parse_structured_import",
    "structured_proposal_digest",
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


_LABEL_PREFIX_RE: re.Pattern[str] = re.compile(
    r"^(?P<label>materials?|contents?|size|price|cost|"
    r"allowed\s+claims?|claims?|founder\s+note|note)\s*[:\-\|]\s*(?P<value>.+)$",
    re.IGNORECASE,
)
_PRICE_RE: re.Pattern[str] = re.compile(
    r"(\$|\\b(price|cost|usd|dollars?)\\b.*\\d|\\d.*\\b(dollars?|usd|bucks)\\b)",
    re.IGNORECASE,
)
_DIMENSION_RE: re.Pattern[str] = re.compile(r"\d\s*[xX]\s*\d|\d+\.\d+\s*[xX]\s*\d+")
_MEASURE_RE: re.Pattern[str] = re.compile(
    r"\d(\.\d+)?\s*(inch|inches|cm|mm|ft|feet|oz|ml|liters?|metres?|meters?)\b",
    re.IGNORECASE,
)
_SIZE_WORD_RE: re.Pattern[str] = re.compile(
    r"\b(xxs|xs|xl|xxl|xxxl|small|medium|large|compact|oversized|"
    r"bifold|petite|plus|dimensions?|measurements?|sized?)\b",
    re.IGNORECASE,
)
_MATERIAL_WORDS: frozenset[str] = frozenset({
    "leather", "canvas", "cotton", "nylon", "polyester", "wool", "silk",
    "denim", "suede", "linen", "metal", "wood", "wooden", "ceramic",
    "plastic", "rubber", "vegan", "stainless", "steel", "brass", "gold",
    "silver", "glass", "paper", "straw", "wicker", "full-grain", "grain",
})
_CONTENTS_WORDS: frozenset[str] = frozenset({
    "slots", "slot", "pockets", "pocket", "compartments", "compartment",
    "holds", "fits", "includes", "contains", "capacity", "cards", "laptop",
})
_FIRST_PERSON_RE: re.Pattern[str] = re.compile(r"^(i|we|my|our)\b", re.IGNORECASE)
_TOKEN_RE: re.Pattern[str] = re.compile(r"[A-Za-z0-9$]+(?:-[A-Za-z0-9$]+)*")
_DIGEST_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{64}$")


def _word_set(candidate: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(candidate)}


def _classify_field(candidate: str) -> str:
    """Route one normalized candidate line to a single fact field.

    Deterministic stdlib heuristics only: an explicit ``Label: value``
    prefix wins, then price, size, material, and contents signals, then a
    first-person single sentence for the founder note. Everything else is
    an allowed claim. The text itself is never altered here.
    """
    labeled = _LABEL_PREFIX_RE.match(candidate)
    if labeled:
        label = re.sub(r"\s+", " ", labeled.group("label").strip().lower())
        value = labeled.group("value").strip()
        if value:
            if label in ("material", "materials"):
                return "material"
            if label in ("content", "contents"):
                return "contents"
            if label == "size":
                return "size"
            if label in ("price", "cost"):
                return "price"
            if label in ("founder note", "note"):
                return "founder_note"
            return "allowed_claim"
    if _PRICE_RE.search(candidate):
        return "price"
    if _DIMENSION_RE.search(candidate) or _MEASURE_RE.search(candidate) or _SIZE_WORD_RE.search(candidate):
        return "size"
    words = _word_set(candidate)
    if words & _MATERIAL_WORDS:
        return "material"
    if words & _CONTENTS_WORDS:
        return "contents"
    if (
        _FIRST_PERSON_RE.search(candidate)
        and candidate[-1:] in (".", "!", "?")
        and len(candidate) <= 280
    ):
        return "founder_note"
    return "allowed_claim"


def structured_proposal_digest(field_suggestions: list[StructuredFieldSuggestion]) -> str:
    """Stable sha256 digest over ordered (field, text) pairs."""
    pairs = [(item["field"], item["text"]) for item in field_suggestions]
    canonical = json.dumps(pairs, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _check_digest(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string or null")
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if not _DIGEST_RE.match(cleaned):
        raise ValueError(f"{name} must be a 64-character hex digest or null")
    return cleaned


def is_replace_conflict(
    active_digest: str | None,
    proposal_digest: str,
    confirm_replace: bool = False,
) -> bool:
    """Report whether showing this proposal would silently replace a pending one.

    Returns True only when the caller holds a different pending proposal
    digest and has not explicitly confirmed replacement. Identical digests
    (same proposal pasted twice) and explicit replacement never conflict.
    Raises ValueError for a malformed active digest.
    """
    checked = _check_digest(active_digest, "active_digest")
    if not isinstance(proposal_digest, str) or not _DIGEST_RE.match(proposal_digest):
        raise ValueError("proposal_digest must be a 64-character hex digest")
    if not isinstance(confirm_replace, bool):
        raise ValueError("confirm_replace must be a boolean")
    if checked is None:
        return False
    if checked == proposal_digest:
        return False
    return not confirm_replace


def parse_structured_import(text: str, source: str) -> StructuredImportResult:
    """Parse pasted plain text into per-field unconfirmed suggestions.

    Args:
        text: Owner-pasted plain text with the same bounds as
            ``parse_import_text``.
        source: One of ``SUPPORTED_SOURCES``. Matched exactly and echoed
            back on the result and on every field suggestion.

    Returns:
        Dict with ``status`` always ``"unconfirmed"``, the echoed
        ``source``, an ordered ``field_suggestions`` list (each with a
        ``field`` from ``STRUCTURED_FIELDS``, normalized plain ``text``,
        ``source``, ``status`` ``"unconfirmed"``, and stable ``index``),
        a stable ``proposal_digest``, ``truncated`` flag, drop counts, and
        ``parser_version``. Empty or whitespace-only input yields zero
        field suggestions and the digest of the empty list.

    Raises:
        TypeError: ``text`` or ``source`` is not a string.
        ValueError: Unsupported ``source``, overlong input, or input with
            disallowed control characters.

    Notes:
        Classification is deterministic heuristics only and never confirms
        anything. Every field suggestion still needs an explicit per-field
        owner confirmation before any evidence use.
    """
    kind = _check_source(source)
    raw = _check_text(text)
    normalized_input = raw.replace("\r\n", "\n").replace("\r", "\n")

    field_suggestions: list[StructuredFieldSuggestion] = []
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
        if len(field_suggestions) >= MAX_SUGGESTIONS:
            truncated = True
            continue
        field_suggestions.append(
            {
                "field": _classify_field(candidate),
                "text": candidate,
                "source": kind,
                "status": STATUS_UNCONFIRMED,
                "index": len(field_suggestions),
            }
        )

    return {
        "status": STATUS_UNCONFIRMED,
        "source": kind,
        "field_suggestions": field_suggestions,
        "proposal_digest": structured_proposal_digest(field_suggestions),
        "truncated": truncated,
        "dropped_duplicates": dropped_duplicates,
        "dropped_overlong": dropped_overlong,
        "dropped_empty": dropped_empty,
        "parser_version": STRUCTURED_PARSER_VERSION,
    }
