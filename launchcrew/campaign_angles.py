"""Campaign angle briefs from owner-confirmed facts.

This module is a pure standard-library helper. It takes a small nonempty
list of owner-confirmed fact strings and returns exactly five structured
draft briefs for later human review.

Not wired into any live campaign UI. Core or backend code may import
:func:`generate_campaign_angles` later; this module performs no wiring,
no model call, and no network, database, file, or other external action.

Interface (stable):
    from launchcrew.campaign_angles import generate_campaign_angles

    briefs = generate_campaign_angles([
        "The Blue Harbor demo notebook has 96 pages.",
        "The Blue Harbor demo notebook cover is blue.",
    ])

Each brief is a plain dict with these keys:

    label: short distinct editorial approach name (str).
    editorial_approach: one-line description of the approach (str).
    editorial_instruction: presentational instruction, clearly marked
        as not a fact (str).
    facts_used: exact fact strings quoted in this brief (list of str).
    fact_indexes: positions of facts_used in the input list (list of int).
    brief_text: readable draft containing the approval banner, the
        editorial instruction under its own heading, and the exact
        facts under their own heading (str).
    status: always "pending_owner_approval" (str).
    approved: always False (bool).

Bounds:
    MIN_FACTS = 1, MAX_FACTS = 8, MAX_FACT_CHARS = 500,
    MAX_BRIEF_CHARS = 6000, NUM_ANGLES = 5.

Rules:
    - Input must be a list or tuple of 1 to MAX_FACTS strings.
    - Each string must be nonblank and at most MAX_FACT_CHARS chars.
    - Exact duplicate strings are rejected.
    - Output keeps each supplied fact string byte-for-byte exact.
    - Output never invents facts and never turns the absence of
      facts into a claim about the product.
    - Editorial instructions live in their own field and heading and
      must not be read as factual claims. They add no benefit,
      audience, price, origin, guarantee, or performance assertion.
    - Every brief requires individual owner approval. This helper
      never approves anything.
    - Pure function: no input mutation, no randomness, no time,
      no global state, deterministic for the same input order.
"""

NUM_ANGLES = 5
MIN_FACTS = 1
MAX_FACTS = 8
MAX_FACT_CHARS = 500
MAX_BRIEF_CHARS = 6000
APPROVAL_STATUS = "pending_owner_approval"

ANGLE_LABELS = (
    "Spotlight Opener",
    "Sequential List",
    "Closing Spotlight",
    "Paired Opener",
    "Reverse List",
)

_APPROVAL_BANNER = (
    "STATUS: PENDING INDIVIDUAL OWNER APPROVAL -- "
    "DRAFT FOR REVIEW, NOT APPROVED."
)

_REVIEW_NOTE = (
    "REVIEW NOTE: This draft re-presents the quoted facts above. "
    "It requires individual owner approval before any use. "
    "No additional facts are asserted here."
)

__all__ = [
    "NUM_ANGLES",
    "MIN_FACTS",
    "MAX_FACTS",
    "MAX_FACT_CHARS",
    "MAX_BRIEF_CHARS",
    "APPROVAL_STATUS",
    "ANGLE_LABELS",
    "generate_campaign_angles",
    "generate_angles",
]


def _validate_facts(confirmed_facts):
    """Validate input and return a copied list of facts."""
    if isinstance(confirmed_facts, (str, bytes)):
        raise TypeError("confirmed_facts must be a list or tuple of strings")
    if not isinstance(confirmed_facts, (list, tuple)):
        raise TypeError("confirmed_facts must be a list or tuple of strings")
    facts = list(confirmed_facts)
    if len(facts) < MIN_FACTS:
        raise ValueError("At least one confirmed fact is required")
    if len(facts) > MAX_FACTS:
        raise ValueError("Too many facts: got %d, maximum is %d" % (len(facts), MAX_FACTS))
    for fact in facts:
        if not isinstance(fact, str):
            raise TypeError("Each confirmed fact must be a string")
        if not fact.strip():
            raise ValueError("Confirmed facts must not be blank")
        if len(fact) > MAX_FACT_CHARS:
            raise ValueError(
                "Fact too long: got %d chars, maximum is %d" % (len(fact), MAX_FACT_CHARS)
            )
    if len(set(facts)) != len(facts):
        raise ValueError("Duplicate facts are not allowed")
    return facts


