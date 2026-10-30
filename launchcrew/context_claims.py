"""Context-aware material and care claim safety for one brand profile.

Isolated foundation only. No integration with Checker, receipts, human
review, backend, schema, or channel helpers. Those paths are owned by
another writer and are not imported or changed here.

Scope rule: nothing blocks unless the caller passes an explicitly enabled
Summit scope bound to a workspace identity. This prevents cross-brand
and cross-workspace leakage. All matching is whole word and whole phrase
only, case-insensitive, with no substring matches.

Owner contract encoded here:
- Affirmative genuine leather, real leather, full grain, and top grain
  are rejected even when confirmed. There is no confirmed path for the
  affirmative form under the Summit scope.
- Accurate negated explanations such as not genuine leather pass only
  with an explicitly confirmed negated sentence or explicit owner
  policy entry for that negated sentence. A bare confirmed phrase
  such as genuine leather never authorizes the negated form, and no
  blanket flag authorizes every material phrase.
- Durability, sustainability, patina, conditioning advice, machine
  washing, and break-in wording require a confirmed sentence or
  explicit owner policy entry for that sentence. A bare evidence
  phrase never authorizes a different subject. Negated care
  instructions such as do not machine wash also require confirmation.
  Supported no stiff break-in can pass with confirmation. Unsupported
  requires a break-in period stays blocked.
- Luxury, high-end, designer, cheap, and cheapest are style guidance.
  This module never blocks them.

Negation is positional and polarity aware. A negation word must appear
before the phrase in the same clause within a short window to count.
A trailing negation after the phrase is ignored. Two negations before
the phrase count as double negation and read as affirmative. Mixed
clauses are split so one negated clause cannot authorize an
affirmative clause elsewhere in the same sentence.
"""

from __future__ import annotations

import re
from typing import Any

SUMMIT_PROFILE_ID = "summit"

MODULE_VERSION = "context-claims/v1"

# Short lookback window: a negation must govern the phrase nearby.
# This keeps a trailing or distant unrelated "not" from flipping
# an affirmative material claim into a negated one.
_NEGATION_WINDOW = 4

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_SENTENCE_BREAK_RE = re.compile(r"(?<!\d)[.!?]+|[.!?]+(?!\d)|\n+")

_CLAUSE_SPLIT_RE = re.compile(
    r"[,;:\n]+|\bbut\b|\bhowever\b|\balthough\b|\bthough\b|\byet\b|\bwhile\b|\bwhereas\b",
    re.IGNORECASE,
)

_NEGATION_WORDS = frozenset({
    "not", "no", "never", "none", "without", "cannot",
    "neither", "nor", "nothing", "nowhere", "hardly", "scarcely",
    "barely", "isnt", "arent", "wasnt", "werent", "hasnt", "havent",
    "hadnt", "couldnt", "shouldnt", "wouldnt", "mustnt", "wont",
    "dont", "cant",
})

MATERIAL_PHRASES = (
    ("genuine", "leather"),
    ("real", "leather"),
    ("full", "grain"),
    ("top", "grain"),
)

EVIDENCE_GATED: dict[str, tuple[tuple[str, ...], ...]] = {
    "durability": (
        ("waterproof",),
        ("lifetime",),
        ("guaranteed", "for", "life"),
        ("unbreakable",),
    ),
    "sustainability": (
        ("eco", "friendly"),
        ("sustainable",),
        ("biodegradable",),
        ("carbon", "neutral"),
    ),
    "patina": (
        ("patina",),
    ),
    "conditioning": (
        ("conditioning",),
        ("conditioner",),
        ("condition", "leather"),
        ("oil", "leather"),
        ("wax", "leather"),
    ),
    "machine_wash": (
        ("machine", "wash",),
        ("machine", "washing",),
        ("machine", "washable",),
        ("machine", "washed",),
    ),
    "break_in": (
        ("break", "in"),
    ),
}

STYLE_GUIDANCE_NON_BLOCKING = (
    "luxury",
    "high-end",
    "designer",
    "cheap",
    "cheapest",
)