def _single_quote_block(fact):
    return "QUOTE (verbatim):\n%s" % fact


def _numbered_block(facts):
    lines = []
    for i, fact in enumerate(facts, start=1):
        lines.append("%d. %s" % (i, fact))
    return "QUOTED FACTS (verbatim, in presentation order):\n" + "\n".join(lines)


def _bullet_block(facts):
    return "QUOTED FACTS (verbatim, in presentation order):\n" + "\n".join(
        "- %s" % fact for fact in facts
    )


def _build_brief(label, approach, instruction, facts, indexes, total):
    facts_used = [facts[i] for i in indexes]
    if label in ("Spotlight Opener", "Closing Spotlight"):
        facts_block = _single_quote_block(facts_used[0])
    elif label == "Paired Opener":
        facts_block = _bullet_block(facts_used)
    else:
        facts_block = _numbered_block(facts_used)
    brief_text = (
        "[%s] DRAFT FOR REVIEW -- %s\n\n"
        "EDITORIAL INSTRUCTION (not a fact): %s\n\n"
        "OWNER-CONFIRMED FACTS USED (%d of %d supplied, verbatim):\n"
        "%s\n\n%s"
        % (label, _APPROVAL_BANNER, instruction, len(facts_used), total, facts_block, _REVIEW_NOTE)
    )
    if len(brief_text) > MAX_BRIEF_CHARS:
        raise ValueError("Generated brief exceeds maximum length")
    return {
        "label": label,
        "editorial_approach": approach,
        "editorial_instruction": instruction,
        "facts_used": list(facts_used),
        "fact_indexes": list(indexes),
        "brief_text": brief_text,
        "status": APPROVAL_STATUS,
        "approved": False,
    }


def generate_campaign_angles(confirmed_facts):
    """Build exactly five draft campaign angle briefs.

    Args:
        confirmed_facts: nonempty list or tuple of 1 to MAX_FACTS
            owner-confirmed fact strings. Each must be nonblank,
            at most MAX_FACT_CHARS chars, with no exact duplicates.
            Order is preserved and selections are deterministic.

    Returns:
        A new list of exactly NUM_ANGLES dicts (see module docstring
        for keys). Labels are distinct. When one fact is supplied,
        all five briefs quote that same fact and differ only in
        editorial presentation.

    Raises:
        TypeError: if the input is not a list or tuple of strings.
        ValueError: if count, blank, duplicate, fact-length, or
            output-length bounds are violated.

    Purity:
        No input mutation, no model, network, database, file, or
        external action. Deterministic for the same input.
    """
    facts = _validate_facts(confirmed_facts)
    total = len(facts)
    last = total - 1
    pair = [0, 1] if total >= 2 else [0]
    specs = (
        (
            ANGLE_LABELS[0],
            "Single-fact spotlight on the first supplied fact.",
            "Display the single quoted fact on its own line. "
            "Do not reword it and do not add surrounding sentences.",
            [0],
        ),
        (
            ANGLE_LABELS[1],
            "Numbered list of the supplied facts in input order.",
            "List each quoted fact in the supplied order, one per "
            "numbered line. Do not reword, combine, or add sentences.",
            list(range(total)),
        ),
        (
            ANGLE_LABELS[2],
            "Single-fact spotlight on the last supplied fact.",
            "Display the single quoted fact as a standalone closing "
            "quote. Do not reword it and do not add surrounding sentences.",
            [last],
        ),
        (
            ANGLE_LABELS[3],
            "Opening bullet presentation from the start of the supplied order.",
            "Show each quoted fact as a separate bullet line in the "
            "supplied order. Do not merge facts into one sentence and "
            "do not add sentences.",
            pair,
        ),
        (
            ANGLE_LABELS[4],
            "Numbered list of the supplied facts in reverse input order.",
            "List each quoted fact in reverse supplied order, one per "
            "numbered line. Do not reword, combine, or add sentences.",
            list(reversed(range(total))),
        ),
    )
    briefs = [_build_brief(label, approach, instruction, facts, indexes, total) for label, approach, instruction, indexes in specs]
    if len(briefs) != NUM_ANGLES:
        raise ValueError("Internal error: expected exactly five briefs")
    return briefs


# Short alias for the same stable helper.
generate_angles = generate_campaign_angles