def _strip_apostrophes(text: str) -> str:
    # Contractions such as don't must tokenize as one word dont, not
    # as don plus t. Strip ASCII and curly apostrophes first so the
    # word tokenizer keeps the negation word intact.
    return (text or "").replace("'", "").replace("\u2019", "").replace("\u2018", "")


def _clean_word(word: str) -> str:
    return _strip_apostrophes(word).lower()


def _word_tokens(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    return _TOKEN_RE.findall(_strip_apostrophes(text).lower())


def _normalize_text(text: str) -> str:
    return " ".join(_word_tokens(text))


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _word_spans(text: str) -> list[tuple[str, int, int]]:
    # Span extraction runs on apostrophe-stripped text so contractions
    # stay whole. Positions are relative to the stripped form and are
    # used only for ordering, never returned to callers.
    cleaned = _strip_apostrophes(text or "")
    spans: list[tuple[str, int, int]] = []
    start: int | None = None
    for index, ch in enumerate(cleaned):
        if _is_word_char(ch):
            if start is None:
                start = index
        elif start is not None:
            spans.append((cleaned[start:index].lower(), start, index))
            start = None
    if start is not None:
        spans.append((cleaned[start:].lower(), start, len(cleaned)))
    return spans


def _split_clauses(sentence: str) -> list[str]:
    parts = _CLAUSE_SPLIT_RE.split(sentence or "")
    return [p.strip() for p in parts if p.strip()]


def _workspace_of(candidate: Any) -> str | None:
    if not isinstance(candidate, dict):
        return None
    raw = candidate.get("workspace_id", candidate.get("workspace"))
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _profile_of(candidate: Any) -> str | None:
    if not isinstance(candidate, dict):
        return None
    for key in ("profile", "profile_id", "brand_profile"):
        raw = candidate.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
    return None


class ScopeBindingError(ValueError):
    """Raised when a Summit scope binding is invalid or mismatched."""


# Focus adverbs that make "not X" read as an exclusive affirmative
# ("not only genuine leather" asserts genuine leather plus more).
# Any of these between the governing negation and the phrase makes
# the polarity ambiguous, so the occurrence is treated as
# affirmative and can never be authorized by a negated confirmation.
_AMBIGUOUS_FOCUS = frozenset({
    "only", "just", "merely", "simply", "solely",
})

# Coordinating conjunctions that bound negation scope. A negation in
# one conjunct never governs a phrase in a later conjunct, so "not
# blue and genuine leather" leaves genuine leather affirmative.
_COORD_BOUNDARY = frozenset({
    "and", "or", "plus",
})


def _scope_binding_state(scope: Any = None, policy: Any = None) -> str:
    """Return enabled or disabled, or raise ScopeBindingError.

    Genuinely disabled or unrelated scope (no scope, disabled flag,
    or non-Summit profile) returns disabled. A scope that claims to
    be an enabled Summit binding but carries no workspace, or a
    policy workspace or profile that mismatches the bound scope,
    raises instead of returning a quiet allow.
    """
    if not isinstance(scope, dict) or not scope:
        return "disabled"
    if scope.get("enabled") is not True:
        return "disabled"
    if _profile_of(scope) != SUMMIT_PROFILE_ID:
        return "disabled"
    scope_ws = _workspace_of(scope)
    if scope_ws is None:
        raise ScopeBindingError(
            "Summit scope is enabled but has no workspace_id; "
            "refusing to check without workspace binding."
        )
    if isinstance(policy, dict) and policy:
        policy_ws = _workspace_of(policy)
        if policy_ws is not None and policy_ws != scope_ws:
            raise ScopeBindingError(
                "Policy workspace does not match scope workspace; "
                "refusing to check a mismatched binding."
            )
        policy_profile = _profile_of(policy)
        if policy_profile is not None and policy_profile != SUMMIT_PROFILE_ID:
            raise ScopeBindingError(
                "Policy profile does not match Summit scope; "
                "refusing to check a mismatched binding."
            )
    return "enabled"


def is_scope_enabled(scope: Any = None, policy: Any = None) -> bool:
    """Return True only for an explicitly enabled Summit workspace scope.

    Genuinely disabled or unrelated scope returns False. An enabled
    Summit scope with a missing workspace, or a mismatched policy
    workspace or profile, raises ScopeBindingError instead of
    returning a quiet allow.
    """
    return _scope_binding_state(scope, policy) == "enabled"


def _confirmed_sentences(facts: Any, policy: Any) -> set[str]:
    """Collect explicitly confirmed full sentences only.

    Only full normalized sentences or clauses authorize a gated claim.
    Bare single phrases, blanket boolean flags, and broad permissions
    are never read here. Unknown blanket keys such as
    material_negation_allowed are intentionally ignored so they stay
    fail-closed.
    """
    confirmed: set[str] = set()
    if isinstance(facts, dict):
        for key in ("approved_claims", "confirmed_claims", "allowlist"):
            raw = facts.get(key)
            if isinstance(raw, (list, tuple)):
                for entry in raw:
                    if isinstance(entry, str) and entry.strip():
                        norm = _normalize_text(entry)
                        if norm:
                            confirmed.add(norm)
    if isinstance(policy, dict):
        for key in ("confirmed_claims", "confirmed_facts",
                    "confirmed_negations", "allowed_claims",
                    "owner_confirmed", "explicit_policies"):
            raw = policy.get(key)
            if isinstance(raw, (list, tuple)):
                for entry in raw:
                    if isinstance(entry, str) and entry.strip():
                        norm = _normalize_text(entry)
                        if norm:
                            confirmed.add(norm)
    return confirmed


def _sentence_supported(sentence: str, facts: Any, policy: Any) -> bool:
    norm = _normalize_text(sentence)
    if not norm:
        return False
    return norm in _confirmed_sentences(facts, policy)


def _find_phrase(spans: list[tuple[str, int, int]],
                 phrase: tuple[str, ...],
                 glue: frozenset[str] | None = None) -> list[int]:
    words = [w for w, _, _ in spans]
    width = len(phrase)
    found: list[int] = []
    if width == 0 or width > len(words):
        return found
    if not glue:
        for i in range(len(words) - width + 1):
            if words[i:i + width] == list(phrase):
                found.append(i)
        return found
    for i in range(len(words)):
        if words[i] != phrase[0]:
            continue
        idx = i + 1
        ok = True
        for k in range(1, width):
            while idx < len(words) and words[idx] in glue:
                idx += 1
            if idx >= len(words) or words[idx] != phrase[k]:
                ok = False
                break
            idx += 1
        if ok:
            found.append(i)
    return found


# Articles that may sit between a care verb and leather without
# changing the meaning, as in condition the leather. Skipped only
# when matching conditioning phrases, never for material phrases.
_ARTICLE_GLUE = frozenset({"the", "a", "an"})


def _phrase_polarity(tokens: list[str], phrase_start: int) -> tuple[bool, bool, bool, bool]:
    """Return (negated, double_negation, affirmative, ambiguous).

    Only negation words before the phrase within _NEGATION_WINDOW
    count, and only within the same coordinated conjunct: a
    conjunction such as and or or between the negation and the
    phrase restarts the scope, so the phrase reads as affirmative.
    A trailing negation after the phrase is ignored. Exactly one
    governing negation reads as negated. Two or more read as double
    negation, hence affirmative. A focus adverb such as only between
    the negation and the phrase marks ambiguous exclusive polarity,
    which always reads as affirmative and can never be authorized by
    a negated confirmation. When polarity cannot be established the
    occurrence stays affirmative and blocks.
    """
    lower = max(0, phrase_start - _NEGATION_WINDOW)
    for j in range(phrase_start - 1, lower - 1, -1):
        if _clean_word(tokens[j]) in _COORD_BOUNDARY:
            lower = j + 1
            break
    window = tokens[lower:phrase_start]
    cleaned = [_clean_word(tok) for tok in window]
    count = sum(1 for tok in cleaned if tok in _NEGATION_WORDS)
    if count >= 2:
        return (False, True, True, True)
    if count == 1:
        if any(tok in _AMBIGUOUS_FOCUS for tok in cleaned):
            return (False, False, True, True)
        return (True, False, False, False)
    return (False, False, True, False)


def detect_claims(text: Any) -> list[dict[str, Any]]:
    """Detect material and gated phrases with positional negation.

    Returns one entry per phrase occurrence with keys: phrase, group,
    negated, double_negation, affirmative, ambiguous, clause,
    sentence. Never raises on non-string input; returns an empty list
    instead.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    results: list[dict[str, Any]] = []
    sentences = [s.strip() for s in _SENTENCE_BREAK_RE.split(text) if s.strip()]
    for sentence in sentences:
        for clause in _split_clauses(sentence):
            spans = _word_spans(clause)
            if not spans:
                continue
            tokens = [w for w, _, _ in spans]
            for phrase in MATERIAL_PHRASES:
                for pos in _find_phrase(spans, phrase):
                    negated, double_negation, affirmative, ambiguous = _phrase_polarity(tokens, pos)
                    results.append({
                        "phrase": " ".join(phrase),
                        "group": "material",
                        "negated": bool(negated),
                        "double_negation": bool(double_negation),
                        "affirmative": bool(affirmative),
                        "ambiguous": bool(ambiguous),
                        "clause": clause,
                        "sentence": sentence,
                    })
            for group, phrases in EVIDENCE_GATED.items():
                for phrase in phrases:
                    glue = _ARTICLE_GLUE if group == "conditioning" else None
                    for pos in _find_phrase(spans, phrase, glue):
                        negated, double_negation, affirmative, ambiguous = _phrase_polarity(tokens, pos)
                        results.append({
                            "phrase": " ".join(phrase),
                            "group": group,
                            "negated": bool(negated),
                            "double_negation": bool(double_negation),
                            "affirmative": bool(affirmative),
                            "ambiguous": bool(ambiguous),
                            "clause": clause,
                            "sentence": sentence,
                        })
    results.sort(key=lambda r: (r["group"], r["phrase"], r["sentence"], r["clause"]))
    return results


def context_blocks_for_text(text: Any,
                             facts: Any = None,
                             policy: Any = None,
                             scope: Any = None) -> list[dict[str, str]]:
    """Return blocks for Summit-scoped context claims in text.

    Genuinely disabled or unrelated scope returns []. An enabled
    Summit scope with a missing workspace, or a mismatched policy
    workspace or profile, raises ScopeBindingError instead of
    returning a quiet allow. Style guidance terms never block.
    Affirmative material phrases always block, even when confirmed,
    including ambiguous exclusive forms such as not only genuine
    leather. Negated material needs an explicitly confirmed negated
    sentence or explicit owner policy entry for that sentence. Other
    gated groups need a confirmed sentence or explicit policy entry
    for that sentence, including negated care instructions. Subject
    changes stay blocked because only exact normalized sentence or
    clause matches authorize.
    """
    if _scope_binding_state(scope, policy) != "enabled":
        return []
    if not isinstance(text, str) or not text.strip():
        return []
    blocks: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    sentences = [s.strip() for s in _SENTENCE_BREAK_RE.split(text) if s.strip()]
    for sentence in sentences:
        for clause in _split_clauses(sentence):
            spans = _word_spans(clause)
            if not spans:
                continue
            tokens = [w for w, _, _ in spans]
            for phrase in MATERIAL_PHRASES:
                positions = _find_phrase(spans, phrase)
                if not positions:
                    continue
                name = " ".join(phrase)
                for pos in positions:
                    negated, double_negation, affirmative, ambiguous = _phrase_polarity(tokens, pos)
                    if affirmative:
                        key = ("material", name, sentence)
                        if key not in seen:
                            seen.add(key)
                            reason = (
                                "Blocked by context policy 'summit-material': "
                                "affirmative '%s' is never allowed, even when "
                                "confirmed. Omit the material claim." % name
                            )
                            if ambiguous and not double_negation:
                                reason = (
                                    "Blocked by context policy 'summit-material': "
                                    "ambiguous exclusive polarity around '%s' "
                                    "(such as not only) reads as affirmative "
                                    "and is never allowed, even when confirmed. "
                                    "Omit the material claim." % name
                                )
                            elif double_negation:
                                reason = (
                                    "Blocked by context policy 'summit-material': "
                                    "double negation around '%s' reads as "
                                    "affirmative and is never allowed. Omit the "
                                    "material claim." % name
                                )
                            blocks.append({"claim": sentence, "reason": reason,
                                           "group": "material", "phrase": name})
                        break
                    if _sentence_supported(sentence, facts, policy) or \
                            _sentence_supported(clause, facts, policy):
                        continue
                    key = ("material-negated", name, sentence)
                    if key not in seen:
                        seen.add(key)
                        blocks.append({
                            "claim": sentence,
                            "reason": (
                                "Blocked by context policy 'summit-material': "
                                "negated '%s' needs an explicitly confirmed "
                                "negated sentence or owner policy entry. Omit "
                                "it or add confirmation." % name
                            ),
                            "group": "material",
                            "phrase": name,
                        })
            for group, phrases in EVIDENCE_GATED.items():
                for phrase in phrases:
                    glue = _ARTICLE_GLUE if group == "conditioning" else None
                    positions = _find_phrase(spans, phrase, glue)
                    if not positions:
                        continue
                    name = " ".join(phrase)
                    for pos in positions:
                        negated, double_negation, affirmative, ambiguous = _phrase_polarity(tokens, pos)
                        if ambiguous and not double_negation:
                            key = (group, name, sentence)
                            if key not in seen:
                                seen.add(key)
                                blocks.append({
                                    "claim": sentence,
                                    "reason": (
                                        "Blocked by context policy 'summit-%s': "
                                        "ambiguous exclusive polarity around '%s' "
                                        "reads as affirmative and needs an explicitly "
                                        "confirmed sentence or owner policy "
                                        "entry; a negated confirmation never "
                                        "authorizes it." % (group, name)
                                    ),
                                    "group": group,
                                    "phrase": name,
                                })
                            break
                        if double_negation:
                            key = (group, name, sentence)
                            if key not in seen:
                                seen.add(key)
                                blocks.append({
                                    "claim": sentence,
                                    "reason": (
                                        "Blocked by context policy 'summit-%s': "
                                        "double negation around '%s' reads as "
                                        "affirmative and needs an explicitly "
                                        "confirmed sentence or owner policy "
                                        "entry." % (group, name)
                                    ),
                                    "group": group,
                                    "phrase": name,
                                })
                            break
                        # Affirmative and negated forms both need an
                        # exact confirmed sentence or explicit policy
                        # entry, including negated care instructions.
                        if _sentence_supported(sentence, facts, policy) or \
                                _sentence_supported(clause, facts, policy):
                            continue
                        key = (group, name, sentence)
                        if key in seen:
                            break
                        seen.add(key)
                        if negated:
                            reason = (
                                "Blocked by context policy 'summit-%s': "
                                "negated '%s' needs an explicitly confirmed "
                                "sentence or owner policy entry. Omit it or "
                                "add confirmation." % (group, name)
                            )
                        else:
                            reason = (
                                "Blocked by context policy 'summit-%s': "
                                "'%s' needs an explicitly confirmed sentence "
                                "or owner policy entry. Omit the claim or add "
                                "confirmation." % (group, name)
                            )
                        blocks.append({
                            "claim": sentence,
                            "reason": reason,
                            "group": group,
                            "phrase": name,
                        })
                        break
    blocks.sort(key=lambda b: (b["group"], b["phrase"], b["claim"]))
    return blocks


def check_candidate(candidate: Any,
                    facts: Any = None,
                    policy: Any = None,
                    scope: Any = None) -> dict[str, Any]:
    """Check one candidate string and return a stable summary dict.

    Raises ScopeBindingError for an invalid or mismatched Summit
    binding instead of returning a quiet allow.
    """
    blocks = context_blocks_for_text(candidate, facts=facts,
                                     policy=policy, scope=scope)
    text = candidate.strip() if isinstance(candidate, str) else ""
    return {
        "claim": text,
        "blocked": bool(blocks),
        "blocked_count": len(blocks),
        "blocks": blocks,
        "module": MODULE_VERSION,
        "scope_enabled": bool(is_scope_enabled(scope, policy)),
    }
